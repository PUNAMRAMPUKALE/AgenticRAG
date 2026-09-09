from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.core.errors import ConversationNotFound, IndexNotReady
from app.core.metrics import CHAT_REQUESTS
from app.core.telemetry import get_tracer, record_exception
from app.domain.identity import Principal
from app.domain.models import Message
from app.domain.ports import AgentTurn, AnswerCache, AnswerGenerator, ConversationRepository, SearchIndex
from app.infrastructure.retrieval.guardrails import guard_query

log = logging.getLogger(__name__)


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
    used_llm: bool = False
    cost_usd: float = 0.0
    quality_retries: int = 0
    hitl_pending: bool = False
    blocked: bool = False
    intent: str = ""
    llm_calls: int = 0


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
        *,
        retrieval_ready: bool = True,
    ) -> ChatResult:
        if index is None or not retrieval_ready:
            raise IndexNotReady()
        text = guard_query(message).text
        with get_tracer().start_as_current_span("chat.ask") as span:
            span.set_attribute("chat.new_conversation", not bool(session_id))
            try:
                result = await self._ask_body(
                    principal, text, session_id, index, index_version
                )
                CHAT_REQUESTS.labels("cache_hit" if result.cache_hit else "ok").inc()
                span.set_attribute("chat.cache_hit", result.cache_hit)
                span.set_attribute("chat.used_llm", result.used_llm)
                span.set_attribute("chat.intent", result.intent)
                return result
            except Exception as exc:
                CHAT_REQUESTS.labels("error").inc()
                record_exception(exc)
                raise

    async def _ask_body(
        self,
        principal: Principal,
        text: str,
        session_id: str | None,
        index: SearchIndex,
        index_version: str,
    ) -> ChatResult:
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
        try:
            turn = await self._generator.generate(text, index, user_id=user_id, session_id=session_id)
        except TypeError:
            turn = await self._generator.generate(text, index)
        if not isinstance(turn, AgentTurn):
            answer, citations, used_llm = turn
            turn = AgentTurn(answer=answer, citations=citations, used_llm=used_llm)
        await self._conversations.add_message(
            session_id,
            Message(role="assistant", content=turn.answer, citations=turn.citations),
            user_id=user_id,
            is_manager=manager,
        )
        if not turn.blocked and not turn.hitl_pending:
            await self._cache.set(user_id, session_id, index_version, text, turn.answer, turn.citations)
        return ChatResult(
            session_id=session_id,
            new_conversation=new_conversation,
            user_id=user_id,
            username=principal.username,
            index_version=index_version,
            redis_enabled=self._cache.enabled,
            cache_hit=False,
            answer=turn.answer,
            citations=turn.citations,
            used_llm=turn.used_llm,
            cost_usd=turn.cost_usd,
            quality_retries=turn.quality_retries,
            hitl_pending=turn.hitl_pending,
            blocked=turn.blocked,
            intent=turn.intent,
            llm_calls=turn.llm_calls,
        )
