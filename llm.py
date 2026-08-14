"""
LLM layer built on LangChain (`langchain_groq.ChatGroq`, Groq's free tier,
OpenAI-compatible under the hood). This is the ONLY module that imports a
LangChain chat model class -- planner/executor/reflector call `complete()`
/ `complete_json()` and never touch LangChain message types directly.

Contract: both functions return `None` on any failure (missing key,
network error, malformed JSON) instead of raising. Every caller treats
`None` as "use the deterministic engine for this piece" -- so the whole
pipeline runs identically, just with template-based content, when no
GROQ_API_KEY is set.
"""
from __future__ import annotations

import json
import os
import re

from logger_config import logger

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

ENABLED = False
_llm = None

if GROQ_API_KEY:
    try:
        from langchain_groq import ChatGroq

        _llm = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY, temperature=0.3, max_tokens=1200)
        ENABLED = True
        logger.info("[INFO] LLM mode: LangChain + Groq enabled (%s)", GROQ_MODEL)
    except Exception:
        logger.info("[INFO] LangChain/Groq SDK unavailable — running in deterministic offline mode")
else:
    logger.info("[INFO] No GROQ_API_KEY set — running in deterministic offline mode")


def complete(system: str, user: str) -> str | None:
    """Free-form text completion. Returns None on failure or if disabled."""
    if not ENABLED:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = _llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return response.content
    except Exception as exc:
        logger.info("[WARN] LLM call failed (%s) — using deterministic fallback", type(exc).__name__)
        return None


def _extract_json(text: str):
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if brace:
            text = brace.group(1)
    return json.loads(text)


def complete_json(system: str, user: str):
    """Structured completion. Returns a parsed dict/list, or None on any failure."""
    raw = complete(system + "\n\nRespond with ONLY valid JSON. No prose, no markdown fences.", user)
    if raw is None:
        return None
    try:
        return _extract_json(raw)
    except Exception:
        logger.info("[WARN] LLM returned invalid JSON — using deterministic fallback")
        return None
