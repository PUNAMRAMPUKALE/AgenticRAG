from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.health import router as health_router
from app.cache import AnswerCache, connect_redis
from app.core.security import TokenVerifier
from app.ingest import ingest_knowledge
from app.middleware import RequestContextMiddleware
from app.runtime import Runtime
from app.settings import get_settings
from app.store import ConversationStore

_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env")
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.require_production_guards()
    store = ConversationStore(settings)
    await store.init_schema()
    if not await store.ping():
        raise RuntimeError(
            "PostgreSQL is unavailable. From the repo root run: docker compose up -d postgres redis keycloak"
        )
    chunks, index, index_version = ingest_knowledge()
    redis_client = await connect_redis(settings.redis_url)
    cache = AnswerCache(redis_client, ttl_seconds=settings.cache_ttl_seconds)
    await cache.set_index_version(index_version)
    verifier = TokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        jwks_url=settings.oidc_jwks_url or None,
    )
    await verifier.warmup()
    app.state.runtime = Runtime(
        store=store,
        cache=cache,
        verifier=verifier,
        chunks=chunks,
        index=index,
        index_version=index_version,
    )
    yield
    if redis_client is not None:
        await redis_client.aclose()
    await store.close()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="Agentic RAG", version="0.4.0", lifespan=lifespan)
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(conversations_router)
    application.include_router(chat_router)
    application.include_router(admin_router)
    return application


app = create_app()
