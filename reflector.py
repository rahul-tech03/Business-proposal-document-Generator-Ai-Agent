"""
Reflection stage: critiques each generated section and repairs it once if
it fails a quality check. This is the agent's self-check step -- it does
not blindly trust the first draft.

Rubric (used both as the LLM review prompt and as the always-available
deterministic fallback check): specific rather than generic filler,
on-topic, no leftover placeholders, not too short.

Repair is bounded to a single attempt per section so latency/cost stay
predictable -- the agent doesn't loop forever chasing a perfect draft.
"""
from __future__ import annotations

from llm import complete, complete_json

REFLECTION_SYSTEM_PROMPT = (
    "You are a quality reviewer for a business document section. Given the section "
    "name and its drafted content, decide if it meets a professional bar: specific "
    "(not generic filler), on-topic, appropriately detailed, no leftover placeholders "
    "like '[TBD]' or 'Lorem ipsum', and not truncated. "
    'Respond with a JSON object: {"pass": true|false, "issues": ["...", ...]}'
)

REPAIR_SYSTEM_PROMPT = (
    "You are the content-generation module of an autonomous document-writing agent. "
    "Rewrite ONE section, fixing the specific issues listed. Respond with plain text only."
)

PLACEHOLDER_MARKERS = ("[tbd]", "lorem ipsum", "xxxx", "todo:", "insert here", "<placeholder>")
MIN_SECTION_CHARS = 40


def _offline_quality_check(section: str, content: str) -> dict:
    issues = []
    lower = content.lower()
    if len(content.strip()) < MIN_SECTION_CHARS:
        issues.append("Content is too short to be useful.")
    if any(marker in lower for marker in PLACEHOLDER_MARKERS):
        issues.append("Contains an unresolved placeholder marker.")
    if content.strip().lower() == section.strip().lower():
        issues.append("Content just repeats the section title.")
    return {"pass": len(issues) == 0, "issues": issues}


def review_section(section: str, content: str) -> dict:
    result = complete_json(REFLECTION_SYSTEM_PROMPT, f"Section: {section}\nContent:\n{content}")
    if not isinstance(result, dict) or "pass" not in result:
        result = _offline_quality_check(section, content)
    return result


def reflect_and_improve(request_text: str, doc_type: str, section: str,
                         content: str, entities: dict) -> tuple[str, bool, list[str]]:
    """Returns (final_content, passed, notes)."""
    from executor import generate_section  # local import: avoids a module-load cycle with executor

    notes: list[str] = []
    review = review_section(section, content)

    if review.get("pass", True):
        notes.append(f"'{section}': passed self-check on first draft.")
        return content, True, notes

    issues = review.get("issues", ["Unspecified quality issue."])
    notes.append(f"'{section}': failed self-check ({'; '.join(issues)}) — regenerating once.")

    repair_prompt = (
        f"Document type: {doc_type}\nSection: {section}\nOriginal request: {request_text}\n"
        f"Known entities: {entities}\nPrevious draft had these issues: {issues}\n"
        f"Previous draft:\n{content}\n\nRewrite the '{section}' section fixing those issues."
    )
    llm_repair = complete(REPAIR_SYSTEM_PROMPT, repair_prompt)
    new_content = llm_repair.strip() if llm_repair and len(llm_repair.strip()) > 20 else \
        generate_section(request_text, doc_type, section, entities)

    recheck = _offline_quality_check(section, new_content)
    if recheck["pass"]:
        notes.append(f"'{section}': regenerated content passed self-check.")
    else:
        notes.append(f"'{section}': regenerated content still had issues {recheck['issues']}; kept best available draft.")

    return new_content, recheck["pass"], notes
