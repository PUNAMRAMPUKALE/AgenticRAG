# Agentic RAG (MVP)

Repo: [PUNAMRAMPUKALE/AgenticRAG](https://github.com/PUNAMRAMPUKALE/AgenticRAG)

Ask fund-doc questions in React. FastAPI retrieves cited snippets. Answers are cached in **Redis** so every API replica shares the same hits.

Cache key: `user_id` (from JWT) + `session_id` + normalized question + `index_version`. TTL default **15 minutes**. `POST /v1/reindex` reloads files, bumps `index_version`, and flushes Redis answers.

## Run

1. Redis (required for shared cache):

```bash
docker compose up -d redis
```

2. API:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app.main:app --reload --port 8000
```

`GET http://127.0.0.1:8000/health` should show `"redis": true`. If Redis is down, chat still works; cache is skipped.

3. UI:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL. You are signed in as `analyst-1` (demo JWT). Ask a question, ask it again → Redis hit. Sign in as `analyst-2` → miss (different user in the key).

## Try

1. “What is the redemption notice period?” → 30 calendar days
2. Same question again → green Redis-hit banner
3. **New chat** → new session, miss
4. After editing a file in `backend/knowledge`, `POST /v1/reindex` with the same Bearer token → old cache cannot be reused (`index_version` changed)
