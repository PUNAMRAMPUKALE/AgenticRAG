from __future__ import annotations

from app.domain.models import Chunk
from app.infrastructure.retrieval.guardrails import guard_hits, guard_query
from app.infrastructure.retrieval.sparse import format_hits
from app.infrastructure.retrieval.vespa_store import VespaChunkStore


class VespaSearchIndex:
    """SearchIndex adapter: queries Vespa, does not hold embeddings in the API process."""

    def __init__(self, store: VespaChunkStore):
        self._store = store
        self.chunks: list[Chunk] = []

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        guarded = guard_query(query, k=k)
        hits = self._store.search_chunks(guarded.text, k=guarded.k)
        return guard_hits(hits, k=guarded.k)

    def format_for_agent(self, hits: list[tuple[Chunk, float]]) -> str:
        return format_hits(hits)
