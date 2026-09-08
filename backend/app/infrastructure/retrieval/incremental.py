from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

from app.domain.models import Chunk
from app.infrastructure.llm.embeddings import get_embedder
from app.infrastructure.retrieval.ingest import ingest_bytes
from app.infrastructure.retrieval.vespa_index import VespaSearchIndex

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
    index: VespaSearchIndex
    version: str
    changed_files: int
    reused_files: int
    docs_indexed: int


async def sync_incremental(
    store,
    *,
    remote: dict[str, str],
    fingerprint: str,
    fetch_bytes: Callable[[str], Awaitable[bytes]],
) -> IncrementalResult:
    """Chunk+embed only files whose stamp changed. Unchanged files load from Vespa."""
    embedder = get_embedder()
    model = embedder.model if embedder else ""
    if hasattr(store, "ensure_ready"):
        await store.ensure_ready()
    stored = await store.stamps()
    stored_model = await store.stored_embedding_model()
    if stored and stored_model != model:
        await store.clear_all()
        stored = {}

    removed = [key for key in stored if key not in remote]
    if removed:
        await store.delete_sources(removed)
        log.info("Removed %s deleted knowledge files from Vespa", len(removed))

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

    index = VespaSearchIndex(store)
    docs_indexed = store.count_chunks() if hasattr(store, "count_chunks") else 0
    log.info(
        "Vespa search ready: %s chunks indexed, %s files re-chunked, %s reused",
        docs_indexed,
        len(changed),
        reused,
    )
    return IncrementalResult(
        chunks=[],
        index=index,
        version=fingerprint,
        changed_files=len(changed),
        reused_files=reused,
        docs_indexed=docs_indexed,
    )


async def sync_one(
    store,
    *,
    source_key: str,
    etag: str,
    fetch_bytes: Callable[[str], Awaitable[bytes]],
    deleted: bool = False,
) -> str:
    """Ingest or delete a single source. Returns changed, reused, deleted, or empty."""
    embedder = get_embedder()
    model = embedder.model if embedder else ""
    if hasattr(store, "ensure_ready"):
        await store.ensure_ready()
    if deleted:
        await store.delete_sources([source_key])
        log.info("Deleted %s from Vespa", source_key)
        return "deleted"
    stored = ""
    if hasattr(store, "source_etag"):
        stored = await store.source_etag(source_key) or ""
    if stored == etag and etag:
        return "reused"
    data = await fetch_bytes(source_key)
    chunks = await asyncio.to_thread(ingest_bytes, source_key, data)
    if not chunks:
        log.warning("No usable chunks from %s", source_key)
        await store.replace_source(source_key, etag, model, [], np.zeros((0, 0), dtype=np.float32))
        return "empty"
    if embedder:
        vectors = await asyncio.to_thread(embedder.embed, [c.text for c in chunks])
    else:
        vectors = np.zeros((0, 0), dtype=np.float32)
    await store.replace_source(source_key, etag, model, chunks, vectors)
    log.info("Re-chunked and stored %s (%s chunks)", source_key, len(chunks))
    return "changed"
