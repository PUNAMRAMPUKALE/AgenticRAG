from __future__ import annotations

import json
import time
import uuid
from typing import Any


class HitlQueue:
    """Human-in-the-loop queue for escalation. Redis when available, memory otherwise."""

    def __init__(self, redis_client: Any | None = None):
        self._redis = redis_client
        self._mem: list[dict] = []

    async def enqueue(self, *, query: str, user_id: str, session_id: str, reason: str) -> str:
        item = {
            "id": str(uuid.uuid4()),
            "query": query[:500],
            "user_id": user_id,
            "session_id": session_id,
            "reason": reason,
            "status": "pending",
            "ts": time.time(),
        }
        if self._redis is not None:
            await self._redis.lpush("hitl:queue", json.dumps(item))
        else:
            self._mem.insert(0, item)
        return item["id"]

    async def list_pending(self, limit: int = 50) -> list[dict]:
        if self._redis is not None:
            raw = await self._redis.lrange("hitl:queue", 0, max(0, limit - 1))
            rows = []
            for blob in raw:
                try:
                    rows.append(json.loads(blob))
                except Exception:
                    continue
            return [r for r in rows if r.get("status") == "pending"]
        return [r for r in self._mem if r.get("status") == "pending"][:limit]

    async def resolve(self, item_id: str, note: str = "") -> bool:
        rows = await self.list_pending(200)
        found = False
        updated: list[dict] = []
        for row in rows:
            if row.get("id") == item_id:
                row["status"] = "resolved"
                row["note"] = note[:500]
                found = True
            if row.get("status") == "pending":
                updated.append(row)
        if self._redis is not None:
            await self._redis.delete("hitl:queue")
            if updated:
                await self._redis.rpush("hitl:queue", *[json.dumps(r) for r in reversed(updated)])
        else:
            self._mem = updated
        return found
