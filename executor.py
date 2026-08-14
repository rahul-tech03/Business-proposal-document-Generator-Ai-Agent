"""
Execution stage: generates the actual content for each section in the plan.

Tries the LLM first (if configured); always has a deterministic fallback
so a request can never fail outright just because a section's content
generation had a problem.
"""
from __future__ import annotations

from datetime import date, timedelta

from llm import complete

SECTION_SYSTEM_PROMPT = (
    "You are the content-generation module of an autonomous document-writing "
    "agent. Write the content for ONE section of a business document. Be "
    "concrete and professional. If specific facts were not given, use "
    "plausible placeholder values rather than vague hand-waving. Keep it to "
    "2-5 sentences or a short list. Respond with plain text only."
)

_TODAY = date.today()
_DEADLINE = _TODAY + timedelta(days=45)


def _content_library(subject: str) -> dict:
    return {
        "Executive Summary": (
            f"This document summarizes the current situation, proposed approach, and expected "
            f"outcomes for {subject}. Where specific figures were not provided, representative "
            "estimates are used and flagged for confirmation."
        ),
        "Problem Statement": (
            f"{subject} is facing a gap between current operating capacity and near-term goals. "
            "Fragmented processes are creating delays and rising coordination overhead as the team scales."
        ),
        "Proposed Solution": (
            "A phased engagement is proposed, covering discovery, implementation, and handover, "
            "favoring incremental delivery so value is realized early."
        ),
        "Scope of Work": (
            "Scope includes requirements gathering, solution design, implementation, testing, "
            "documentation, and knowledge transfer. Ongoing maintenance is out of scope unless otherwise agreed."
        ),
        "Timeline": (
            f"Target kickoff is {_TODAY.strftime('%B %d, %Y')}, with an estimated completion date of "
            f"{_DEADLINE.strftime('%B %d, %Y')}, subject to scope confirmation."
        ),
        "Budget": (
            "A detailed line-item budget will be finalized after scope sign-off. A placeholder "
            "estimate of $25,000–$40,000 is provided for planning purposes."
        ),
        "Why Us": (
            "The team combines hands-on delivery experience with a track record of shipping "
            "similar engagements on time and within budget."
        ),
        "Next Steps": (
            "1) Review this proposal internally. 2) Schedule a kickoff call to confirm scope. "
            "3) Sign off to begin the discovery phase."
        ),
        "Meeting Overview": (
            f"This meeting covered progress and next steps related to {subject}. Notes below "
            "summarize discussion points, decisions, and owners."
        ),
        "Attendees": "Project Sponsor, Project Lead, Engineering Lead, Design Lead, Client Stakeholder.",
        "Agenda": "1) Status update. 2) Open risks. 3) Decisions needed. 4) Action items and owners.",
        "Discussion Summary": (
            "The team reviewed progress against the plan, flagged two open risks around timeline "
            "and resourcing, and discussed mitigation options."
        ),
        "Decisions Made": (
            "The team agreed to proceed with the proposed approach and revisit the timeline at "
            "the next checkpoint if blockers remain."
        ),
        "Action Items": (
            f"Owner: Project Lead — finalize scope by {_DEADLINE.strftime('%B %d, %Y')}. "
            "Owner: Engineering Lead — confirm resource availability by next week."
        ),
        "Next Meeting": "To be scheduled one week from this meeting, pending calendar availability.",
        "Project Overview": f"This plan defines how {subject} will be delivered, including scope, milestones, and risk management.",
        "Objectives": "Deliver the agreed scope on time and on budget while maintaining quality and stakeholder alignment.",
        "Scope": "In-scope: core deliverables agreed with the sponsor. Out-of-scope: items deferred to a later phase.",
        "Milestones & Timeline": (
            f"Kickoff: {_TODAY.strftime('%B %d, %Y')}. Design sign-off: +2 weeks. Build complete: +6 weeks. "
            f"Launch: {_DEADLINE.strftime('%B %d, %Y')}."
        ),
        "Resource Plan": "A cross-functional team of 3–5 people is estimated, spanning delivery, engineering, and design.",
        "Risks & Mitigations": "Key risk: scope creep. Mitigation: a formal change-request process for out-of-scope items.",
        "Success Criteria": "Success is on-time delivery of the agreed scope, accepted by the sponsor, within budget.",
        "Key Metrics": "Illustrative metrics: Revenue, Active Users, Retention Rate, Operating Costs (placeholders pending real data).",
        "Performance Analysis": "Overall performance trended positively this period, with growth offset by rising operating costs.",
        "Challenges": "Primary challenges include resourcing constraints and slower-than-expected adoption in one segment.",
        "Opportunities": "Room to improve margins through automation and grow adoption via better onboarding.",
        "Recommendations": "Recommend investing in workflow automation and piloting an onboarding improvement next quarter.",
        "Conclusion": "Overall trajectory is positive; the recommendations above are intended to compound that momentum.",
        "Goals & Non-Goals": "Goal: solve the stated problem reliably at the required scale. Non-goal: unrelated system rebuilds.",
        "System Architecture": "A modular architecture separates the API layer, orchestration layer, and persistence layer.",
        "Detailed Design": "Each component exposes a narrow interface; cross-component communication uses defined contracts.",
        "API / Interface Design": "A REST API is proposed as the primary interface, using JSON and standard HTTP status codes.",
        "Trade-offs & Alternatives": "A monolithic design was considered but rejected in favor of modularity for independent scaling.",
        "Rollout Plan": "Staged rollout: internal testing, limited beta, then general availability, with monitoring at each stage.",
        "Purpose": f"This SOP defines the standard procedure related to {subject}, ensuring consistency and repeatability.",
        "Roles & Responsibilities": "Process Owner: accountable for the procedure. Operator: executes steps. Reviewer: audits compliance.",
        "Procedure Steps": "1) Confirm prerequisites. 2) Execute core steps in order. 3) Record the outcome. 4) Escalate exceptions.",
        "Exceptions & Escalation": "Any deviation must be logged and escalated to the Process Owner within 24 hours.",
        "Revision History": f"v1.0 — {_TODAY.strftime('%B %d, %Y')} — Initial version.",
        "Problem & Motivation": f"Users of {subject} currently lack a reliable way to complete this workflow.",
        "User Stories": "As a user, I want to complete this workflow in one session, so I don't lose progress.",
        "Functional Requirements": "The system must support the core workflow end-to-end and surface clear error messages.",
        "Non-Functional Requirements": "The system should respond within acceptable latency and degrade gracefully under failure.",
        "Out of Scope": "Support for edge-case workflows outside the primary use case is deferred to a future iteration.",
        "Open Questions": "Final ownership of long-term maintenance and the exact rollout date remain to be confirmed.",
    }


def generate_section(request_text: str, doc_type: str, section: str, entities: dict) -> str:
    """Generate content for one section: LLM first, deterministic fallback always available."""
    llm_text = complete(
        SECTION_SYSTEM_PROMPT,
        f"Document type: {doc_type}\nSection: {section}\nOriginal request: {request_text}\n"
        f"Known entities: {entities}\n\nWrite the content for the '{section}' section.",
    )
    if llm_text and len(llm_text.strip()) > 20:
        return llm_text.strip()

    subject = entities.get("proper_nouns", ["the client"])
    subject = subject[0] if subject else "the client"
    library = _content_library(subject)
    return library.get(section, f"Details for '{section}' will be finalized in a follow-up review with {subject}.")
