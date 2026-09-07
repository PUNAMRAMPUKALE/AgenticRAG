from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
