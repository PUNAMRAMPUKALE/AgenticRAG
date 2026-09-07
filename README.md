# Agentic RAG

Postgres for conversation history. Redis for answer cache. The API is an **OAuth2 resource server**: it never mints passwords or JWTs. The SPA signs in with **Authorization Code + PKCE** against an identity provider. Access tokens are checked with **JWKS** (`iss`, `aud`, `exp`, signature). Realm roles **analyst** and **admin** gate chat vs reindex.

Local IdP is **Keycloak**. Production should point `OIDC_ISSUER` at Auth0, Cognito, or Entra (https) and keep `OIDC_AUDIENCE` as this API’s identifier.

## Architecture

The API is a four-layer service. HTTP never talks to Redis, Postgres, or JWKS directly.

| Layer | Package | Owns |
|---|---|---|
| Presentation | `app.api` | Routes, auth dependencies, SSE |
| Application | `app.application` | Use cases: chat, conversations, reindex, health |
| Domain | `app.domain` | Entities, `Principal`, ports (interfaces) |
| Infrastructure | `app.infrastructure` | Postgres, Redis, Keycloak JWKS, TF-IDF, Pydantic AI |
| Cross-cutting | `app.core` | Settings, errors, request middleware |

`app.main` is the composition root (`uvicorn app.main:app`). Adapters are wired in `application/container.py`.

## Run

```bash
docker compose up -d postgres redis keycloak
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app.main:app --reload --port 8000
```

Wait until Keycloak answers `http://127.0.0.1:8080/realms/agenticrag` (first start can take ~30s). Health: `GET http://127.0.0.1:8000/health` should show `"postgres": true`, `"redis": true`, `"oidc": true`.

```bash
cd frontend
copy .env.example .env
npm install
npm run dev
```

Open the Vite URL (use **127.0.0.1**, not localhost, so the token `iss` matches `OIDC_ISSUER`).

| User | Password | Roles |
|---|---|---|
| analyst | analyst-pass | analyst |
| analyst2 | analyst-pass | analyst (isolation) |
| admin | admin-pass | analyst + admin |

## Authorization

| Route | Who |
|---|---|
| `GET /health`, `GET /v1/auth/config` | Public |
| `GET /v1/auth/me`, `POST /v1/chat`, `GET /v1/conversations` | Bearer token + **analyst** or **admin** |
| `POST /v1/reindex` | Bearer token + **admin** |

Conversations are stored under the token `sub`, not the display name.

## Production

```
ENVIRONMENT=production
OIDC_ISSUER=https://your-idp.example.com/realms/your-realm
OIDC_AUDIENCE=your-api-audience
OIDC_SPA_CLIENT_ID=your-spa-client
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
```

The API refuses to start in production if the issuer is not https. Configure the SPA client with PKCE, no implicit flow, no resource-owner password grant. Map an audience claim to `OIDC_AUDIENCE` and include realm roles in the access token.

## What is still later

Dense/hybrid pgvector search, Alembic in CI, MCP, HITL. Retrieval is still TF-IDF over sample markdown.
