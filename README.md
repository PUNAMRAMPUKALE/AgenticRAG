# Agentic RAG

Postgres for conversation history. Redis for answer cache and login sessions. **Sign in with Google** is authentication. Authorization uses three roles: **analyst**, **senior analyst**, and **manager (expert)**. All three can chat. Only managers can reindex.

## Architecture

| Layer | Package | Owns |
|---|---|---|
| Presentation | `app.api` | Routes, session cookie, SSE |
| Application | `app.application` | Chat, conversations, reindex, health |
| Domain | `app.domain` | Entities, `Principal`, ports |
| Infrastructure | `app.infrastructure` | Postgres, Redis, Google ID tokens, TF-IDF, Pydantic AI |
| Cross-cutting | `app.core` | Settings, errors, request middleware |

`uvicorn app.main:app` is the composition root.

## Google Cloud (once)

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → Create credentials → **OAuth client ID** → **Web application**.
2. Authorized JavaScript origins: `http://127.0.0.1:5173` (and `http://127.0.0.1:5174` if Vite uses that port).
3. Authorized redirect URIs: `http://127.0.0.1:5173` and `http://127.0.0.1:5174`.
4. Copy the client ID into repo-root `.env` as `GOOGLE_CLIENT_ID`.
5. Map Google emails in `.env`: `GOOGLE_ANALYST_EMAILS`, `GOOGLE_SENIOR_ANALYST_EMAILS`, `GOOGLE_MANAGER_EMAILS` (managers can reindex).

Use **127.0.0.1**, not `localhost`, in both the Cloud Console and the browser.

## Run

```bash
docker compose up -d postgres redis
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
# edit ..\.env and set GOOGLE_CLIENT_ID
uvicorn app.main:app --reload --port 8000
```

`GET http://127.0.0.1:8000/health` should show `"postgres": true`, `"redis": true`, `"google": true`.

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
| `POST /v1/reindex` | manager (expert) — `GOOGLE_MANAGER_EMAILS` |

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
```

Add your production HTTPS origin to the Google OAuth client. Serve UI and API on the same site so the session cookie is first-party.

## What is still later

Dense/hybrid pgvector search, Alembic in CI, MCP, HITL. Retrieval is still TF-IDF over sample markdown.
