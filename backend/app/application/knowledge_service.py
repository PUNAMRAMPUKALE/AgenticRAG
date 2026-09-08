from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.domain.knowledge import chunk_record
from app.domain.models import Chunk
from app.domain.ports import AnswerCache, KnowledgeLoader, SearchIndex
from app.infrastructure.llm.embeddings import get_embedder
from app.infrastructure.persistence.ingest_runs import IngestRunRepository
from app.infrastructure.retrieval.incremental import stamp_fingerprint, sync_incremental, sync_one
from app.infrastructure.retrieval.vespa_store import VespaChunkStore

log = logging.getLogger(__name__)


@dataclass
class ReindexResult:
    index_version: str
    docs_indexed: int
    flushed_keys: int
    reindexed_by: str
    changed: bool = True


class KnowledgeService:
    def __init__(
        self,
        loader: KnowledgeLoader,
        cache: AnswerCache,
        vector_store: VespaChunkStore | None = None,
        ingest_runs: IngestRunRepository | None = None,
        knowledge_source: str = "s3",
    ):
        self._loader = loader
        self._cache = cache
        self._vector_store = vector_store
        self._ingest_runs = ingest_runs
        self._knowledge_source = knowledge_source
        self._lock = asyncio.Lock()
        self.chunks: list[Chunk] = []
        self.index: SearchIndex | None = None
        self.index_version: str = ""
        self.ingesting: bool = False
        self.last_changed_files: int = 0
        self.last_reused_files: int = 0
        self.docs_indexed: int = 0
        if vector_store is not None:
            from app.infrastructure.retrieval.vespa_index import VespaSearchIndex

            self.index = VespaSearchIndex(vector_store)

    def load(self) -> None:
        raise RuntimeError("Search is Vespa-only. Do not load the corpus into the API process.")

    async def reindex(self, actor: str) -> ReindexResult:
        async with self._lock:
            self.ingesting = True
            try:
                return await self._rebuild(actor)
            finally:
                self.ingesting = False

    async def reindex_if_changed(self, actor: str) -> ReindexResult | None:
        async with self._lock:
            self.ingesting = True
            try:
                version = await asyncio.to_thread(self._loader.fingerprint)
                if version == self.index_version and self.index is not None:
                    return None
                return await self._rebuild(actor)
            finally:
                self.ingesting = False

    async def _rebuild(self, actor: str) -> ReindexResult:
        if self._vector_store is not None and hasattr(self._loader, "list_stamps"):
            remote = await asyncio.to_thread(self._loader.list_stamps)
            fingerprint = stamp_fingerprint(remote)

            async def fetch_bytes(source_key: str) -> bytes:
                return await asyncio.to_thread(self._loader.read_bytes, source_key)

            result = await sync_incremental(
                self._vector_store,
                remote=remote,
                fingerprint=fingerprint,
                fetch_bytes=fetch_bytes,
            )
            self.chunks = result.chunks
            self.index = result.index
            self.index_version = result.version
            self.last_changed_files = result.changed_files
            self.last_reused_files = result.reused_files
            self.docs_indexed = result.docs_indexed
        else:
            raise RuntimeError("Knowledge ingest requires Vespa and a stamp-aware loader.")
        flushed = 0
        if self.last_changed_files or actor.startswith("reindex"):
            flushed = await self._cache.flush_answers()
        await self._cache.set_index_version(self.index_version)
        if self._ingest_runs is not None:
            model = ""
            embedder = get_embedder()
            if embedder:
                model = embedder.model
            await self._ingest_runs.record(
                actor=actor,
                status="succeeded",
                knowledge_source=self._knowledge_source,
                embedding_model=model,
                index_version=self.index_version,
                files_seen=self.last_changed_files + self.last_reused_files,
                files_rechunked=self.last_changed_files,
                files_reused=self.last_reused_files,
                files_deleted=0,
                chunks_indexed=self.docs_indexed,
            )
        log.info(
            "Knowledge ingest: %s chunks, version %s, flushed %s cache keys (%s)",
            self.docs_indexed,
            self.index_version,
            flushed,
            actor,
        )
        return ReindexResult(
            index_version=self.index_version,
            docs_indexed=self.docs_indexed,
            flushed_keys=flushed,
            reindexed_by=actor,
        )

    async def ingest_object(self, source_key: str, *, deleted: bool, actor: str) -> str:
        """Process one S3 object. Returns changed, reused, deleted, or empty."""
        if self._vector_store is None or not hasattr(self._loader, "read_bytes"):
            raise RuntimeError("Per-object ingest requires Vespa and an S3 loader.")
        async with self._lock:
            self.ingesting = True
            try:
                treat_deleted = deleted
                etag = ""
                if not treat_deleted and hasattr(self._loader, "head_etag"):
                    found = await asyncio.to_thread(self._loader.head_etag, source_key)
                    if found is None:
                        treat_deleted = True
                    else:
                        etag = found
                outcome = await sync_one(
                    self._vector_store,
                    source_key=source_key,
                    etag=etag,
                    fetch_bytes=self._fetch_bytes,
                    deleted=treat_deleted,
                )
                files_deleted = 1 if treat_deleted else 0
                files_rechunked = 1 if outcome in {"changed", "empty"} else 0
                files_reused = 1 if outcome == "reused" else 0
                await self._after_object(
                    actor,
                    outcome,
                    source_key=source_key,
                    files_deleted=files_deleted,
                    files_rechunked=files_rechunked,
                    files_reused=files_reused,
                )
                return outcome
            except Exception as exc:
                if self._ingest_runs is not None:
                    await self._ingest_runs.record(
                        actor=actor,
                        status="failed",
                        knowledge_source=self._knowledge_source,
                        embedding_model="",
                        index_version=self.index_version,
                        files_seen=1,
                        files_rechunked=0,
                        files_reused=0,
                        files_deleted=0,
                        chunks_indexed=self.docs_indexed,
                        error_detail=f"{source_key}: {exc}"[:2000],
                    )
                raise
            finally:
                self.ingesting = False

    async def _fetch_bytes(self, source_key: str) -> bytes:
        return await asyncio.to_thread(self._loader.read_bytes, source_key)

    async def _after_object(
        self,
        actor: str,
        outcome: str,
        *,
        source_key: str,
        files_deleted: int,
        files_rechunked: int,
        files_reused: int,
    ) -> None:
        from app.infrastructure.retrieval.vespa_index import VespaSearchIndex

        self.index = VespaSearchIndex(self._vector_store)
        self.last_changed_files = files_rechunked
        self.last_reused_files = files_reused
        self.docs_indexed = self._vector_store.count_chunks() if self._vector_store else 0
        if outcome != "reused":
            self.index_version = stamp_fingerprint({source_key: f"{outcome}:{self.docs_indexed}"})
            flushed = await self._cache.flush_answers()
            await self._cache.set_index_version(self.index_version)
        else:
            flushed = 0
        if self._ingest_runs is not None:
            model = ""
            embedder = get_embedder()
            if embedder:
                model = embedder.model
            await self._ingest_runs.record(
                actor=actor,
                status="succeeded",
                knowledge_source=self._knowledge_source,
                embedding_model=model,
                index_version=self.index_version,
                files_seen=files_deleted + files_rechunked + files_reused,
                files_rechunked=files_rechunked,
                files_reused=files_reused,
                files_deleted=files_deleted,
                chunks_indexed=self.docs_indexed,
            )
        log.info(
            "Object ingest %s %s by %s (deleted=%s rechunked=%s reused=%s flushed=%s)",
            source_key,
            outcome,
            actor,
            files_deleted,
            files_rechunked,
            files_reused,
            flushed,
        )

    async def snapshot(self, *, file_id: str | None = None, offset: int = 0, limit: int = 50) -> dict:
        chunks = self.chunks
        if not chunks and self._vector_store is not None:
            chunks, _ = await self._vector_store.load_all()
        rows = chunks
        if file_id:
            rows = [c for c in rows if c.file_id == file_id]
        limit = min(max(limit, 1), 200)
        offset = max(offset, 0)
        files: dict[str, int] = {}
        for chunk in chunks:
            files[chunk.file_id] = files.get(chunk.file_id, 0) + 1
        return {
            "index_version": self.index_version,
            "chunk_count": len(chunks),
            "file_count": len(files),
            "files": [{"file_id": k, "chunks": v} for k, v in sorted(files.items())],
            "offset": offset,
            "limit": limit,
            "filtered_count": len(rows),
            "chunks": [chunk_record(c) for c in rows[offset : offset + limit]],
        }

    def live_chunk_count(self) -> int:
        if self._vector_store is not None:
            return self._vector_store.count_chunks()
        return self.docs_indexed or len(self.chunks)

