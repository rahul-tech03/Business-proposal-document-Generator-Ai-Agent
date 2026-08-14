"""
FastAPI entry point.

    GET  /                           -> web UI (static/index.html)
    POST /agent                      -> run the agent, get back one JSON response
                                         once the whole pipeline has finished
    POST /agent/stream                -> same agent, but streamed as newline-
                                         delimited JSON (NDJSON) events, one per
                                         real pipeline step as it completes --
                                         this is what the web UI's live task
                                         list consumes
    GET  /agent/download/{file}       -> download the generated .docx
    GET  /health                      -> liveness probe
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent import OUTPUT_DIR, Agent
from logger_config import logger
from schemas import AgentRequest, AgentResponse

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Autonomous Document Agent (LangChain + LangGraph)",
    description="Plans, executes, self-checks, and renders a Word document from a natural-language request.",
    version="2.1.0",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

agent = Agent()


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/agent", response_model=AgentResponse)
def run_agent(payload: AgentRequest):
    logger.info("[INFO] Received request: %.100s", payload.request)
    try:
        result = agent.run(payload.request)
    except Exception:
        logger.info("[FAILED] Unhandled agent error")
        raise HTTPException(status_code=500, detail="Internal agent error. Please try again.")

    if result["status"] == "error" and not result.get("file_path"):
        raise HTTPException(status_code=422, detail=result.get("message", "Agent could not process the request."))

    return result


@app.post("/agent/stream")
def run_agent_stream(payload: AgentRequest):
    """Streams NDJSON (one JSON object per line) as the graph actually
    executes. Consumed by static/index.html via fetch() + ReadableStream --
    plain HTTP, no extra client library needed."""
    logger.info("[INFO] Received streaming request: %.100s", payload.request)

    def event_source():
        try:
            for event in agent.stream_run(payload.request):
                yield json.dumps(event) + "\n"
        except Exception as exc:
            logger.info("[FAILED] Unhandled streaming error: %s", type(exc).__name__)
            yield json.dumps({"type": "error", "message": "Internal agent error. Please try again."}) + "\n"

    return StreamingResponse(event_source(), media_type="application/x-ndjson")


@app.get("/agent/download/{file_name}")
def download_document(file_name: str):
    safe_name = os.path.basename(file_name)  # guard against path traversal
    file_path = os.path.join(OUTPUT_DIR, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=safe_name,
    )
