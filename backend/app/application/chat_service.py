from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.errors import ConversationNotFound, EmptyQuery, IndexNotReady
from app.domain.identity import Principal
from app.domain.models import Message
from app.domain.ports import AnswerCache, AnswerGenerator, ConversationRepository, SearchIndex


@dataclass
class ChatResult:
    session_id: str
    new_conversation: bool
    user_id: str
    username: str
    index_version: str
    redis_enabled: bool
    cache_hit: bool
    answer: str
    citations: list[dict]
    used_llm: bool


class ChatService:
    def __init__(
        self,
        conversations: ConversationRepository,
        cache: AnswerCache,
        generator: AnswerGenerator,
    ):
        self._conversations = conversations
        self._cache = cache
        self._generator = generator

    async def ask(
        self,
        principal: Principal,
        message: str,
        session_id: str | None,
        index: SearchIndex | None,
        index_version: str,
    ) -> ChatResult:
        if index is None:
            raise IndexNotReady()
        text = message.strip()
        if not text:
            raise EmptyQuery()

        user_id = principal.subject
        manager = principal.is_manager
        new_conversation = not session_id
        if new_conversation:
            session_id = str(uuid.uuid4())
            await self._conversations.create(session_id, user_id, text[:60], is_manager=manager)
        else:
            existing = await self._conversations.get(session_id, user_id, is_manager=manager)
            if not existing:
                raise ConversationNotFound("Conversation not found. Start a new chat.")

        await self._conversations.log_request(user_id, text, session_id, is_manager=manager)

        cached = await self._cache.get(user_id, session_id, index_version, text)
        if cached:
            answer, citations = cached
            await self._conversations.add_message(
                session_id, Message(role="user", content=text), user_id=user_id, is_manager=manager
            )
            await self._conversations.add_message(
                session_id,
                Message(role="assistant", content=answer, citations=citations, cache_hit=True),
                user_id=user_id,
                is_manager=manager,
            )
            return ChatResult(
                session_id=session_id,
                new_conversation=new_conversation,
                user_id=user_id,
                username=principal.username,
                index_version=index_version,
                redis_enabled=self._cache.enabled,
                cache_hit=True,
                answer=answer,
                citations=citations,
                used_llm=False,
            )

        await self._conversations.add_message(
            session_id, Message(role="user", content=text), user_id=user_id, is_manager=manager
        )
        answer, citations, used_llm = await self._generator.generate(text, index)
        await self._conversations.add_message(
            session_id,
            Message(role="assistant", content=answer, citations=citations),
            user_id=user_id,
            is_manager=manager,
        )
        await self._cache.set(user_id, session_id, index_version, text, answer, citations)
        return ChatResult(
            session_id=session_id,
            new_conversation=new_conversation,
            user_id=user_id,
            username=principal.username,
            index_version=index_version,
            redis_enabled=self._cache.enabled,
            cache_hit=False,
            answer=answer,
            citations=citations,
            used_llm=used_llm,
        )
