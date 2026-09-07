from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_container, require_any_role
from app.application.container import AppContainer
from app.domain.identity import CHAT_ROLES, REINDEX_ROLES, Principal

router = APIRouter(prefix="/v1", tags=["admin"])


@router.post("/reindex")
async def reindex(
    principal: Principal = Depends(require_any_role(*REINDEX_ROLES)),
    container: AppContainer = Depends(get_container),
):
    result = await container.knowledge.reindex(principal.username)
    return {
        "ok": True,
        "index_version": result.index_version,
        "docs_indexed": result.docs_indexed,
        "flushed_keys": result.flushed_keys,
        "reindexed_by": result.reindexed_by,
    }


@router.get("/knowledge")
async def knowledge_snapshot(
    file_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    principal: Principal = Depends(require_any_role(*CHAT_ROLES)),
    container: AppContainer = Depends(get_container),
):
    """Inspect stored chunks and metadata (in-memory index today; Vespa later)."""
    return container.knowledge.snapshot(file_id=file_id, offset=offset, limit=limit)
