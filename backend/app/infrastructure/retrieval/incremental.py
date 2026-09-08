from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

from app.core.ingest_context import ingest_source_key
from app.core.metrics import INGEST_CHUNKS, INGEST_FILES
from app.core.telemetry import get_tracer
from app.infrastructure.llm.embeddings import get_embedder
from app.infrastructure.retrieval.ingest import ingest_bytes
from app.infrastructure.retrieval.ingest_tracker import IngestTracker
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
    tracker: IngestTracker | None = None,
) -> IncrementalResult:
    """Chunk+embed only files whose stamp changed. Unchanged files load from Vespa."""
    embedder = get_embedder()
    model = embedder.model if embedder else ""
    if tracker:
        tracker.emit("vespa_ensure", detail="checking config 19071 then query 8080")
    if hasattr(store, "ensure_ready"):
        await store.ensure_ready()
    if tracker:
        tracker.emit("vespa_ready", detail="query port 8080 up")
    stored = await store.stamps()
    stored_model = await store.stored_embedding_model()
    if stored and stored_model != model:
        await store.clear_all()
        stored = {}
        if tracker:
            tracker.emit("vespa_cleared", detail="embedding model changed")

    removed = [key for key in stored if key not in remote]
    if removed:
        await store.delete_sources(removed)
        log.info(
            "Removed %s deleted knowledge files from Vespa",
            len(removed),
            extra={"pipeline": "ingest", "stage": "delete_stale", "files_total": len(removed)},
        )

    changed = [key for key, stamp in remote.items() if stored.get(key) != stamp]
    reused = len(remote) - len(changed)
    if tracker:
        tracker.emit(
            "s3_listed",
            detail=f"{len(remote)} objects in prefix",
            files_total=len(remote),
            files_changed=len(changed),
            files_reused=reused,
            files_done=0,
            files_failed=0,
        )
    log.info(
        "Ingest plan: %s remote, %s re-chunk, %s reuse",
        len(remote),
        len(changed),
        reused,
        extra={
            "pipeline": "ingest",
            "stage": "plan",
            "files_total": len(remote),
            "files_changed": len(changed),
            "files_reused": reused,
            "files_done": 0,
        },
    )

    failed = 0
    for i, key in enumerate(changed, start=1):
        started = time.perf_counter()
        key_token = ingest_source_key.set(key)
        with get_tracer().start_as_current_span("ingest.file") as span:
            span.set_attribute("ingest.source_key", key)
            if tracker:
                tracker.emit("file_start", source_key=key, files_done=i - 1, files_total=len(changed))
            log.info(
                "Ingest file start %s (%s/%s)",
                key,
                i,
                len(changed),
                extra={"pipeline": "ingest", "stage": "file_start", "source_key": key, "files_done": i - 1},
            )
            try:
                try:
                    data = await fetch_bytes(key)
                    chunks = await asyncio.to_thread(ingest_bytes, key, data)
                except Exception as exc:
                    failed += 1
                    elapsed = int((time.perf_counter() - started) * 1000)
                    INGEST_FILES.labels("error").inc()
                    log.exception(
                        "Failed to ingest %s",
                        key,
                        extra={"pipeline": "ingest", "stage": "file_error", "source_key": key, "status": "error"},
                    )
                    if tracker:
                        tracker.emit(
                            "file_error",
                            status="error",
                            source_key=key,
                            detail=str(exc)[:2000],
                            duration_ms=elapsed,
                            files_done=i,
                            files_failed=failed,
                            files_total=len(changed),
                        )
                    continue
                if not chunks:
                    INGEST_FILES.labels("empty").inc()
                    log.warning(
                        "No usable chunks from %s",
                        key,
                        extra={"pipeline": "ingest", "stage": "file_empty", "source_key": key},
                    )
                    await store.replace_source(key, remote[key], model, [], np.zeros((0, 0), dtype=np.float32))
                    if tracker:
                        tracker.emit("file_empty", source_key=key, files_done=i, files_total=len(changed))
                    continue
                if tracker:
                    tracker.emit(
                        "embed_start",
                        source_key=key,
                        chunks=len(chunks),
                        files_done=i - 1,
                        files_total=len(changed),
                    )
                if embedder:
                    vectors = await asyncio.to_thread(embedder.embed, [c.text for c in chunks])
                else:
                    vectors = np.zeros((0, 0), dtype=np.float32)
                await store.replace_source(key, remote[key], model, chunks, vectors)
                elapsed = int((time.perf_counter() - started) * 1000)
                INGEST_FILES.labels("ok").inc()
                INGEST_CHUNKS.inc(len(chunks))
                span.set_attribute("ingest.chunks", len(chunks))
                log.info(
                    "Re-chunked and stored %s (%s chunks)",
                    key,
                    len(chunks),
                    extra={
                        "pipeline": "ingest",
                        "stage": "file_ok",
                        "source_key": key,
                        "chunks": len(chunks),
                        "duration_ms": elapsed,
                        "files_done": i,
                    },
                )
                if tracker:
                    tracker.emit(
                        "file_ok",
                        source_key=key,
                        chunks=len(chunks),
                        duration_ms=elapsed,
                        files_done=i,
                        files_total=len(changed),
                    )
            finally:
                ingest_source_key.reset(key_token)

    index = VespaSearchIndex(store)
    docs_indexed = store.count_chunks() if hasattr(store, "count_chunks") else 0
    log.info(
        "Vespa search ready: %s chunks indexed, %s files re-chunked, %s reused, %s failed",
        docs_indexed,
        len(changed),
        reused,
        failed,
        extra={"pipeline": "ingest", "stage": "complete", "chunks": docs_indexed, "files_failed": failed},
    )
    if tracker:
        tracker.emit(
            "complete",
            chunks=docs_indexed,
            files_done=len(changed),
            files_failed=failed,
            files_total=len(changed),
            files_reused=reused,
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
    tracker: IngestTracker | None = None,
) -> str:
    """Ingest or delete a single source. Returns changed, reused, deleted, or empty."""
    embedder = get_embedder()
    model = embedder.model if embedder else ""
    key_token = ingest_source_key.set(source_key)
    started = time.perf_counter()
    with get_tracer().start_as_current_span("ingest.file") as span:
        span.set_attribute("ingest.source_key", source_key)
        if tracker:
            tracker.emit("file_start", source_key=source_key, files_total=1)
        try:
            if hasattr(store, "ensure_ready"):
                await store.ensure_ready()
            if deleted:
                await store.delete_sources([source_key])
                INGEST_FILES.labels("deleted").inc()
                log.info(
                    "Deleted %s from Vespa",
                    source_key,
                    extra={"pipeline": "ingest", "stage": "file_deleted", "source_key": source_key, "outcome": "deleted"},
                )
                if tracker:
                    tracker.emit("file_deleted", source_key=source_key, files_done=1, files_total=1)
                return "deleted"
            stored = ""
            if hasattr(store, "source_etag"):
                stored = await store.source_etag(source_key) or ""
            if stored == etag and etag:
                INGEST_FILES.labels("reused").inc()
                log.info(
                    "Skipped unchanged %s",
                    source_key,
                    extra={"pipeline": "ingest", "stage": "file_reused", "source_key": source_key, "outcome": "reused"},
                )
                if tracker:
                    tracker.emit("file_reused", source_key=source_key, files_done=1, files_total=1, files_reused=1)
                return "reused"
            data = await fetch_bytes(source_key)
            chunks = await asyncio.to_thread(ingest_bytes, source_key, data)
            if not chunks:
                INGEST_FILES.labels("empty").inc()
                log.warning(
                    "No usable chunks from %s",
                    source_key,
                    extra={"pipeline": "ingest", "stage": "file_empty", "source_key": source_key},
                )
                await store.replace_source(source_key, etag, model, [], np.zeros((0, 0), dtype=np.float32))
                if tracker:
                    tracker.emit("file_empty", source_key=source_key, files_done=1, files_total=1)
                return "empty"
            if embedder:
                vectors = await asyncio.to_thread(embedder.embed, [c.text for c in chunks])
            else:
                vectors = np.zeros((0, 0), dtype=np.float32)
            await store.replace_source(source_key, etag, model, chunks, vectors)
            elapsed = int((time.perf_counter() - started) * 1000)
            INGEST_FILES.labels("ok").inc()
            INGEST_CHUNKS.inc(len(chunks))
            span.set_attribute("ingest.chunks", len(chunks))
            log.info(
                "Re-chunked and stored %s (%s chunks)",
                source_key,
                len(chunks),
                extra={
                    "pipeline": "ingest",
                    "stage": "file_ok",
                    "source_key": source_key,
                    "chunks": len(chunks),
                    "duration_ms": elapsed,
                    "outcome": "changed",
                },
            )
            if tracker:
                tracker.emit(
                    "file_ok",
                    source_key=source_key,
                    chunks=len(chunks),
                    duration_ms=elapsed,
                    files_done=1,
                    files_total=1,
                )
            return "changed"
        except Exception:
            INGEST_FILES.labels("error").inc()
            raise
        finally:
            ingest_source_key.reset(key_token)
