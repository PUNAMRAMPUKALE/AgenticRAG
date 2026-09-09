from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.chat_service import ChatService
from app.application.conversation_service import ConversationService
from app.application.health_service import HealthService
from app.application.knowledge_service import KnowledgeService
from app.core.config import Settings
from app.domain.ports import AnswerCache, ConversationRepository, IdentityProvider, SessionStore
from app.infrastructure.agents.hitl import HitlQueue
from app.infrastructure.agents.orchestrator import KnowledgeOrchestrator
from app.infrastructure.cache.answers import RedisAnswerCache, connect_redis
from app.infrastructure.identity.google import GoogleIdentity
from app.infrastructure.identity.sessions import RedisSessionStore
from app.infrastructure.persistence.conversations import PostgresConversationRepository
from app.infrastructure.persistence.ingest_runs import IngestRunRepository
from app.infrastructure.retrieval.corpus import CorpusKnowledgeLoader
from app.infrastructure.retrieval.s3_loader import S3CorpusLoader
from app.infrastructure.retrieval.s3_sync import KnowledgeS3Pipeline
from app.infrastructure.retrieval.vespa_store import VespaChunkStore
from app.infrastructure.retrieval.watch import KnowledgeIngestWatcher


@dataclass
class AppContainer:
    settings: Settings
    conversations: ConversationRepository
    cache: AnswerCache
    identity: IdentityProvider
    sessions: SessionStore
    knowledge: KnowledgeService
    chat: ChatService
    conversation_queries: ConversationService
    health: HealthService
    redis_client: Any = None
    ingest_watcher: KnowledgeIngestWatcher | None = None
    s3_pipeline: KnowledgeS3Pipeline | None = None
    hitl: HitlQueue | None = None

    async def aclose(self) -> None:
        if self.ingest_watcher is not None:
            self.ingest_watcher.stop()
            self.ingest_watcher = None
        if self.s3_pipeline is not None:
            self.s3_pipeline.stop()
            self.s3_pipeline = None
        if self.redis_client is not None:
            await self.redis_client.aclose()
        await self.conversations.close()


async def build_container(settings: Settings, *, run_ingest: bool | None = None) -> AppContainer:
    settings.require_production_guards()
    conversations = PostgresConversationRepository(settings)
    await conversations.init_schema()
    if not await conversations.ping():
        raise RuntimeError(
            "PostgreSQL is unavailable. From the repo root run: docker compose up -d postgres redis vespa"
        )

    redis_client = await connect_redis(settings.redis_url)
    if redis_client is None:
        raise RuntimeError(
            "Redis is unavailable. From the repo root run: docker compose up -d postgres redis vespa"
        )
    cache = RedisAnswerCache(redis_client, ttl_seconds=settings.cache_ttl_seconds)
    source = settings.knowledge_source.strip().lower() or "local"
    disk_loader: CorpusKnowledgeLoader | None = None
    if source == "s3":
        if not settings.knowledge_s3_bucket.strip():
            raise RuntimeError("KNOWLEDGE_S3_BUCKET is required when KNOWLEDGE_SOURCE=s3.")
        loader: CorpusKnowledgeLoader | S3CorpusLoader = S3CorpusLoader(
            bucket=settings.knowledge_s3_bucket.strip(),
            prefix=settings.knowledge_s3_prefix,
            region=settings.knowledge_s3_region.strip() or None,
        )
    else:
        disk_loader = CorpusKnowledgeLoader()
        loader = disk_loader
    vespa_url = settings.vespa_url.strip() or "http://127.0.0.1:8080"
    start_ingest = settings.ingest_in_api if run_ingest is None else run_ingest
    vespa = VespaChunkStore(
        vespa_url,
        config_url=settings.vespa_config_url.strip() or "http://127.0.0.1:19071",
        auto_deploy=bool(run_ingest or start_ingest),
    )
    ingest_runs = IngestRunRepository(conversations.engine)
    knowledge = KnowledgeService(
        loader,
        cache,
        vector_store=vespa,
        ingest_runs=ingest_runs,
        knowledge_source=source,
    )
    if source != "s3":
        await knowledge.reindex("startup-local")

    identity = GoogleIdentity(settings)
    sessions = RedisSessionStore(redis_client, ttl_seconds=settings.session_hours * 3600)
    hitl = HitlQueue(redis_client)
    generator = KnowledgeOrchestrator(hitl)
    ingest_watcher: KnowledgeIngestWatcher | None = None
    s3_pipeline: KnowledgeS3Pipeline | None = None
    if source == "s3" and start_ingest:
        s3_pipeline = KnowledgeS3Pipeline(
            knowledge,
            poll_seconds=settings.knowledge_s3_poll_seconds,
            queue_url=settings.knowledge_s3_queue_url,
            region=settings.knowledge_s3_region.strip() or None,
            loader=loader if isinstance(loader, S3CorpusLoader) else None,
            dlq_url=settings.knowledge_s3_dlq_url,
            max_receive=settings.knowledge_s3_max_receive,
            visibility_timeout=settings.knowledge_s3_visibility_timeout,
            reconcile_seconds=settings.knowledge_s3_reconcile_seconds,
        )
    elif disk_loader is not None and settings.knowledge_watch:
        ingest_watcher = KnowledgeIngestWatcher(
            knowledge,
            disk_loader.knowledge_dir,
            debounce_seconds=settings.knowledge_watch_debounce_ms / 1000,
            poll_seconds=settings.knowledge_poll_seconds,
        )

    return AppContainer(
        settings=settings,
        conversations=conversations,
        cache=cache,
        identity=identity,
        sessions=sessions,
        knowledge=knowledge,
        chat=ChatService(conversations, cache, generator),
        conversation_queries=ConversationService(conversations),
        health=HealthService(settings, conversations, cache, identity, vespa),
        redis_client=redis_client,
        ingest_watcher=ingest_watcher,
        s3_pipeline=s3_pipeline,
        hitl=hitl,
    )

