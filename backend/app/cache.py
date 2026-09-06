from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

log = logging.getLogger(__name__)

KEY_PREFIX = "agenticrag:answer"
INDEX_VERSION_KEY = "agenticrag:index_version"
TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "900"))


def normalize_query(q: str) -> str:
    return " ".join(q.lower().split())


def build_cache_key(user_id: str, session_id: str, index_version: str, message: str) -> str:
    qh = hashlib.sha256(normalize_query(message).encode()).hexdigest()
    return f"{KEY_PREFIX}:{user_id}:{session_id}:{index_version}:{qh}"


class AnswerCache:
    def __init__(self, client: redis.Redis | None):
        self._r = client

    @property
    def enabled(self) -> bool:
        return self._r is not None

    async def get(self, key: str) -> tuple[str, list[dict]] | None:
        if not self._r:
            return None
        try:
            raw = await self._r.get(key)
        except RedisError as e:
            log.warning("Redis GET failed (%s); serving without cache", e)
            return None
        if not raw:
            return None
        data = json.loads(raw)
        return data["answer"], data["citations"]

    async def set(self, key: str, answer: str, citations: list[dict[str, Any]]) -> None:
        if not self._r:
            return
        payload = json.dumps({"answer": answer, "citations": citations})
        try:
            await self._r.set(key, payload, ex=TTL_SECONDS)
        except RedisError as e:
            log.warning("Redis SET failed (%s)", e)

    async def set_index_version(self, version: str) -> None:
        if not self._r:
            return
        try:
            await self._r.set(INDEX_VERSION_KEY, version)
        except RedisError as e:
            log.warning("Redis index version SET failed (%s)", e)

    async def flush_answers(self) -> int:
        """Drop all cached answers (call after reindex). TTL would also expire old keys."""
        if not self._r:
            return 0
        deleted = 0
        try:
            async for key in self._r.scan_iter(match=f"{KEY_PREFIX}:*"):
                deleted += await self._r.delete(key)
        except RedisError as e:
            log.warning("Redis flush failed (%s)", e)
        return deleted


async def connect_redis() -> redis.Redis | None:
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    client = redis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except RedisError as e:
        log.warning("Redis unavailable at %s (%s). Cache disabled until it is up.", url, e)
        await client.aclose()
        return None
    return client
