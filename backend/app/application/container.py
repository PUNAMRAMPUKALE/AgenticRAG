from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.chat_service import ChatService
from app.application.conversation_service import ConversationService
from app.application.health_service import HealthService
from app.application.knowledge_service import KnowledgeService
from app.core.config import Settings
from app.domain.ports import AnswerCache, ConversationRepository, TokenVerifier
from app.infrastructure.cache.answers import RedisAnswerCache, connect_redis
from app.infrastructure.identity.jwks import JwksTokenVerifier
from app.infrastructure.llm.assistant import KnowledgeAssistant
from app.infrastructure.persistence.conversations import PostgresConversationRepository
from app.infrastructure.retrieval.markdown import MarkdownKnowledgeLoader


@dataclass
class AppContainer:
    settings: Settings
    conversations: ConversationRepository
    cache: AnswerCache
    verifier: TokenVerifier
    knowledge: KnowledgeService
    chat: ChatService
    conversation_queries: ConversationService
    health: HealthService
    redis_client: Any = None

    async def aclose(self) -> None:
        if self.redis_client is not None:
            await self.redis_client.aclose()
        await self.conversations.close()


async def build_container(settings: Settings) -> AppContainer:
    settings.require_production_guards()
    conversations = PostgresConversationRepository(settings)
    await conversations.init_schema()
    if not await conversations.ping():
        raise RuntimeError(
            "PostgreSQL is unavailable. From the repo root run: docker compose up -d postgres redis keycloak"
        )

    redis_client = await connect_redis(settings.redis_url)
    cache = RedisAnswerCache(redis_client, ttl_seconds=settings.cache_ttl_seconds)
    knowledge = KnowledgeService(MarkdownKnowledgeLoader(), cache)
    knowledge.load()
    await cache.set_index_version(knowledge.index_version)

    verifier = JwksTokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        jwks_url=settings.oidc_jwks_url or None,
    )
    await verifier.warmup()

    generator = KnowledgeAssistant()
    return AppContainer(
        settings=settings,
        conversations=conversations,
        cache=cache,
        verifier=verifier,
        knowledge=knowledge,
        chat=ChatService(conversations, cache, generator),
        conversation_queries=ConversationService(conversations),
        health=HealthService(settings, conversations, cache, verifier),
        redis_client=redis_client,
    )
