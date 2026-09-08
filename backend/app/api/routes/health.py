from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request, Response

from app.api.deps import get_container
from app.application.container import AppContainer
from app.core.metrics import VESPA_CHUNKS, render_metrics

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(request: Request):
    container: AppContainer = get_container(request)
    knowledge = container.knowledge
    try:
        docs = knowledge.live_chunk_count()
    except Exception:
        docs = 0
    knowledge.docs_indexed = docs
    try:
        VESPA_CHUNKS.set(docs)
    except Exception:
        pass
    ingest_watch = container.s3_pipeline is not None or container.ingest_watcher is not None
    status = await container.health.status(
        docs_indexed=docs,
        index_version=knowledge.index_version,
        ingesting=knowledge.ingesting,
        files_rechunked=knowledge.last_changed_files,
        files_reused=knowledge.last_reused_files,
        ingest_watch=ingest_watch,
        ingest_stage=knowledge.tracker.live.stage,
        ingest_source_key=knowledge.tracker.live.source_key,
        ingest_files_done=knowledge.tracker.live.files_done,
        ingest_files_total=knowledge.tracker.live.files_changed or knowledge.tracker.live.files_total,
    )
    return asdict(status)


@router.get("/metrics")
async def metrics():
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
