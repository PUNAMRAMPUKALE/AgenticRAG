from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.domain.knowledge import chunk_record
from app.domain.models import Chunk
from app.domain.ports import AnswerCache, KnowledgeLoader, SearchIndex

log = logging.getLogger(__name__)


@dataclass
class ReindexResult:
    index_version: str
    docs_indexed: int
    flushed_keys: int
    reindexed_by: str
    changed: bool = True


class KnowledgeService:
    def __init__(self, loader: KnowledgeLoader, cache: AnswerCache, vespa: object | None = None):
        self._loader = loader
        self._cache = cache
        self._vespa = vespa
        self._lock = asyncio.Lock()
        self.chunks: list[Chunk] = []
        self.index: SearchIndex | None = None
        self.index_version: str = ""

    def load(self) -> None:
        self.chunks, self.index, self.index_version = self._loader.load()

    async def reindex(self, actor: str) -> ReindexResult:
        async with self._lock:
            return await self._rebuild(actor)

    async def reindex_if_changed(self, actor: str) -> ReindexResult | None:
        async with self._lock:
            version = await asyncio.to_thread(self._loader.fingerprint)
            if version == self.index_version:
                return None
            return await self._rebuild(actor)

    async def _rebuild(self, actor: str) -> ReindexResult:
        self.chunks, self.index, self.index_version = await asyncio.to_thread(self._loader.load)
        flushed = await self._cache.flush_answers()
        await self._cache.set_index_version(self.index_version)
        if self._vespa is not None and getattr(self._vespa, "enabled", False):
            await self._vespa.replace_all(self.chunks)
        log.info(
            "Knowledge ingest: %s chunks, version %s, flushed %s cache keys (%s)",
            len(self.chunks),
            self.index_version,
            flushed,
            actor,
        )
        return ReindexResult(
            index_version=self.index_version,
            docs_indexed=len(self.chunks),
            flushed_keys=flushed,
            reindexed_by=actor,
        )

    def snapshot(self, *, file_id: str | None = None, offset: int = 0, limit: int = 50) -> dict:
        rows = self.chunks
        if file_id:
            rows = [c for c in rows if c.file_id == file_id]
        limit = min(max(limit, 1), 200)
        offset = max(offset, 0)
        files: dict[str, int] = {}
        for chunk in self.chunks:
            files[chunk.file_id] = files.get(chunk.file_id, 0) + 1
        return {
            "index_version": self.index_version,
            "chunk_count": len(self.chunks),
            "file_count": len(files),
            "files": [{"file_id": k, "chunks": v} for k, v in sorted(files.items())],
            "offset": offset,
            "limit": limit,
            "filtered_count": len(rows),
            "chunks": [chunk_record(c) for c in rows[offset : offset + limit]],
        }
