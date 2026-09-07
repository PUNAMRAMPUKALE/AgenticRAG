from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.deps import get_container, require_any_role
from app.application.container import AppContainer
from app.domain.identity import CHAT_ROLES, Principal

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    principal: Principal = Depends(require_any_role(*CHAT_ROLES)),
    container: AppContainer = Depends(get_container),
):
    rows = await container.conversation_queries.list_for_user(
        principal.subject, is_manager=principal.is_manager
    )
    return {"conversations": [asdict(r) for r in rows]}


@router.get("/{session_id}")
async def get_conversation(
    session_id: str,
    principal: Principal = Depends(require_any_role(*CHAT_ROLES)),
    container: AppContainer = Depends(get_container),
):
    conv = await container.conversation_queries.get_for_user(
        session_id, principal.subject, is_manager=principal.is_manager
    )
    return {
        "session_id": conv.session_id,
        "title": conv.title,
        "messages": [m.__dict__ for m in conv.messages],
    }
