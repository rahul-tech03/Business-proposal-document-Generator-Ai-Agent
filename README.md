# Autonomous Document Agent — LangChain + LangGraph + Web UI

A FastAPI service that takes a natural-language request and runs it
through an explicit **LangGraph** pipeline — Plan → Execute → Reflect →
Render — to produce a polished Word (`.docx`) document, with **LangChain**
(`langchain-groq`, free tier) as the optional LLM layer, and a built-in
**web UI** that shows the task list completing live and lets you download
the result — no curl/Swagger needed.

Runs with **zero API keys**: every stage has a deterministic fallback, so
the full pipeline works offline out of the box.

---
![Uploading web_ui_preview.png…]()


## 1. Web UI

Open `http://localhost:8000/` after starting the server:

- Type a request in plain English (or click one of the two example
  buttons) and hit **Generate document**.
- The **Pipeline** panel and **Sections** checklist update live — driven
  by real server-sent events, not a client-side timer — as each stage of
  the LangGraph pipeline actually finishes.
- The **Live log** panel mirrors the same `[DONE]` / `[RECOVERED]` /
  `[FAILED]` lines the server logs to its own console.
- When it finishes, a result card shows the title, any assumptions the
  agent made, anything flagged for you to double-check, and a
  **Download .docx** button.

This is served by `GET /` (static/index.html) and powered by
`POST /agent/stream`, a newline-delimited-JSON (NDJSON) streaming
endpoint — see §3.

---

## 2. Architecture

```
        ┌────────────┐      ┌────────────┐      ┌────────────┐      ┌────────────┐
 START →│    plan     │─────▶│   execute   │─────▶│   reflect   │─────▶│   render    │──▶ END
        │ planner.py  │      │ executor.py │      │reflector.py │      │ renderer.py │
        └────────────┘      └────────────┘      └────────────┘      └────────────┘
              │                    │                    │                    │
              ▼                    ▼                    ▼                    ▼
      classify doc type      generate content     self-check each      python-docx →
      extract entities       for every section     section, repair       .docx file
      generate assumptions                          once if it fails
      build section outline                         the rubric
```

```
              ┌──────────────────────────┐
   Browser ──▶ │  GET /            (UI)    │
              │  POST /agent       (JSON)   │──▶ agent.py: Agent.run()      ──▶ graph.invoke()
              │  POST /agent/stream (NDJSON)│──▶ agent.py: Agent.stream_run()──▶ graph.stream()
              │  GET /agent/download/{file}  │
              └──────────────────────────┘
                             │
              StateGraph: plan → execute → reflect → render   (agent.py, state.py)
                    │            │            │              │
               planner.py   executor.py  reflector.py   renderer.py
                    │            │            │
                    └────────────┴────────────┘
                                 │
                              llm.py   (LangChain ChatGroq — optional, returns None on any failure)
```

| File | Responsibility | Depends on |
|---|---|---|
| `main.py` | FastAPI routes: web UI, JSON endpoint, streaming endpoint, download, health | FastAPI, pydantic |
| `static/index.html` | Web UI: form, live pipeline/section status, log feed, result + download | vanilla JS, no build step |
| `schemas.py` | Request/response pydantic models | pydantic |
| `agent.py` | LangGraph graph definition + `Agent.run()` / `Agent.stream_run()` | langgraph |
| `state.py` | Shared `AgentState` TypedDict with reducers | stdlib only |
| `planner.py` | Classify doc type, extract entities, generate assumptions, pick section outline | `llm.py` |
| `executor.py` | Generate content per section | `llm.py` |
| `reflector.py` | Self-check + repair each section | `llm.py`, `executor.py` |
| `renderer.py` | Render the final `.docx` | `python-docx` |
| `llm.py` | LangChain `ChatGroq` wrapper; the only file that imports a LangChain chat model | `langchain-groq` (optional) |
| `logger_config.py` | Clean, quiet logging setup | stdlib only |

`planner.py`, `executor.py`, `reflector.py`, and `renderer.py` have **no
dependency on FastAPI, pydantic, or LangGraph** — `test_pipeline.py` proves
this by running the exact same plan → execute → reflect → render sequence
with nothing installed but `python-docx`.

---

## 3. How the live task list actually works (not a fake progress bar)

`POST /agent/stream` streams NDJSON — one JSON object per line — using
LangGraph's own `graph.stream(state, stream_mode="updates")`, which yields
`{node_name: partial_state}` once per node **as that node actually
finishes**. `Agent.stream_run()` (in `agent.py`) turns each of those into
small events:

```
{"type": "step", "name": "Plan document", "status": "done", "detail": "proposal"}
{"type": "plan", "document_type": "proposal", "sections": [...], "assumptions": [...]}
{"type": "step", "name": "Generate section: Executive Summary", "status": "done"}
...
{"type": "done", "status": "success", "file_path": "outputs/....docx", ...}
```

The browser reads the response body as a stream (`fetch()` +
`ReadableStream`, see `static/index.html`) and updates the Pipeline /
Sections / Live log panels as each line arrives — so what you see on
screen is a direct reflection of server-side execution, not a client-side
animation guessing at progress.

**Granularity note (an explicit tradeoff, not an oversight):** events
arrive at the *stage* level (plan / execute / reflect / render — 4 events),
not per individual section, because `execute_node` and `reflect_node` each
loop over every section internally before returning to the graph runtime.
True per-section live streaming would need LangGraph's `Send` API to fan
each section out into its own graph node — more powerful, meaningfully
more complex. Stage-level streaming was chosen to keep the graph simple
and easy to reason about; see `agent.py`'s module docstring for the full
reasoning. `test_stream.py` covers this event/merge logic directly.

`POST /agent` (used by API clients that don't need live updates) uses the
same graph via `graph.invoke()` and returns one JSON object once the whole
pipeline has finished.

---

## 4. What was fixed from the previous version

| Problem | Fix |
|---|---|
| Steps shown as `PENDING` even after execution | Steps are appended to `state["steps"]` **only when their node actually finishes**, carrying the real outcome of that run. There is no separate task list drawn up in advance and patched afterward. |
| Noisy Groq/SDK error logs | `logger_config.py` pins `httpx`/`httpcore`/`groq`/`langchain*` loggers to `CRITICAL`. `llm.py` catches every exception at the source and emits one line: `[WARN] LLM call failed (<ExceptionType>) — using deterministic fallback`. No stack traces reach the console. |
| Missing API layer | `main.py` — `POST /agent`, `POST /agent/stream`, `GET /agent/download/{file}`, `GET /health`, plus `GET /` for the web UI. |
| Weak architecture | Split exactly into `planner.py` / `executor.py` / `reflector.py` / `renderer.py` / `agent.py` (orchestrator) / `main.py` (API), each with one job. |
| No real execution flow | The LangGraph edges (`plan → execute → reflect → render`) enforce the sequence; each node's output is real, not simulated — and now streamed live to the browser. |
| Missing error handling | Input validation in `Agent.run()`/`stream_run()`; every graph node has its own try/except with a safe fallback; the API layer catches anything unhandled and returns a clean `500`/`422` instead of a stack trace. |
| Not truly autonomous | `planner.py` classifies the document type from the request itself, decides the section outline, and generates explicit `assumptions` when data is missing — surfaced live in the UI, not just buried in the final JSON. |
| No way to use it without curl/Swagger | The web UI (`static/index.html`) — type a request, watch it execute, download the result. |

---

## 5. Mandatory improvement: Reflection / self-check

After `execute` generates a section, `reflect` reviews it against a
rubric — specific vs. generic filler, on-topic, no leftover placeholders
(`[TBD]`, `Lorem ipsum`), not too short — and regenerates that **one**
section (feeding the specific issues back into the prompt) if it fails.
Bounded to a single repair attempt per section. Every decision is recorded
in `reflection_notes` and, in the UI, shows up as each section's status
in the **Sections** panel ("reviewed — passed self-check" vs "reviewed —
revised"). The rubric has a fully deterministic fallback
(`_offline_quality_check` in `reflector.py`), so reflection works
identically with or without a live LLM.

---

## 6. Running it

```bash
pip install -r requirements.txt

# Optional — omit to run entirely offline/free:
export GROQ_API_KEY=your_free_groq_key   # https://console.groq.com

uvicorn main:app --reload
```

Then open **`http://localhost:8000/`** for the web UI, or
**`http://localhost:8000/docs`** for the API directly.

**Dependency-light sanity checks** (no langgraph/fastapi/pydantic needed):
```bash
python test_pipeline.py   # planner/executor/reflector/renderer, end to end
python test_stream.py     # streaming event/merge logic + PENDING-status regression test
```

---

## 7. Example: streaming endpoint (what the web UI calls)

```bash
curl -N -X POST http://localhost:8000/agent/stream \
  -H "Content-Type: application/json" \
  -d '{"request": "Write a project proposal for Acme Retail Co. to build a new inventory management mobile app. Budget is around $35,000 and we want it done within 2 months."}'
```

```
{"type": "step", "name": "Validate input", "status": "done"}
{"type": "plan", "document_type": "proposal", "title": "Business Proposal: Acme Retail Co", "sections": ["Executive Summary", ...], "assumptions": [], "clarifications_needed": []}
{"type": "step", "name": "Plan document", "status": "done", "detail": "proposal"}
{"type": "step", "name": "Generate section: Executive Summary", "status": "done"}
...
{"type": "step", "name": "Reflect: Executive Summary", "status": "done"}
...
{"type": "step", "name": "Render Word document", "status": "done"}
{"type": "done", "status": "success", "title": "Business Proposal: Acme Retail Co", "file_path": "outputs/business_proposal_acme_retail_co.docx", "assumptions": [], "clarifications_needed": [], "reflection_notes": [...], "message": "Document generated successfully."}
```

Download it:
```bash
curl -O http://localhost:8000/agent/download/business_proposal_acme_retail_co.docx
```

### Non-streaming JSON endpoint (for API clients)
```bash
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"request": "Write meeting minutes for yesterday'\''s product sync"}'
```
Returns the same shape as the final `"done"` event above, in one response.

---

## 8. Project layout

```
autonomous_agent_langgraph/
├── main.py             # FastAPI app: web UI route, JSON + streaming endpoints, download, health
├── schemas.py           # pydantic request/response models
├── agent.py             # LangGraph StateGraph + Agent.run() / Agent.stream_run()
├── state.py              # AgentState TypedDict (shared graph state)
├── planner.py             # classify / extract / assume / outline
├── executor.py             # per-section content generation
├── reflector.py             # self-check + repair
├── renderer.py               # python-docx rendering
├── llm.py                     # LangChain ChatGroq wrapper (optional)
├── logger_config.py            # clean logging setup
├── static/
│   └── index.html                # web UI (form, live status, download)
├── test_pipeline.py                # dependency-light sanity check (planner→renderer)
├── test_stream.py                    # streaming event/merge logic regression test
├── outputs/                            # generated .docx files
├── requirements.txt
├── .env.example
└── README.md
```
