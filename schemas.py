"""Pydantic schemas — the API transport layer only. The graph/agent core
(agent.py, planner.py, executor.py, reflector.py, renderer.py) returns
plain dicts and has no dependency on pydantic or FastAPI."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AgentRequest(BaseModel):
    request: str = Field(..., min_length=3, max_length=4000, description="Natural-language document request")

    @field_validator("request")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("request must not be blank")
        return v.strip()


class AgentResponse(BaseModel):
    status: str
    document_type: Optional[str] = None
    title: Optional[str] = None
    sections: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    clarifications_needed: List[str] = Field(default_factory=list)
    file_path: Optional[str] = None
    logs: List[str] = Field(default_factory=list)
    steps: List[Dict] = Field(default_factory=list)
    reflection_notes: List[str] = Field(default_factory=list)
    message: Optional[str] = None
