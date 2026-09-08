from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.ports import AnswerCache, ConversationRepository, IdentityProvider
from app.infrastructure.retrieval.vespa_store import VespaChunkStore


@dataclass
class HealthStatus:
    ok: bool
    environment: str
    postgres: bool
    google: bool
    redis: bool
    vespa: bool
    docs_indexed: int
    index_version: str
    cache_ttl_seconds: int
    llm_enabled: bool
    conversations: int
    ingest_watch: bool
    knowledge_source: str
    embeddings: bool
    ingesting: bool
    vector_store: str
    files_rechunked: int
    files_reused: int
    ingest_in_api: bool
    ingest_queue: bool
    ingest_stage: str
    ingest_source_key: str
    ingest_files_done: int
    ingest_files_total: int


class HealthService:
    def __init__(
        self,
        settings: Settings,
        conversations: ConversationRepository,
        cache: AnswerCache,
        identity: IdentityProvider,
        vespa: VespaChunkStore | None = None,
    ):
        self._settings = settings
        self._conversations = conversations
        self._cache = cache
        self._identity = identity
        self._vespa = vespa

    async def status(
        self,
        docs_indexed: int,
        index_version: str,
        ingesting: bool = False,
        files_rechunked: int = 0,
        files_reused: int = 0,
        ingest_watch: bool = False,
        ingest_stage: str = "idle",
        ingest_source_key: str = "",
        ingest_files_done: int = 0,
        ingest_files_total: int = 0,
    ) -> HealthStatus:
        pg_ok = await self._conversations.ping()
        google_ok = self._identity.ready
        redis_ok = self._cache.enabled
        vespa_ok = await self._vespa.ping() if self._vespa is not None else False
        conversation_count = 0
        if pg_ok:
            try:
                conversation_count = await self._conversations.count()
            except Exception:
                conversation_count = 0
        return HealthStatus(
            ok=pg_ok and google_ok and redis_ok and vespa_ok,
            environment=self._settings.environment,
            postgres=pg_ok,
            google=google_ok,
            redis=redis_ok,
            vespa=vespa_ok,
            docs_indexed=docs_indexed,
            index_version=index_version,
            cache_ttl_seconds=self._settings.cache_ttl_seconds,
            llm_enabled=bool(self._settings.llm_api_key.strip()),
            conversations=conversation_count,
            ingest_watch=ingest_watch,
            knowledge_source=self._settings.knowledge_source.strip().lower() or "local",
            embeddings=bool(self._settings.llm_api_key.strip()),
            ingesting=ingesting,
            vector_store="vespa",
            files_rechunked=files_rechunked,
            files_reused=files_reused,
            ingest_in_api=self._settings.ingest_in_api,
            ingest_queue=bool(self._settings.knowledge_s3_queue_url.strip()),
            ingest_stage=ingest_stage,
            ingest_source_key=ingest_source_key,
            ingest_files_done=ingest_files_done,
            ingest_files_total=ingest_files_total,
        )
