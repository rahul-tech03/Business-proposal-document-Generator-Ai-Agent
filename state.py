"""
Shared state for the LangGraph pipeline.

Fields annotated with `Annotated[list, operator.add]` use LangGraph's
reducer mechanism: when a node returns a partial update for that key, its
value is APPENDED to the existing list rather than overwriting it. That's
what gives us real, cumulative execution logs and step statuses across
the plan -> execute -> reflect -> render graph, instead of each node
clobbering what the previous node wrote -- and it's also what the
streaming endpoint (see agent.py) replays to the browser in real time.
"""
from __future__ import annotations

import operator
from typing import Annotated, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # input
    request: str

    # produced by the "plan" node
    document_type: str
    title: str
    sections: List[str]
    entities: dict
    assumptions: List[str]
    clarifications_needed: List[str]

    # produced by the "execute" node, refined by "reflect"
    section_content: Dict[str, str]
    reflection_notes: Annotated[List[str], operator.add]

    # produced by the "render" node
    file_path: Optional[str]
    status: str
    error: Optional[str]

    # cumulative across every node
    logs: Annotated[List[str], operator.add]
    steps: Annotated[List[dict], operator.add]
