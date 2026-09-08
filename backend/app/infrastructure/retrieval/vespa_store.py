from __future__ import annotations

import hashlib
import io
import logging
import re
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

import httpx
import numpy as np

from app.domain.models import Chunk

log = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parents[4] / "vespa" / "application"
_EMBED_DIM = 1536
_SCHEMA_VERSION = 1
_CORPUS_ID = "horizon_trust"
_TENANT_ID = "default"


class VespaChunkStore:
    """Production Vespa store: knowledge_source registry + knowledge_chunk tensors."""

    def __init__(self, base_url: str, config_url: str = "http://127.0.0.1:19071"):
        self._base = (base_url or "").rstrip("/")
        self._config = (config_url or "http://127.0.0.1:19071").rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self._base)

    def _chunk_url(self, chunk_id: str) -> str:
        doc_id = quote(chunk_id.replace("/", "__"), safe="")
        return f"{self._base}/document/v1/default/knowledge_chunk/docid/{doc_id}"

    def _source_url(self, source_key: str) -> str:
        doc_id = quote(source_key.replace("/", "__"), safe="")
        return f"{self._base}/document/v1/default/knowledge_source/docid/{doc_id}"

    async def ping(self) -> bool:
        if not self._base:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base}/state/v1/health")
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def ensure_ready(self) -> None:
        if not self._base:
            raise RuntimeError("VESPA_URL is empty. Set VESPA_URL=http://127.0.0.1:8080")
        if not await self.ping():
            raise RuntimeError(
                "Vespa is not running. From the repo root: docker compose up -d postgres redis vespa"
            )
        await self._deploy_app()

    async def _deploy_app(self) -> None:
        if not _APP_DIR.is_dir():
            log.warning("Vespa application package missing at %s", _APP_DIR)
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in _APP_DIR.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(_APP_DIR).as_posix())
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self._config}/application/v2/tenant/default/prepareandactivate",
                    content=buf.getvalue(),
                    headers={"Content-Type": "application/zip"},
                )
            if response.status_code >= 400:
                log.warning("Vespa deploy HTTP %s: %s", response.status_code, response.text[:500])
            else:
                log.info("Vespa application deployed")
        except httpx.HTTPError:
            log.warning("Vespa config server not reachable at %s", self._config, exc_info=True)

    async def source_etag(self, source_key: str) -> str | None:
        if not self._base:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self._source_url(source_key))
        except httpx.HTTPError:
            return None
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            log.warning("Vespa source get %s HTTP %s", source_key, response.status_code)
            return None
        fields = (response.json() or {}).get("fields") or {}
        return str(fields.get("etag") or "")

    async def stamps(self) -> dict[str, str]:
        stamps: dict[str, str] = {}
        for fields in await self._visit_fields("knowledge_source"):
            key = str(fields.get("source_key") or "")
            etag = str(fields.get("etag") or "")
            if key:
                stamps[key] = etag
        return stamps

    async def stored_embedding_model(self) -> str:
        for fields in await self._visit_fields("knowledge_source"):
            model = str(fields.get("embedding_model") or "").strip()
            if model:
                return model
        return ""

    async def clear_all(self) -> None:
        await self._delete_selection("knowledge_chunk", "true")
        await self._delete_selection("knowledge_source", "true")
        log.info("Cleared Vespa knowledge_source and knowledge_chunk documents")

    async def delete_sources(self, source_keys: list[str]) -> None:
        for key in source_keys:
            escaped = key.replace("\\", "\\\\").replace('"', '\\"')
            await self._delete_selection("knowledge_chunk", f'knowledge_chunk.source_key=="{escaped}"')
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.delete(self._source_url(key))
            if response.status_code >= 400 and response.status_code != 404:
                log.warning("Vespa source delete %s HTTP %s", key, response.status_code)

    async def replace_source(
        self,
        source_key: str,
        etag: str,
        embedding_model: str,
        chunks: list[Chunk],
        vectors: np.ndarray,
    ) -> None:
        run_id = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)
        content_type = ""
        lower = source_key.lower()
        if lower.endswith(".pdf"):
            content_type = "application/pdf"
        elif lower.endswith(".md"):
            content_type = "text/markdown"
        elif lower.endswith(".xlsx") or lower.endswith(".xlsm"):
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif lower.endswith(".jsonl"):
            content_type = "application/jsonl"
        else:
            content_type = "text/plain"

        await self.delete_sources([source_key])
        async with httpx.AsyncClient(timeout=60.0) as client:
            source_fields = {
                "source_key": source_key,
                "corpus_id": _CORPUS_ID,
                "tenant_id": _TENANT_ID,
                "source_uri": source_key,
                "content_type": content_type,
                "etag": etag,
                "content_sha256": "",
                "byte_size": 0,
                "chunk_count": len(chunks),
                "embedding_model": embedding_model,
                "embedding_dim": _EMBED_DIM if embedding_model else 0,
                "schema_version": _SCHEMA_VERSION,
                "status": "ready" if chunks else "empty",
                "error_detail": "",
                "ingest_run_id": run_id,
                "ingested_at": now_ms,
                "updated_at": now_ms,
            }
            source_resp = await client.post(self._source_url(source_key), json={"fields": source_fields})
            if source_resp.status_code >= 400:
                log.warning("Vespa source put failed for %s: %s", source_key, source_resp.text[:300])

            for i, chunk in enumerate(chunks):
                text = chunk.text or ""
                ordinal = i
                if ":" in chunk.chunk_id:
                    try:
                        ordinal = int(chunk.chunk_id.rsplit(":", 1)[-1])
                    except ValueError:
                        ordinal = i
                fields = {
                    "chunk_id": chunk.chunk_id,
                    "source_key": source_key,
                    "corpus_id": _CORPUS_ID,
                    "tenant_id": _TENANT_ID,
                    "source_uri": source_key,
                    "file_id": chunk.file_id,
                    "ordinal": ordinal,
                    "title": chunk.title,
                    "text": text,
                    "section": chunk.section,
                    "page": chunk.page,
                    "as_of": chunk.as_of,
                    "doc_type": chunk.doc_type,
                    "strategy": chunk.strategy,
                    "language": "en",
                    "classification": "internal",
                    "char_count": len(text),
                    "token_count": max(len(text.split()), 0),
                    "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "embedding_model": embedding_model,
                    "embedding_dim": _EMBED_DIM if embedding_model else 0,
                    "schema_version": _SCHEMA_VERSION,
                    "ingest_run_id": run_id,
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
                if vectors.size and i < vectors.shape[0] and vectors.shape[1] == _EMBED_DIM:
                    fields["embedding"] = {"values": [float(x) for x in vectors[i].tolist()]}
                response = await client.post(self._chunk_url(chunk.chunk_id), json={"fields": fields})
                if response.status_code >= 400:
                    log.warning("Vespa chunk put failed for %s: %s", chunk.chunk_id, response.text[:300])

    async def load_all(self) -> tuple[list[Chunk], np.ndarray | None]:
        chunks: list[Chunk] = []
        vectors: list[list[float]] = []
        missing = False
        docs = await self._visit_fields("knowledge_chunk")
        docs.sort(key=lambda f: (str(f.get("source_key") or ""), int(f.get("ordinal") or 0)))
        for fields in docs:
            chunks.append(
                Chunk(
                    chunk_id=str(fields.get("chunk_id") or ""),
                    file_id=str(fields.get("file_id") or ""),
                    title=str(fields.get("title") or ""),
                    text=str(fields.get("text") or ""),
                    as_of=str(fields.get("as_of") or ""),
                    section=str(fields.get("section") or ""),
                    page=str(fields.get("page") or ""),
                    doc_type=str(fields.get("doc_type") or ""),
                    strategy=str(fields.get("strategy") or ""),
                )
            )
            values = _tensor_values(fields.get("embedding"))
            if values and len(values) == _EMBED_DIM:
                vectors.append(values)
            else:
                missing = True
        if not chunks or missing or len(vectors) != len(chunks):
            return chunks, None
        return chunks, np.asarray(vectors, dtype=np.float32)

    def search_chunks(
        self,
        query: str,
        k: int = 4,
        *,
        classification: str = "internal",
        tenant_id: str = "default",
        corpus_id: str = "horizon_trust",
    ) -> list[tuple[Chunk, float]]:
        """Live retrieval in Vespa (HNSW + BM25). Does not load the corpus into RAM."""
        from app.infrastructure.llm.embeddings import get_embedder

        if not query.strip() or not self._base:
            return []
        embedder = get_embedder()
        tenant_id = _safe_token(tenant_id, "default")
        corpus_id = _safe_token(corpus_id, "horizon_trust")
        classification = _safe_token(classification, "internal")
        k = max(1, min(int(k), 20))
        yql = (
            "select * from knowledge_chunk where "
            f'tenant_id contains "{tenant_id}" and corpus_id contains "{corpus_id}" '
            f'and classification contains "{classification}" and '
            f"(userQuery() or ({{targetHits:{k}}}nearestNeighbor(embedding, q_emb)))"
        )
        body: dict = {
            "yql": yql,
            "query": query,
            "hits": k,
            "ranking": "hybrid",
            "timeout": "5s",
        }
        if embedder:
            vector = embedder.embed([query])
            if vector.size:
                body["input.query(q_emb)"] = {"values": [float(x) for x in vector[0].tolist()]}
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(f"{self._base}/search/", json=body)
        except httpx.HTTPError:
            log.exception("Vespa search failed")
            return []
        if response.status_code >= 400:
            log.warning("Vespa search HTTP %s: %s", response.status_code, response.text[:400])
            return []
        hits: list[tuple[Chunk, float]] = []
        for hit in (response.json().get("root") or {}).get("children") or []:
            fields = hit.get("fields") or {}
            chunk = Chunk(
                chunk_id=str(fields.get("chunk_id") or ""),
                file_id=str(fields.get("file_id") or ""),
                title=str(fields.get("title") or ""),
                text=str(fields.get("text") or ""),
                as_of=str(fields.get("as_of") or ""),
                section=str(fields.get("section") or ""),
                page=str(fields.get("page") or ""),
                doc_type=str(fields.get("doc_type") or ""),
                strategy=str(fields.get("strategy") or ""),
            )
            hits.append((chunk, float(hit.get("relevance") or 0)))
        return hits

    def count_chunks(self) -> int:
        if not self._base:
            return 0
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{self._base}/search/",
                json={"yql": "select * from knowledge_chunk where true", "hits": 0, "timeout": "5s"},
            )
        if response.status_code >= 400:
            return 0
        return int(((response.json().get("root") or {}).get("fields") or {}).get("totalCount") or 0)

    async def _delete_selection(self, doc_type: str, selection: str) -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.delete(
                f"{self._base}/document/v1/default/{doc_type}/docid/",
                params={"selection": selection, "cluster": "knowledge"},
            )
        if response.status_code >= 400:
            log.warning("Vespa delete %s (%s) HTTP %s", doc_type, selection[:80], response.status_code)

    async def _visit_fields(self, doc_type: str) -> list[dict]:
        out: list[dict] = []
        continuation = ""
        async with httpx.AsyncClient(timeout=120.0) as client:
            while True:
                params = {"cluster": "knowledge", "wantedDocumentCount": "400", "timeout": "120s"}
                if continuation:
                    params["continuation"] = continuation
                response = await client.get(
                    f"{self._base}/document/v1/default/{doc_type}/docid/",
                    params=params,
                )
                if response.status_code >= 400:
                    log.warning("Vespa visit %s HTTP %s: %s", doc_type, response.status_code, response.text[:300])
                    break
                payload = response.json()
                for doc in payload.get("documents") or []:
                    fields = doc.get("fields") or {}
                    if fields:
                        out.append(fields)
                continuation = str(payload.get("continuation") or "")
                if not continuation:
                    break
        return out


def _safe_token(value: str, default: str) -> str:
    token = (value or default).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", token):
        return default
    return token


def _tensor_values(raw: object) -> list[float]:
    if isinstance(raw, dict):
        values = raw.get("values")
        if isinstance(values, list):
            return [float(x) for x in values]
        cells = raw.get("cells")
        if isinstance(cells, list) and cells:
            return [float(c.get("value", 0)) for c in cells if isinstance(c, dict)]
    if isinstance(raw, list):
        return [float(x) for x in raw]
    return []
