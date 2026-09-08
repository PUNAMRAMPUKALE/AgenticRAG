# Agentic RAG

Postgres for conversation history. Redis for answer cache and login sessions. **Sign in with Google** is authentication. Authorization uses three roles: **analyst**, **senior analyst**, and **manager (expert)**. All three can chat. Knowledge under `backend/knowledge/` is chunked automatically on file create, update, and delete. Managers can still force reindex.

## Architecture

| Layer | Package | Owns |
|---|---|---|
| Presentation | `app.api` | Routes, session cookie, SSE |
| Application | `app.application` | Chat, conversations, reindex, health |
| Domain | `app.domain` | Entities, `Principal`, ports |
| Infrastructure | `app.infrastructure` | Postgres (RLS), Redis, Google ID tokens, S3, Vespa, Pydantic AI |
| Cross-cutting | `app.core` | Settings, errors, request middleware |

`uvicorn app.main:app` is the API. `python -m app.worker.ingest` is the S3 ingest worker.

## Knowledge ingest

**Local (development):** drop markdown, PDF, or Excel into `backend/knowledge/`. The API watches that directory, re-chunks on change, writes chunks to Vespa, and flushes the answer cache.

**Production:** S3 holds original files. Vespa holds chunks and embeddings. Chat queries Vespa (hybrid BM25 + HNSW). Postgres holds users, chats, and audit only. The API does not run the S3 pipeline unless `INGEST_IN_API=true`.

```
Author / CMS  →  S3 (original files)
                     │
                     ├─ Object Created / Deleted → SQS (+ DLQ)
                     │                              │
                     │                              ▼
                     │                    ingest worker: one object
                     │                    GetObject → chunk → embed → Vespa
                     │
                     └─ periodic reconcile (optional)
                     │
                     ▼
              API chat: embed query → Vespa hybrid search → LLM
```

Set `KNOWLEDGE_S3_QUEUE_URL` and run `python -m app.worker.ingest`. Point the bucket (prefix) at that queue. Set `KNOWLEDGE_S3_DLQ_URL` (or an SQS redrive policy) so failed objects leave the main queue after `KNOWLEDGE_S3_MAX_RECEIVE` attempts. Without a queue URL the worker still lists the bucket on a timer.

Cleaning: Unicode NFKC, strip control chars, collapse whitespace, repair PDF hyphen/line wrap, drop empty or low-signal extracts.

Chunking: size 1200 / overlap 180. With `LLM_API_KEY`, OpenAI semantic split; otherwise TF-IDF cohesion. Search ranking is 70% dense / 30% BM25 in Vespa.

Leave `AWS_ACCESS_KEY_ID` empty in production and use an IAM role. Optional `AWS_SECRETS_ARN` loads missing env keys from Secrets Manager.

`POST /v1/reindex` remains a manual force rebuild for managers. Schema changes go through Alembic (`alembic upgrade head` from `backend/`, or `MIGRATE_ON_BOOT=true` in development).

## Google Cloud (once)

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → Create credentials → **OAuth client ID** → **Web application**.
2. Authorized JavaScript origins: `http://127.0.0.1:5173` (and `http://127.0.0.1:5174` if Vite uses that port).
3. Authorized redirect URIs: `http://127.0.0.1:5173` and `http://127.0.0.1:5174`.
4. Copy the client ID into repo-root `.env` as `GOOGLE_CLIENT_ID`.
5. Map Google emails in `.env`: `GOOGLE_ANALYST_EMAILS`, `GOOGLE_SENIOR_ANALYST_EMAILS`, `GOOGLE_MANAGER_EMAILS` (managers can reindex).

Use **127.0.0.1**, not `localhost`, in both the Cloud Console and the browser.

## Run

```bash
docker compose up -d postgres redis vespa
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
# edit ..\.env: GOOGLE_CLIENT_ID, LLM_API_KEY; wait until Vespa is healthy
uvicorn app.main:app --reload --port 8000
# production-style ingest (separate process): python -m app.worker.ingest
```

`GET http://127.0.0.1:8000/health` should show `"postgres": true`, `"redis": true`, `"google": true`, `"vespa": true`.

```bash
cd frontend
npm install
npm run dev
```

Open **http://127.0.0.1:5173** → **Sign in with Google**.

## Authorization

Google authenticates the person. The app assigns one role (highest match wins):

| Role | Env list | Access |
|---|---|---|
| analyst | `GOOGLE_ANALYST_EMAILS` (optional; this is also the default) | Chat and conversations |
| senior analyst | `GOOGLE_SENIOR_ANALYST_EMAILS` | Chat and conversations |
| manager (expert) | `GOOGLE_MANAGER_EMAILS` | Chat, conversations, and reindex |

| Route | Who |
|---|---|
| `GET /health`, `GET /v1/auth/config` | Public |
| `POST /v1/auth/google` | Google ID token |
| Chat and conversations | analyst, senior analyst, or manager |
| `POST /v1/reindex` | manager (expert) — optional force rebuild; ingest also runs automatically |

Conversations are stored under Google `sub`.

## Production

```
ENVIRONMENT=production
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_MANAGER_EMAILS=you@yourcompany.com
GOOGLE_SENIOR_ANALYST_EMAILS=
GOOGLE_ANALYST_EMAILS=
GOOGLE_ALLOWED_DOMAIN=yourcompany.com
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
KNOWLEDGE_SOURCE=s3
KNOWLEDGE_S3_BUCKET=your-company-knowledge
KNOWLEDGE_S3_PREFIX=knowledge
KNOWLEDGE_S3_REGION=us-east-2
KNOWLEDGE_S3_QUEUE_URL=https://sqs.us-east-2.amazonaws.com/123/knowledge-events
KNOWLEDGE_S3_DLQ_URL=https://sqs.us-east-2.amazonaws.com/123/knowledge-events-dlq
INGEST_IN_API=false
MIGRATE_ON_BOOT=false
AWS_DEFAULT_REGION=us-east-2
# Prefer an IAM role in production. Access keys are for local/dev only.
LLM_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Add your production HTTPS origin to the Google OAuth client. Serve UI and API on the same site so the session cookie is first-party.

## What is still later

MCP, HITL, CI test suite, and a dedicated `agenticrag_app` DB password in every environment. Production refuses to boot without a Google domain, SQS ingest queue, `INGEST_IN_API=false`, and `MIGRATE_ON_BOOT=false`. Manager reindex enqueues to SQS.
