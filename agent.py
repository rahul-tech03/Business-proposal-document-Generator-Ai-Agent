"""
The LangGraph agent: Plan -> Execute -> Reflect -> Render, as an explicit
StateGraph. Each node does REAL work and returns its REAL outcome -- there
is no pre-populated "PENDING" list that gets optimistically marked done
elsewhere. A step only appears in `state["steps"]` at the moment it has
actually finished (or actually failed), with the status that action
produced.

Two entry points are exposed:

  Agent.run(request_text)          -> single dict, once the whole graph
                                       has finished (used by POST /agent)
  Agent.stream_run(request_text)   -> generator of small event dicts,
                                       emitted as each graph node actually
                                       completes (used by POST /agent/stream,
                                       which powers the web UI's live task list)

Both call the SAME compiled graph -- `stream_run` just consumes
`graph.stream(..., stream_mode="updates")` instead of `graph.invoke(...)`.
LangGraph's "updates" stream mode yields one `{node_name: partial_state}`
dict per node as it finishes, which is real, node-level execution
progress -- not a simulated/fake timer on the frontend.

Streaming granularity note (an explicit simplicity-vs-extensibility
tradeoff): because each node (e.g. `execute_node`) generates every
section internally in a plain Python loop before returning, events arrive
at the granularity of "a whole stage finished" (4 events: plan / execute /
reflect / render), not "one individual section finished". Getting
true per-section streaming would mean fanning each section out into its
own graph node (LangGraph's `Send` API), which adds real complexity for
a proportionally smaller UX gain here. Stage-level streaming was chosen
deliberately to keep the graph simple and easy to reason about.
"""
from __future__ import annotations

import os
from typing import Iterator

from langgraph.graph import END, START, StateGraph

import executor
import planner
import reflector
import renderer
from logger_config import logger
from state import AgentState

OUTPUT_DIR = os.getenv("AGENT_OUTPUT_DIR", "outputs")


# --------------------------------------------------------------------------- #
# Node 1: Plan
# --------------------------------------------------------------------------- #
def plan_node(state: AgentState) -> dict:
    try:
        plan = planner.create_plan(state["request"])
        logger.info("[DONE] Step completed: Plan document (%s)", plan.document_type)
        return {
            "document_type": plan.document_type,
            "title": plan.title,
            "sections": plan.sections,
            "assumptions": plan.assumptions,
            "clarifications_needed": plan.clarifications_needed,
            "entities": plan.entities,
            "logs": [f"[DONE] Step completed: Plan document ({plan.document_type})"],
            "steps": [{"name": "Plan document", "status": "done", "detail": plan.document_type}],
        }
    except Exception as exc:
        logger.info("[RECOVERED] Planning failed (%s); using fallback template", type(exc).__name__)
        fallback_type = planner.DEFAULT_DOC_TYPE
        return {
            "document_type": fallback_type,
            "title": "Business Document",
            "sections": planner.SECTION_OUTLINES[fallback_type],
            "assumptions": ["Planning encountered an error, so a default proposal template was used."],
            "clarifications_needed": [],
            "entities": {"proper_nouns": [], "budget_mention": None},
            "logs": [f"[RECOVERED] Planning failed ({type(exc).__name__}); used fallback template."],
            "steps": [{"name": "Plan document", "status": "recovered", "detail": type(exc).__name__}],
        }


# --------------------------------------------------------------------------- #
# Node 2: Execute
# --------------------------------------------------------------------------- #
def execute_node(state: AgentState) -> dict:
    logs, steps, content = [], [], {}
    for sec in state["sections"]:
        try:
            content[sec] = executor.generate_section(state["request"], state["document_type"], sec, state["entities"])
            logs.append(f"[DONE] Step completed: Generate section '{sec}'")
            steps.append({"name": f"Generate section: {sec}", "status": "done"})
        except Exception as exc:
            content[sec] = f"Content for '{sec}' will be finalized in a follow-up review."
            logs.append(f"[RECOVERED] Section '{sec}' generation failed ({type(exc).__name__}); used fallback text.")
            steps.append({"name": f"Generate section: {sec}", "status": "recovered"})
    return {"section_content": content, "logs": logs, "steps": steps}


# --------------------------------------------------------------------------- #
# Node 3: Reflect (self-check)
# --------------------------------------------------------------------------- #
def reflect_node(state: AgentState) -> dict:
    logs, steps, notes = [], [], []
    updated = dict(state["section_content"])

    for sec, text in state["section_content"].items():
        try:
            new_text, passed, section_notes = reflector.reflect_and_improve(
                state["request"], state["document_type"], sec, text, state["entities"]
            )
            updated[sec] = new_text
            notes.extend(section_notes)
            status = "done" if passed else "revised"
            logs.append(f"[DONE] Step completed: Reflect on '{sec}' ({'passed' if passed else 'revised'})")
            steps.append({"name": f"Reflect: {sec}", "status": status})
        except Exception as exc:
            logs.append(f"[RECOVERED] Reflection failed for '{sec}' ({type(exc).__name__}); kept original draft.")
            steps.append({"name": f"Reflect: {sec}", "status": "recovered"})

    return {"section_content": updated, "reflection_notes": notes, "logs": logs, "steps": steps}


# --------------------------------------------------------------------------- #
# Node 4: Render
# --------------------------------------------------------------------------- #
def render_node(state: AgentState) -> dict:
    try:
        file_path = renderer.render_document(
            title=state["title"],
            doc_type=state["document_type"],
            sections=state["section_content"],
            assumptions=state["assumptions"],
            output_dir=OUTPUT_DIR,
        )
        logger.info("[DONE] Step completed: Render Word document")
        return {
            "file_path": file_path,
            "status": "success",
            "logs": ["[DONE] Step completed: Render Word document"],
            "steps": [{"name": "Render Word document", "status": "done"}],
        }
    except Exception as exc:
        logger.info("[FAILED] Render Word document: %s", type(exc).__name__)
        return {
            "file_path": None,
            "status": "error",
            "error": f"Rendering failed: {exc}",
            "logs": [f"[FAILED] Render Word document: {type(exc).__name__}"],
            "steps": [{"name": "Render Word document", "status": "failed"}],
        }


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("render", render_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "reflect")
    graph.add_edge("reflect", "render")
    graph.add_edge("render", END)

    return graph.compile()


_compiled_graph = build_graph()


def _validate(request_text: str) -> tuple[bool, str]:
    cleaned = (request_text or "").strip()
    if len(cleaned) < 3 or sum(c.isalpha() for c in cleaned) < 3:
        return False, "Request must be a non-empty description of the document you want generated."
    return True, cleaned


def _merge(accumulated: dict, key: str, value) -> None:
    """Mirrors the graph's own reducers so a Python-side accumulator built
    while consuming the stream matches what `graph.invoke()` would have
    returned: list fields (logs/steps/reflection_notes) append, everything
    else is last-write-wins."""
    if key in ("logs", "steps", "reflection_notes"):
        accumulated[key] = accumulated.get(key, []) + value
    else:
        accumulated[key] = value


class Agent:
    """Thin orchestrator facade over the compiled LangGraph graph."""

    # ---- non-streaming: used by POST /agent ----
    def run(self, request_text: str) -> dict:
        ok, cleaned_or_msg = _validate(request_text)
        if not ok:
            logger.info("[FAILED] Input validation: %s", cleaned_or_msg)
            return {
                "status": "error", "document_type": None, "title": None, "sections": [],
                "assumptions": [], "clarifications_needed": [], "file_path": None,
                "logs": [f"[FAILED] Input validation: {cleaned_or_msg}"],
                "steps": [{"name": "Validate input", "status": "failed"}],
                "reflection_notes": [], "message": cleaned_or_msg,
            }

        logger.info("[DONE] Step completed: Validate input")
        initial_state: AgentState = {"request": cleaned_or_msg, "logs": [], "steps": [], "reflection_notes": []}
        final_state = _compiled_graph.invoke(initial_state)

        status = final_state.get("status", "success")
        return {
            "status": status,
            "document_type": final_state.get("document_type"),
            "title": final_state.get("title"),
            "sections": final_state.get("sections", []),
            "assumptions": final_state.get("assumptions", []),
            "clarifications_needed": final_state.get("clarifications_needed", []),
            "file_path": final_state.get("file_path"),
            "logs": ["[DONE] Step completed: Validate input"] + final_state.get("logs", []),
            "steps": [{"name": "Validate input", "status": "done"}] + final_state.get("steps", []),
            "reflection_notes": final_state.get("reflection_notes", []),
            "message": "Document generated successfully." if status == "success" else final_state.get("error", "Unknown error"),
        }

    # ---- streaming: used by POST /agent/stream (the web UI) ----
    def stream_run(self, request_text: str) -> Iterator[dict]:
        """Yields small JSON-serializable event dicts as the graph actually
        executes:
            {"type": "step", "name": ..., "status": ...}       one per real step
            {"type": "plan", "document_type": ..., "sections": [...], ...}
            {"type": "done", ...final shaped response...}
            {"type": "error", "message": ...}                  on validation failure
        """
        ok, cleaned_or_msg = _validate(request_text)
        if not ok:
            logger.info("[FAILED] Input validation: %s", cleaned_or_msg)
            yield {"type": "error", "message": cleaned_or_msg}
            return

        logger.info("[DONE] Step completed: Validate input")
        validate_step = {"name": "Validate input", "status": "done"}
        yield {"type": "step", **validate_step}

        initial_state: AgentState = {
            "request": cleaned_or_msg, "logs": [], "steps": [validate_step], "reflection_notes": [],
        }
        accumulated: dict = dict(initial_state)

        for update in _compiled_graph.stream(initial_state, stream_mode="updates"):
            node_name, partial = next(iter(update.items()))
            for key, value in partial.items():
                _merge(accumulated, key, value)

            if node_name == "plan":
                yield {
                    "type": "plan",
                    "document_type": partial.get("document_type"),
                    "title": partial.get("title"),
                    "sections": partial.get("sections", []),
                    "assumptions": partial.get("assumptions", []),
                    "clarifications_needed": partial.get("clarifications_needed", []),
                }

            for step in partial.get("steps", []):
                yield {"type": "step", **step}

        status = accumulated.get("status", "success")
        yield {
            "type": "done",
            "status": status,
            "document_type": accumulated.get("document_type"),
            "title": accumulated.get("title"),
            "sections": accumulated.get("sections", []),
            "assumptions": accumulated.get("assumptions", []),
            "clarifications_needed": accumulated.get("clarifications_needed", []),
            "file_path": accumulated.get("file_path"),
            "reflection_notes": accumulated.get("reflection_notes", []),
            "message": "Document generated successfully." if status == "success" else accumulated.get("error", "Unknown error"),
        }
