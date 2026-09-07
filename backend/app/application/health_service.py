from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.ports import AnswerCache, ConversationRepository, IdentityProvider


@dataclass
class HealthStatus:
    ok: bool
    environment: str
    postgres: bool
    google: bool
    redis: bool
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


class HealthService:
    def __init__(
        self,
        settings: Settings,
        conversations: ConversationRepository,
        cache: AnswerCache,
        identity: IdentityProvider,
    ):
        self._settings = settings
        self._conversations = conversations
        self._cache = cache
        self._identity = identity

    async def status(
        self,
        docs_indexed: int,
        index_version: str,
        ingesting: bool = False,
        files_rechunked: int = 0,
        files_reused: int = 0,
    ) -> HealthStatus:
        pg_ok = await self._conversations.ping()
        google_ok = self._identity.ready
        redis_ok = self._cache.enabled
        return HealthStatus(
            ok=pg_ok and google_ok and redis_ok,
            environment=self._settings.environment,
            postgres=pg_ok,
            google=google_ok,
            redis=redis_ok,
            docs_indexed=docs_indexed,
            index_version=index_version,
            cache_ttl_seconds=self._settings.cache_ttl_seconds,
            llm_enabled=bool(self._settings.llm_api_key.strip()),
            conversations=await self._conversations.count() if pg_ok else 0,
            ingest_watch=self._settings.knowledge_watch
            or self._settings.knowledge_source.strip().lower() == "s3",
            knowledge_source=self._settings.knowledge_source.strip().lower() or "local",
            embeddings=bool(self._settings.llm_api_key.strip()),
            ingesting=ingesting,
            vector_store="vespa",
            files_rechunked=files_rechunked,
            files_reused=files_reused,
        )
