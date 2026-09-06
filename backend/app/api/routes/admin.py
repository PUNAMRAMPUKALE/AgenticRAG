from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_any_role
from app.core.security import ROLE_ADMIN, Principal
from app.ingest import ingest_knowledge

router = APIRouter(prefix="/v1", tags=["admin"])


@router.post("/reindex")
async def reindex(
    request: Request,
    principal: Principal = Depends(require_any_role(ROLE_ADMIN)),
):
    runtime = request.app.state.runtime
    chunks, index, index_version = ingest_knowledge()
    runtime.chunks = chunks
    runtime.index = index
    runtime.index_version = index_version
    flushed = await runtime.cache.flush_answers()
    await runtime.cache.set_index_version(index_version)
    return {
        "ok": True,
        "index_version": index_version,
        "docs_indexed": len(chunks),
        "flushed_keys": flushed,
        "reindexed_by": principal.username,
    }
