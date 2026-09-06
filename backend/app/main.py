from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager

from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import generate_answer
from app.auth import TokenRequest, issue_token, user_from_authorization
from app.cache import AnswerCache, build_cache_key, connect_redis
from app.ingest import ingest_knowledge
from app.models import Message
from app.settings import get_settings
from app.store import ConversationStore

_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env")
load_dotenv()

store: ConversationStore | None = None
chunks = []
index = None
index_version = ""
cache = AnswerCache(None)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global chunks, index, index_version, cache, store
    settings = get_settings()
    settings.require_production_guards()
    store = ConversationStore(settings)
    await store.init_schema()
    if not await store.ping():
        raise RuntimeError(
            "PostgreSQL is unavailable. From the repo root run: docker compose up -d postgres redis"
        )
    chunks, index, index_version = ingest_knowledge()
    client = await connect_redis(settings.redis_url)
    cache = AnswerCache(client, ttl_seconds=settings.cache_ttl_seconds)
    await cache.set_index_version(index_version)
    yield
    if client is not None:
        await client.aclose()
    if store is not None:
        await store.close()


app = FastAPI(title="Agentic RAG", version="0.3.0", lifespan=lifespan)
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


def _db() -> ConversationStore:
    if store is None:
        raise HTTPException(503, "Database not ready")
    return store


@app.get("/health")
async def health():
    settings = get_settings()
    db = store
    pg_ok = await db.ping() if db else False
    return {
        "ok": pg_ok,
        "environment": settings.environment,
        "postgres": pg_ok,
        "docs_indexed": len(chunks),
        "index_version": index_version,
        "redis": cache.enabled,
        "cache_ttl_seconds": settings.cache_ttl_seconds,
        "llm_enabled": bool((os.getenv("LLM_API_KEY") or "").strip()),
        "conversations": await db.count() if db and pg_ok else 0,
        "dev_login": settings.auth_allow_dev_login,
    }


@app.post("/v1/auth/token")
def create_token(body: TokenRequest):
    settings = get_settings()
    if not settings.auth_allow_dev_login:
        raise HTTPException(
            403,
            "Dev login is disabled. Issue JWTs from your identity provider (OIDC).",
        )
    token = issue_token(body.user_id.strip())
    return {"access_token": token, "token_type": "bearer", "user_id": body.user_id.strip()}


@app.post("/v1/reindex")
async def reindex(user_id: str = Depends(user_from_authorization)):
    global chunks, index, index_version
    chunks, index, index_version = ingest_knowledge()
    flushed = await cache.flush_answers()
    await cache.set_index_version(index_version)
    return {
        "ok": True,
        "index_version": index_version,
        "docs_indexed": len(chunks),
        "flushed_keys": flushed,
        "reindexed_by": user_id,
    }


@app.get("/v1/conversations")
async def list_conversations(user_id: str = Depends(user_from_authorization)):
    return {"conversations": await _db().list_for_user(user_id)}


@app.get("/v1/conversations/{session_id}")
async def get_conversation(session_id: str, user_id: str = Depends(user_from_authorization)):
    conv = await _db().get(session_id, user_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return {
        "session_id": conv.session_id,
        "title": conv.title,
        "messages": [m.__dict__ for m in conv.messages],
    }


@app.post("/v1/chat")
async def chat(body: ChatRequest, user_id: str = Depends(user_from_authorization)):
    if index is None:
        raise HTTPException(503, "Index not ready")

    text = body.message.strip()
    if not text:
        raise HTTPException(400, "Empty query")

    db = _db()
    new_session = not body.session_id
    if new_session:
        session_id = str(uuid.uuid4())
        await db.create(session_id, user_id, text[:60])
    else:
        session_id = body.session_id
        existing = await db.get(session_id, user_id)
        if not existing:
            raise HTTPException(404, "Conversation not found. Start a new chat.")

    cache_key = build_cache_key(user_id, session_id, index_version, text)
    cached = await cache.get(cache_key)

    async def events():
        yield _sse(
            {
                "type": "session",
                "session_id": session_id,
                "new_conversation": new_session,
                "user_id": user_id,
                "index_version": index_version,
                "redis": cache.enabled,
            }
        )

        if cached:
            answer, citations = cached
            await db.add_message(session_id, Message(role="user", content=text))
            await db.add_message(
                session_id,
                Message(role="assistant", content=answer, citations=citations, cache_hit=True),
            )
            yield _sse({"type": "cache_hit", "value": True})
            yield _sse({"type": "token", "text": answer})
            yield _sse({"type": "citations", "citations": citations})
            yield _sse({"type": "done", "session_id": session_id, "cache_hit": True})
            return

        yield _sse({"type": "cache_hit", "value": False})
        await db.add_message(session_id, Message(role="user", content=text))
        answer, citations, used_llm = await generate_answer(text, index)
        await db.add_message(session_id, Message(role="assistant", content=answer, citations=citations))
        await cache.set(cache_key, answer, citations)
        yield _sse({"type": "token", "text": answer})
        yield _sse({"type": "citations", "citations": citations})
        yield _sse(
            {
                "type": "done",
                "session_id": session_id,
                "cache_hit": False,
                "used_llm": used_llm,
            }
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
