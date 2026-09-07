from __future__ import annotations

import os
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

    async def status(self, docs_indexed: int, index_version: str) -> HealthStatus:
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
            llm_enabled=bool((os.getenv("LLM_API_KEY") or "").strip()),
            conversations=await self._conversations.count() if pg_ok else 0,
        )
