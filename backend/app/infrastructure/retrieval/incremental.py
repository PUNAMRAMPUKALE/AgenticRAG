from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

from app.domain.models import Chunk
from app.infrastructure.llm.embeddings import get_embedder
from app.infrastructure.persistence.vectors import PostgresVectorStore
from app.infrastructure.retrieval.ingest import ingest_bytes
from app.infrastructure.retrieval.sparse import SparseIndex

log = logging.getLogger(__name__)


def stamp_fingerprint(stamps: dict[str, str]) -> str:
    h = hashlib.sha256()
    for rel, etag in sorted(stamps.items()):
        h.update(rel.encode())
        h.update(etag.encode())
    return h.hexdigest()[:16]


@dataclass
class IncrementalResult:
    chunks: list[Chunk]
    index: SparseIndex
    version: str
    changed_files: int
    reused_files: int


async def sync_incremental(
    store: PostgresVectorStore,
    *,
    remote: dict[str, str],
    fingerprint: str,
    fetch_bytes: Callable[[str], Awaitable[bytes]],
) -> IncrementalResult:
    """Chunk+embed only files whose stamp changed. Unchanged files load from Postgres."""
    embedder = get_embedder()
    model = embedder.model if embedder else ""
    stored = await store.stamps()
    stored_model = await store.stored_embedding_model()
    if stored and stored_model != model:
        await store.clear_all()
        stored = {}

    removed = [key for key in stored if key not in remote]
    if removed:
        await store.delete_sources(removed)
        log.info("Removed %s deleted knowledge files from Postgres", len(removed))

    changed = [key for key, stamp in remote.items() if stored.get(key) != stamp]
    reused = len(remote) - len(changed)

    for key in changed:
        try:
            data = await fetch_bytes(key)
            chunks = await asyncio.to_thread(ingest_bytes, key, data)
        except Exception:
            log.exception("Failed to ingest %s", key)
            continue
        if not chunks:
            log.warning("No usable chunks from %s", key)
            await store.replace_source(key, remote[key], model, [], np.zeros((0, 0), dtype=np.float32))
            continue
        if embedder:
            vectors = await asyncio.to_thread(embedder.embed, [c.text for c in chunks])
        else:
            vectors = np.zeros((0, 0), dtype=np.float32)
        await store.replace_source(key, remote[key], model, chunks, vectors)
        log.info("Re-chunked and stored %s (%s chunks)", key, len(chunks))

    chunks, dense = await store.load_all()
    if dense is None and embedder and chunks:
        dense = await asyncio.to_thread(embedder.embed, [c.text for c in chunks])
        log.warning("Persisted embeddings missing; re-embedded %s chunks", len(chunks))
    index = SparseIndex(chunks, embedder=embedder, dense=dense)
    log.info(
        "Knowledge index: %s chunks, %s files re-chunked, %s files reused from Postgres",
        len(chunks),
        len(changed),
        reused,
    )
    return IncrementalResult(
        chunks=chunks,
        index=index,
        version=fingerprint,
        changed_files=len(changed),
        reused_files=reused,
    )
