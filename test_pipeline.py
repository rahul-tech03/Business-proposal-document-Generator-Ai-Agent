"""
Runs plan -> execute -> reflect -> render by calling the exact same
functions agent.py's graph nodes call, with zero dependency on
langgraph/fastapi/pydantic. Useful as a fast sanity check on the core
business logic, independent of whether the graph/web/API layers are set
up correctly.

Usage: python test_pipeline.py
"""
import os

import executor
import planner
import reflector
import renderer

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")


def run_pipeline(request_text: str, label: str):
    print("\n" + "=" * 90)
    print(f"TEST CASE: {label}")
    print("=" * 90)
    print(f"REQUEST: {request_text!r}\n")

    plan = planner.create_plan(request_text)
    print(f"[DONE] Step completed: Plan document ({plan.document_type})")
    print(f"  title       = {plan.title}")
    print(f"  sections    = {plan.sections}")
    print(f"  entities    = {plan.entities}")
    print(f"  assumptions = {plan.assumptions}")

    content = {}
    for sec in plan.sections:
        content[sec] = executor.generate_section(request_text, plan.document_type, sec, plan.entities)
        print(f"[DONE] Step completed: Generate section '{sec}'")

    notes = []
    for sec, text in content.items():
        new_text, passed, section_notes = reflector.reflect_and_improve(
            request_text, plan.document_type, sec, text, plan.entities
        )
        content[sec] = new_text
        notes.extend(section_notes)
        print(f"[DONE] Step completed: Reflect on '{sec}' ({'passed' if passed else 'revised'})")

    file_path = renderer.render_document(
        title=plan.title, doc_type=plan.document_type, sections=content,
        assumptions=plan.assumptions, output_dir=OUTPUT_DIR,
    )
    print(f"[DONE] Step completed: Render Word document -> {file_path}")

    print("\nReflection notes:")
    for n in notes:
        print(f"   - {n}")

    return file_path


if __name__ == "__main__":
    run_pipeline(
        "Write a project proposal for Acme Retail Co. to build a new inventory "
        "management mobile app. Budget is around $35,000 and we want it done "
        "within 2 months.",
        "Standard, well-specified request",
    )
    run_pipeline(
        "hey can you put together something for the team about what we discussed "
        "on the call yesterday, whatever you think makes sense, not sure if it "
        "should be minutes or a plan, just make it look good and send it over asap",
        "Ambiguous / underspecified request",
    )
    print("\nDone. Files written to:", OUTPUT_DIR)
