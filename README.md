# Agentic RAG

Postgres for conversation history (replicas share one database). Redis for answer cache. JWT for identity. Local UI may use a **dev login** flag; production must turn that off and use an IdP.

## Run

```bash
docker compose up -d postgres redis
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app.main:app --reload --port 8000
```

`GET http://127.0.0.1:8000/health` should show `"postgres": true` and `"redis": true`.

```bash
cd frontend
npm install
npm run dev
```

## Production flags

```
ENVIRONMENT=production
AUTH_ALLOW_DEV_LOGIN=false
JWT_SECRET=<long random secret>
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
```

The API refuses to start if production still has the default JWT secret or open `/v1/auth/token`. Point the UI at your IdP (Auth0, Cognito, Entra) and send `Authorization: Bearer`.

## What is still later

Dense/hybrid pgvector search, Alembic-only migrations in CI, MCP, HITL. Retrieval is still TF-IDF over sample markdown until the next slice.
