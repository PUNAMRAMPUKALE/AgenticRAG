from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import get_container, require_any_role
from app.application.chat_service import ChatResult
from app.application.container import AppContainer
from app.domain.identity import CHAT_ROLES, Principal

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


@router.post("/chat")
async def chat(
    body: ChatRequest,
    principal: Principal = Depends(require_any_role(*CHAT_ROLES)),
    container: AppContainer = Depends(get_container),
):
    result = await container.chat.ask(
        principal=principal,
        message=body.message,
        session_id=body.session_id,
        index=container.knowledge.index,
        index_version=container.knowledge.index_version,
        retrieval_ready=container.knowledge.retrieval_ready(),
    )

    async def events():
        yield _sse(_session_event(result))
        yield _sse({"type": "cache_hit", "value": result.cache_hit})
        yield _sse({"type": "token", "text": result.answer})
        yield _sse({"type": "citations", "citations": result.citations})
        done = {"type": "done", "session_id": result.session_id, "cache_hit": result.cache_hit}
        if not result.cache_hit:
            done["used_llm"] = result.used_llm
            if result.intent:
                done["intent"] = result.intent
            if result.hitl_pending:
                done["hitl_pending"] = True
            if result.cost_usd:
                done["cost_usd"] = result.cost_usd
        yield _sse(done)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _session_event(result: ChatResult) -> dict:
    return {
        "type": "session",
        "session_id": result.session_id,
        "new_conversation": result.new_conversation,
        "user_id": result.user_id,
        "username": result.username,
        "index_version": result.index_version,
        "redis": result.redis_enabled,
    }


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"
