# Agentic RAG (MVP)

Repo: [PUNAMRAMPUKALE/AgenticRAG](https://github.com/PUNAMRAMPUKALE/AgenticRAG)

One end-to-end feature: **ask a question over sample fund documents in React, get a cited answer from FastAPI**.

| Included now | Later |
|---|---|
| Ingest 3 markdown filings on startup | Drive watcher, add/update/delete |
| Sparse (TF-IDF) retrieval + citations | Dense + hybrid, SQL on tables |
| New chat vs continue (`session_id`) | Auth, LTM Mem0 |
| Repeat question → cache, no second search | Redis + ACL keys |
| Optional Pydantic AI if `LLM_API_KEY` is set | MCP ServiceNow/Workday, LangGraph HITL |

## Run

Terminal 1 — API:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Terminal 2 — UI:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

Copy `.env.example` to `.env` in the repo root and set `LLM_API_KEY` if you want a composed LLM answer. Without a key, the API still returns retrieved snippets (extractive).

## Try

1. “What is the redemption notice period?” → 30 calendar days + citation `redemption_policy`
2. Ask the **same question again** in the same chat → green banner, cache hit
3. **New chat** → new `session_id`
4. “Institutional expense ratio?” → 0.45%
