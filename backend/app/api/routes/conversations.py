from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_store, require_any_role
from app.core.security import ROLE_ADMIN, ROLE_ANALYST, Principal
from app.store import ConversationStore

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    principal: Principal = Depends(require_any_role(ROLE_ANALYST, ROLE_ADMIN)),
    store: ConversationStore = Depends(get_store),
):
    return {"conversations": await store.list_for_user(principal.subject)}


@router.get("/{session_id}")
async def get_conversation(
    session_id: str,
    principal: Principal = Depends(require_any_role(ROLE_ANALYST, ROLE_ADMIN)),
    store: ConversationStore = Depends(get_store),
):
    conv = await store.get(session_id, principal.subject)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return {
        "session_id": conv.session_id,
        "title": conv.title,
        "messages": [m.__dict__ for m in conv.messages],
    }
