from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import Chunk
from app.domain.ports import AnswerCache, KnowledgeLoader, SearchIndex


@dataclass
class ReindexResult:
    index_version: str
    docs_indexed: int
    flushed_keys: int
    reindexed_by: str


class KnowledgeService:
    def __init__(self, loader: KnowledgeLoader, cache: AnswerCache):
        self._loader = loader
        self._cache = cache
        self.chunks: list[Chunk] = []
        self.index: SearchIndex | None = None
        self.index_version: str = ""

    def load(self) -> None:
        self.chunks, self.index, self.index_version = self._loader.load()

    async def reindex(self, actor: str) -> ReindexResult:
        self.load()
        flushed = await self._cache.flush_answers()
        await self._cache.set_index_version(self.index_version)
        return ReindexResult(
            index_version=self.index_version,
            docs_indexed=len(self.chunks),
            flushed_keys=flushed,
            reindexed_by=actor,
        )
