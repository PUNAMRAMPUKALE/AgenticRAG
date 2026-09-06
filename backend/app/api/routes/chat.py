from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import generate_answer
from app.api.deps import get_runtime, get_store, require_any_role
from app.cache import build_cache_key
from app.core.security import ROLE_ADMIN, ROLE_ANALYST, Principal
from app.models import Message
from app.runtime import Runtime
from app.store import ConversationStore

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


@router.post("/chat")
async def chat(
    body: ChatRequest,
    principal: Principal = Depends(require_any_role(ROLE_ANALYST, ROLE_ADMIN)),
    store: ConversationStore = Depends(get_store),
    runtime: Runtime = Depends(get_runtime),
):
    if runtime.index is None:
        raise HTTPException(503, "Index not ready")

    text = body.message.strip()
    if not text:
        raise HTTPException(400, "Empty query")

    user_id = principal.subject
    new_session = not body.session_id
    if new_session:
        session_id = str(uuid.uuid4())
        await store.create(session_id, user_id, text[:60])
    else:
        session_id = body.session_id
        existing = await store.get(session_id, user_id)
        if not existing:
            raise HTTPException(404, "Conversation not found. Start a new chat.")

    cache_key = build_cache_key(user_id, session_id, runtime.index_version, text)
    cached = await runtime.cache.get(cache_key)

    async def events():
        yield _sse(
            {
                "type": "session",
                "session_id": session_id,
                "new_conversation": new_session,
                "user_id": user_id,
                "username": principal.username,
                "index_version": runtime.index_version,
                "redis": runtime.cache.enabled,
            }
        )

        if cached:
            answer, citations = cached
            await store.add_message(session_id, Message(role="user", content=text))
            await store.add_message(
                session_id,
                Message(role="assistant", content=answer, citations=citations, cache_hit=True),
            )
            yield _sse({"type": "cache_hit", "value": True})
            yield _sse({"type": "token", "text": answer})
            yield _sse({"type": "citations", "citations": citations})
            yield _sse({"type": "done", "session_id": session_id, "cache_hit": True})
            return

        yield _sse({"type": "cache_hit", "value": False})
        await store.add_message(session_id, Message(role="user", content=text))
        answer, citations, used_llm = await generate_answer(text, runtime.index)
        await store.add_message(
            session_id, Message(role="assistant", content=answer, citations=citations)
        )
        await runtime.cache.set(cache_key, answer, citations)
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
