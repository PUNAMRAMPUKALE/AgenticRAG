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
from app.cache import AnswerCache, TTL_SECONDS, build_cache_key, connect_redis
from app.ingest import ingest_knowledge
from app.models import Conversation, Message

_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env")
load_dotenv()

conversations: dict[str, Conversation] = {}
chunks = []
index = None
index_version = ""
cache = AnswerCache(None)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global chunks, index, index_version, cache
    chunks, index, index_version = ingest_knowledge()
    client = await connect_redis()
    cache = AnswerCache(client)
    await cache.set_index_version(index_version)
    yield
    if client is not None:
        await client.aclose()


app = FastAPI(title="Fintech AI MVP", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


@app.get("/health")
def health():
    return {
        "ok": True,
        "docs_indexed": len(chunks),
        "index_version": index_version,
        "redis": cache.enabled,
        "cache_ttl_seconds": TTL_SECONDS,
        "llm_enabled": bool(os.getenv("LLM_API_KEY", "").strip()),
        "conversations": len(conversations),
    }


@app.post("/v1/auth/token")
def create_token(body: TokenRequest):
    """Dev/demo login. Production: replace with your IdP (Auth0, Cognito, Entra)."""
    token = issue_token(body.user_id.strip())
    return {"access_token": token, "token_type": "bearer", "user_id": body.user_id.strip()}


@app.post("/v1/reindex")
async def reindex(user_id: str = Depends(user_from_authorization)):
    """Reload knowledge files, bump index_version, flush Redis answers so stale hits cannot be reused."""
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


@app.get("/v1/conversations/{session_id}")
def get_conversation(session_id: str, user_id: str = Depends(user_from_authorization)):
    conv = conversations.get(session_id)
    if not conv or conv.user_id != user_id:
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

    new_session = not body.session_id
    if new_session:
        session_id = str(uuid.uuid4())
        conv = Conversation(session_id=session_id, user_id=user_id, title=text[:60])
        conversations[session_id] = conv
    else:
        session_id = body.session_id
        conv = conversations.get(session_id)
        if not conv or conv.user_id != user_id:
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
            conv.messages.append(Message(role="user", content=text))
            conv.messages.append(
                Message(role="assistant", content=answer, citations=citations, cache_hit=True)
            )
            yield _sse({"type": "cache_hit", "value": True})
            yield _sse({"type": "token", "text": answer})
            yield _sse({"type": "citations", "citations": citations})
            yield _sse({"type": "done", "session_id": session_id, "cache_hit": True})
            return

        yield _sse({"type": "cache_hit", "value": False})
        conv.messages.append(Message(role="user", content=text))
        answer, citations, used_llm = await generate_answer(text, index)
        conv.messages.append(Message(role="assistant", content=answer, citations=citations))
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
