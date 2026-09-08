from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_container, require_any_role
from app.application.container import AppContainer
from app.core.errors import AppError
from app.domain.identity import CHAT_ROLES, REINDEX_ROLES, Principal
from app.evals.runner import run_evals
from app.infrastructure.retrieval.ingest_queue import enqueue_full_reindex

router = APIRouter(prefix="/v1", tags=["admin"])
_eval_lock = asyncio.Lock()


@router.post("/reindex")
async def reindex(
    principal: Principal = Depends(require_any_role(*REINDEX_ROLES)),
    container: AppContainer = Depends(get_container),
):
    settings = container.settings
    queue_url = settings.knowledge_s3_queue_url.strip()
    if queue_url and not settings.ingest_in_api:
        try:
            await asyncio.to_thread(
                enqueue_full_reindex,
                queue_url,
                principal.username,
                settings.knowledge_s3_region.strip() or None,
            )
        except Exception as exc:
            raise AppError(503, f"Could not queue reindex on SQS: {exc}") from exc
        return {
            "ok": True,
            "queued": True,
            "reindexed_by": principal.username,
            "detail": "Full reindex queued for the ingest worker.",
        }
    if settings.ingest_in_api or settings.knowledge_source.strip().lower() != "s3":
        result = await container.knowledge.reindex(principal.username)
        return {
            "ok": True,
            "queued": False,
            "index_version": result.index_version,
            "docs_indexed": result.docs_indexed,
            "flushed_keys": result.flushed_keys,
            "reindexed_by": result.reindexed_by,
        }
    raise AppError(
        503,
        "Ingest runs in the worker. Set KNOWLEDGE_S3_QUEUE_URL or INGEST_IN_API=true for local single-process.",
    )


@router.get("/ingest/status")
async def ingest_status(
    principal: Principal = Depends(require_any_role(*REINDEX_ROLES)),
    container: AppContainer = Depends(get_container),
):
    """Live ingest traces, per-document chunking, errors, and recent logs."""
    return await container.knowledge.ingest_status()


@router.get("/observability")
async def observability(
    principal: Principal = Depends(require_any_role(*REINDEX_ROLES)),
    container: AppContainer = Depends(get_container),
):
    return await container.knowledge.ingest_status()


@router.get("/knowledge")
async def knowledge_snapshot(
    file_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    principal: Principal = Depends(require_any_role(*CHAT_ROLES)),
    container: AppContainer = Depends(get_container),
):
    """Inspect chunks stored in Vespa (paginated)."""
    return await container.knowledge.snapshot(file_id=file_id, offset=offset, limit=limit)


@router.post("/evals")
async def run_eval_suite(
    generate: bool = Query(False),
    principal: Principal = Depends(require_any_role(*REINDEX_ROLES)),
    container: AppContainer = Depends(get_container),
):
    """Gold retrieval evals against live Vespa. generate=true also runs the chat generator."""
    index = container.knowledge.index
    if index is None:
        raise AppError(503, "Search index is not ready")
    if _eval_lock.locked():
        raise AppError(409, "An eval run is already in progress")
    async with _eval_lock:
        report = await run_evals(index, generate=generate)
        try:
            report["vespa_chunks"] = container.knowledge.live_chunk_count()
        except Exception:
            report["vespa_chunks"] = 0
        report["run_by"] = principal.username
        return report
