from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.infrastructure.persistence.orm import KnowledgeIngestRunRow
from app.infrastructure.persistence.rls import apply_row_context


class IngestRunRepository:
    def __init__(self, engine: AsyncEngine):
        self._sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def record(
        self,
        *,
        actor: str,
        status: str,
        knowledge_source: str,
        embedding_model: str,
        index_version: str,
        files_seen: int,
        files_rechunked: int,
        files_reused: int,
        files_deleted: int,
        chunks_indexed: int,
        error_detail: str | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        async with self._sessions() as db:
            await apply_row_context(db, service=True)
            db.add(
                KnowledgeIngestRunRow(
                    run_id=run_id,
                    started_at=now,
                    finished_at=now,
                    actor=actor,
                    status=status,
                    knowledge_source=knowledge_source,
                    embedding_model=embedding_model,
                    index_version=index_version,
                    files_seen=files_seen,
                    files_rechunked=files_rechunked,
                    files_reused=files_reused,
                    files_deleted=files_deleted,
                    chunks_indexed=chunks_indexed,
                    error_detail=error_detail,
                )
            )
            await db.commit()
        return run_id

    async def list_recent(self, limit: int = 25) -> list[dict]:
        async with self._sessions() as db:
            await apply_row_context(db, service=True)
            result = await db.execute(
                select(KnowledgeIngestRunRow)
                .order_by(KnowledgeIngestRunRow.started_at.desc())
                .limit(max(1, min(limit, 100)))
            )
            rows = result.scalars().all()
        return [
            {
                "run_id": row.run_id,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "actor": row.actor,
                "status": row.status,
                "knowledge_source": row.knowledge_source,
                "embedding_model": row.embedding_model,
                "index_version": row.index_version,
                "files_seen": row.files_seen,
                "files_rechunked": row.files_rechunked,
                "files_reused": row.files_reused,
                "files_deleted": row.files_deleted,
                "chunks_indexed": row.chunks_indexed,
                "error_detail": row.error_detail,
            }
            for row in rows
        ]
