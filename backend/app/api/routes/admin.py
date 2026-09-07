from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container, require_any_role
from app.application.container import AppContainer
from app.domain.identity import ROLE_ADMIN, Principal

router = APIRouter(prefix="/v1", tags=["admin"])


@router.post("/reindex")
async def reindex(
    principal: Principal = Depends(require_any_role(ROLE_ADMIN)),
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
