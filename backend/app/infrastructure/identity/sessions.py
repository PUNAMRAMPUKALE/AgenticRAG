from __future__ import annotations

import json
import uuid

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.domain.identity import Principal

KEY_PREFIX = "agenticrag:session"


class RedisSessionStore:
    def __init__(self, client: redis.Redis | None, ttl_seconds: int):
        self._r = client
        self._ttl = ttl_seconds

    async def create(self, principal: Principal) -> str:
        if not self._r:
            raise RuntimeError("Redis is required for Google sign-in sessions")
        sid = str(uuid.uuid4())
        payload = json.dumps(
            {
                "sub": principal.subject,
                "username": principal.username,
                "roles": sorted(principal.roles),
                "email": principal.email,
            }
        )
        await self._r.set(f"{KEY_PREFIX}:{sid}", payload, ex=self._ttl)
        return sid

    async def get(self, session_id: str) -> Principal | None:
        if not self._r or not session_id:
            return None
        try:
            raw = await self._r.get(f"{KEY_PREFIX}:{session_id}")
        except RedisError:
            return None
        if not raw:
            return None
        data = json.loads(raw)
        return Principal(
            subject=str(data["sub"]),
            username=str(data["username"]),
            roles=frozenset(data.get("roles") or []),
            email=str(data.get("email") or ""),
        )

    async def delete(self, session_id: str) -> None:
        if not self._r or not session_id:
            return
        try:
            await self._r.delete(f"{KEY_PREFIX}:{session_id}")
        except RedisError:
            return
