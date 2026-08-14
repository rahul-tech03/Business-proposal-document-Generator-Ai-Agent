"""
Verifies Agent.stream_run()'s event emission and state-merging logic.

Swaps `agent._compiled_graph` for a fake whose `.stream()` drives the REAL
plan/execute/reflect/render node functions in agent.py, yielding updates in
exactly the shape LangGraph's `stream(..., stream_mode="updates")` produces.
This isolates "is the event/merge logic correct" from "is a live LLM
configured" -- it runs fully offline, deterministically, no API key needed.

This is also the direct regression test for the original bug this project
started from: every step event must resolve to a real terminal status
(done / revised / recovered / failed) and never sit at "pending" once
execution has actually finished.

Usage: python test_stream.py
"""
import json

import agent


class FakeCompiledGraph:
    """Drives the real node functions in the real order, yielding updates
    in exactly the shape agent.py's Agent.stream_run() expects to consume."""

    def stream(self, initial_state, stream_mode="updates"):
        assert stream_mode == "updates"
        state = dict(initial_state)

        for node_name, node_fn in [
            ("plan", agent.plan_node),
            ("execute", agent.execute_node),
            ("reflect", agent.reflect_node),
            ("render", agent.render_node),
        ]:
            partial = node_fn(state)
            # apply the same reducers state.py declares, so `state` fed into
            # the next node looks like what the real graph would produce
            for key, value in partial.items():
                if key in ("logs", "steps", "reflection_notes"):
                    state[key] = state.get(key, []) + value
                else:
                    state[key] = value
            yield {node_name: partial}


def run_and_check(request_text: str, label: str):
    print("\n" + "=" * 90)
    print("TEST:", label)
    print("=" * 90)

    agent._compiled_graph = FakeCompiledGraph()  # swap in the fake -- keeps this test fast/offline

    events = list(agent.Agent().stream_run(request_text))

    types_seen = [e["type"] for e in events]
    print("Event sequence:", types_seen)

    assert types_seen[0] == "step" and events[0]["name"] == "Validate input"
    assert "plan" in types_seen, "expected a 'plan' event once planning finished"
    assert types_seen[-1] == "done", "stream must end with a 'done' event"

    step_events = [e for e in events if e["type"] == "step"]
    step_names = [e["name"] for e in step_events]
    print(f"{len(step_events)} step events:", step_names)

    # Regression test: every step must have a real, terminal status -- no
    # step is allowed to still say "pending" once its node has finished.
    bad = [e for e in step_events if e["status"] not in ("done", "revised", "recovered", "failed")]
    assert not bad, f"found step(s) with an unexpected status: {bad}"
    assert all(e["status"] != "pending" for e in step_events), "a step event was still 'pending' after execution!"

    done_event = events[-1]
    print("\nFinal 'done' event:")
    print(json.dumps(done_event, indent=2))

    assert done_event["status"] in ("success", "error")
    if done_event["status"] == "success":
        assert done_event["file_path"], "success but no file_path returned"

    print(f"\nPASSED: {label}")
    return done_event


if __name__ == "__main__":
    run_and_check(
        "Write a project proposal for Acme Retail Co. to build a new inventory "
        "management mobile app. Budget is around $35,000 and we want it done "
        "within 2 months.",
        "Standard request — streaming event/merge logic",
    )
    run_and_check(
        "hey can you put together something for the team about what we discussed "
        "on the call yesterday, whatever you think makes sense, not sure if it "
        "should be minutes or a plan, just make it look good and send it over asap",
        "Ambiguous request — streaming event/merge logic",
    )

    print("\n" + "=" * 90)
    print("TEST: empty input -> should yield a single 'error' event")
    print("=" * 90)
    agent._compiled_graph = FakeCompiledGraph()
    events = list(agent.Agent().stream_run("  "))
    print(events)
    assert len(events) == 1 and events[0]["type"] == "error"
    print("PASSED: empty input handled without touching the graph")

    print("\nAll streaming tests passed.")
