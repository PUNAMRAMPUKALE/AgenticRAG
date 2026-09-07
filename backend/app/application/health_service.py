from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import Settings
from app.domain.ports import AnswerCache, ConversationRepository, TokenVerifier


@dataclass
class HealthStatus:
    ok: bool
    environment: str
    postgres: bool
    oidc: bool
    oidc_issuer: str
    docs_indexed: int
    index_version: str
    redis: bool
    cache_ttl_seconds: int
    llm_enabled: bool
    conversations: int


class HealthService:
    def __init__(
        self,
        settings: Settings,
        conversations: ConversationRepository,
        cache: AnswerCache,
        verifier: TokenVerifier,
    ):
        self._settings = settings
        self._conversations = conversations
        self._cache = cache
        self._verifier = verifier

    async def status(self, docs_indexed: int, index_version: str) -> HealthStatus:
        pg_ok = await self._conversations.ping()
        oidc_ok = self._verifier.ready
        return HealthStatus(
            ok=pg_ok and oidc_ok,
            environment=self._settings.environment,
            postgres=pg_ok,
            oidc=oidc_ok,
            oidc_issuer=self._settings.oidc_issuer,
            docs_indexed=docs_indexed,
            index_version=index_version,
            redis=self._cache.enabled,
            cache_ttl_seconds=self._settings.cache_ttl_seconds,
            llm_enabled=bool((os.getenv("LLM_API_KEY") or "").strip()),
            conversations=await self._conversations.count() if pg_ok else 0,
        )
