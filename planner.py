"""
Planning logic: turns a raw natural-language request into document_type,
title, section outline, entities, and explicit assumptions.

Deterministic by default (regex/keyword based, zero dependencies), with
an optional LLM assist for the title via llm.complete(). This is what
makes the agent "autonomous" rather than a template picker -- it decides
the document type and section structure itself, and explicitly records
assumptions when the request is incomplete instead of stalling.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from llm import complete

DOC_TYPE_KEYWORDS = {
    "meeting_minutes": ["minutes", "meeting notes", "recap of the meeting", "meeting summary", "discussed on the call"],
    "project_plan": ["project plan", "roadmap", "timeline", "milestones", "gantt"],
    "business_report": ["quarterly report", "business report", "performance report", "financial report", "annual report"],
    "technical_design": ["technical design", "design doc", "architecture", "system design", "tdd"],
    "sop": ["sop", "standard operating procedure", "process document", "procedure for"],
    "product_spec": ["product spec", "prd", "product requirements", "feature spec"],
    "proposal": ["proposal", "pitch", "quote", "offer for", "propose"],
}
DEFAULT_DOC_TYPE = "proposal"

SECTION_OUTLINES = {
    "proposal": ["Executive Summary", "Problem Statement", "Proposed Solution", "Scope of Work",
                 "Timeline", "Budget", "Why Us", "Next Steps"],
    "meeting_minutes": ["Meeting Overview", "Attendees", "Agenda", "Discussion Summary",
                         "Decisions Made", "Action Items", "Next Meeting"],
    "project_plan": ["Project Overview", "Objectives", "Scope", "Milestones & Timeline",
                      "Resource Plan", "Risks & Mitigations", "Success Criteria"],
    "business_report": ["Executive Summary", "Key Metrics", "Performance Analysis",
                         "Challenges", "Opportunities", "Recommendations", "Conclusion"],
    "technical_design": ["Overview", "Goals & Non-Goals", "System Architecture", "Detailed Design",
                          "API / Interface Design", "Trade-offs & Alternatives", "Rollout Plan"],
    "sop": ["Purpose", "Scope", "Roles & Responsibilities", "Procedure Steps",
            "Exceptions & Escalation", "Revision History"],
    "product_spec": ["Overview", "Problem & Motivation", "User Stories", "Functional Requirements",
                      "Non-Functional Requirements", "Out of Scope", "Open Questions"],
}

AMBIGUOUS_SIGNALS = ["asap", "something", "you decide", "up to you", "not sure", "figure it out",
                     "whatever you think", "tbd", "whatever makes sense"]

_LEADING_VERB_STOPWORDS = {
    "I", "The", "A", "An", "We", "Word", "Please", "For", "Write", "Build", "Create", "Draft",
    "Prepare", "Make", "Put", "Send", "Help", "Can", "Could", "Generate", "Produce", "Design",
    "Set", "Give", "Get", "Do", "Budget", "Timeline", "Scope", "Team", "It", "This", "That",
    "Also", "And", "But", "So", "Just",
}


@dataclass
class Plan:
    document_type: str
    title: str
    sections: list[str]
    assumptions: list[str] = field(default_factory=list)
    clarifications_needed: list[str] = field(default_factory=list)
    entities: dict = field(default_factory=dict)


def classify_document_type(text: str) -> str:
    lower = text.lower()
    scores = {}
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score:
            scores[doc_type] = score
    return max(scores, key=scores.get) if scores else DEFAULT_DOC_TYPE


def extract_entities(text: str) -> dict:
    candidates = re.findall(r"\b([A-Z][a-zA-Z0-9&]*(?:\s+[A-Z][a-zA-Z0-9&]*){0,2})\b", text)
    cleaned = [c for c in candidates if len(c) > 2]
    multi_word = [c for c in cleaned if " " in c]
    single_word = [c for c in cleaned if " " not in c and c not in _LEADING_VERB_STOPWORDS]
    proper_nouns = (multi_word + single_word)[:5]

    budget = None
    if "$" in text or "budget" in text.lower():
        match = re.search(r"\$\s?[\d,]+(?:\.\d+)?\s?(?:k|K|thousand|million|M)?", text)
        if match:
            budget = match.group(0).strip()

    return {"proper_nouns": proper_nouns, "budget_mention": budget}


def generate_assumptions(text: str, entities: dict) -> tuple[list[str], list[str]]:
    """Returns (assumptions, clarifications_needed)."""
    is_ambiguous = any(sig in text.lower() for sig in AMBIGUOUS_SIGNALS)
    has_specifics = bool(entities["proper_nouns"]) or bool(entities["budget_mention"])

    assumptions: list[str] = []
    clarifications: list[str] = []

    if not has_specifics:
        assumptions.append(
            "No company, client, or project name was given, so mock placeholder "
            "names and figures were used throughout the document."
        )
    if is_ambiguous or not has_specifics:
        assumptions.append(
            "The request did not fully specify scope, audience, or tone, so "
            "reasonable business-standard defaults were used for this document "
            "type instead of blocking on a clarifying question."
        )
        clarifications.append(
            "Confirm the real client/company name, budget, and timeline before "
            "sending this document externally."
        )
    return assumptions, clarifications


def _build_title(doc_type: str, entities: dict) -> str:
    subject = entities["proper_nouns"][0] if entities["proper_nouns"] else "New Initiative"

    llm_title = complete(
        "You write short, specific business document titles. Respond with ONLY the title, nothing else.",
        f"Document type: {doc_type}. Subject/entity: {subject}. Give a concise professional title.",
    )
    if llm_title and 3 < len(llm_title.strip()) < 120:
        return llm_title.strip().strip('"')

    templates = {
        "proposal": f"Business Proposal: {subject}",
        "meeting_minutes": f"Meeting Minutes — {subject}",
        "project_plan": f"Project Plan: {subject}",
        "business_report": f"Business Report: {subject}",
        "technical_design": f"Technical Design Document: {subject}",
        "sop": f"Standard Operating Procedure: {subject}",
        "product_spec": f"Product Specification: {subject}",
    }
    return templates.get(doc_type, f"Document: {subject}")


def create_plan(request_text: str) -> Plan:
    """Main entry point: classify -> extract -> assume -> outline -> title."""
    doc_type = classify_document_type(request_text)
    entities = extract_entities(request_text)
    assumptions, clarifications = generate_assumptions(request_text, entities)
    sections = SECTION_OUTLINES.get(doc_type, SECTION_OUTLINES[DEFAULT_DOC_TYPE])
    title = _build_title(doc_type, entities)

    return Plan(
        document_type=doc_type,
        title=title,
        sections=sections,
        assumptions=assumptions,
        clarifications_needed=clarifications,
        entities=entities,
    )
