from __future__ import annotations

from app.core.errors import ConversationNotFound
from app.domain.models import Conversation, ConversationSummary
from app.domain.ports import ConversationRepository


class ConversationService:
    def __init__(self, conversations: ConversationRepository):
        self._conversations = conversations

    async def list_for_user(self, user_id: str) -> list[ConversationSummary]:
        return await self._conversations.list_for_user(user_id)

    async def get_for_user(self, session_id: str, user_id: str) -> Conversation:
        conv = await self._conversations.get(session_id, user_id)
        if not conv:
            raise ConversationNotFound()
        return conv
