from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.domain.knowledge import chunk_record
from app.domain.models import Chunk

log = logging.getLogger(__name__)


class VespaChunkStore:
    """Optional feed of chunk text + metadata into Vespa (BM25 now; tensors later)."""

    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self._base)

    async def replace_all(self, chunks: list[Chunk]) -> None:
        if not self._base:
            return
        async with httpx.AsyncClient(timeout=30.0) as client:
            for chunk in chunks:
                doc_id = quote(chunk.chunk_id.replace("/", "__"), safe="")
                url = f"{self._base}/document/v1/default/knowledge_chunk/docid/{doc_id}"
                payload = {"fields": chunk_record(chunk)}
                try:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                except httpx.HTTPError:
                    log.warning("Vespa feed failed for %s", chunk.chunk_id, exc_info=True)
                    return
        log.info("Fed %s chunks to Vespa at %s", len(chunks), self._base)
