from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from app.api.deps import get_container
from app.application.container import AppContainer

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(request: Request):
    container: AppContainer = get_container(request)
    status = await container.health.status(
        docs_indexed=len(container.knowledge.chunks),
        index_version=container.knowledge.index_version,
        ingesting=container.knowledge.ingesting or container.knowledge.index is None,
        files_rechunked=container.knowledge.last_changed_files,
        files_reused=container.knowledge.last_reused_files,
    )
    return asdict(status)
