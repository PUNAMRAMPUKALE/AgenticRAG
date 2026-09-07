from __future__ import annotations

import logging

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.models import Chunk
from app.infrastructure.persistence.orm import KnowledgeChunkRow, KnowledgeSourceRow

log = logging.getLogger(__name__)


class PostgresVectorStore:
    """Durable chunk text + embeddings. API restart loads this instead of re-chunking S3."""

    def __init__(self, engine: AsyncEngine):
        self._sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def stamps(self) -> dict[str, str]:
        async with self._sessions() as db:
            rows = (await db.execute(select(KnowledgeSourceRow.source_key, KnowledgeSourceRow.etag))).all()
        return {key: etag for key, etag in rows}

    async def stored_embedding_model(self) -> str:
        async with self._sessions() as db:
            value = await db.scalar(select(KnowledgeSourceRow.embedding_model).limit(1))
        return (value or "").strip()

    async def clear_all(self) -> None:
        async with self._sessions() as db:
            await db.execute(delete(KnowledgeChunkRow))
            await db.execute(delete(KnowledgeSourceRow))
            await db.commit()
        log.info("Cleared persisted knowledge vectors (embedding model changed or full reset)")

    async def delete_sources(self, source_keys: list[str]) -> None:
        if not source_keys:
            return
        async with self._sessions() as db:
            await db.execute(delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_key.in_(source_keys)))
            await db.commit()

    async def replace_source(
        self,
        source_key: str,
        etag: str,
        embedding_model: str,
        chunks: list[Chunk],
        vectors: np.ndarray,
    ) -> None:
        async with self._sessions() as db:
            await db.execute(delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_key == source_key))
            await db.flush()
            db.add(KnowledgeSourceRow(source_key=source_key, etag=etag, embedding_model=embedding_model))
            for i, chunk in enumerate(chunks):
                embedding = None
                if vectors.size and i < vectors.shape[0]:
                    embedding = [float(x) for x in vectors[i].tolist()]
                db.add(
                    KnowledgeChunkRow(
                        chunk_id=chunk.chunk_id,
                        source_key=source_key,
                        file_id=chunk.file_id,
                        title=chunk.title[:200],
                        text=chunk.text,
                        as_of=chunk.as_of[:80],
                        section=(chunk.section or "")[:200],
                        page=(chunk.page or "")[:32],
                        doc_type=(chunk.doc_type or "")[:32],
                        strategy=(chunk.strategy or "")[:64],
                        embedding=embedding,
                    )
                )
            await db.commit()

    async def load_all(self) -> tuple[list[Chunk], np.ndarray | None]:
        async with self._sessions() as db:
            rows = (
                await db.execute(select(KnowledgeChunkRow).order_by(KnowledgeChunkRow.source_key, KnowledgeChunkRow.chunk_id))
            ).scalars().all()
        chunks: list[Chunk] = []
        vectors: list[list[float]] = []
        missing = False
        for row in rows:
            chunks.append(
                Chunk(
                    chunk_id=row.chunk_id,
                    file_id=row.file_id,
                    title=row.title,
                    text=row.text,
                    as_of=row.as_of,
                    section=row.section or "",
                    page=row.page or "",
                    doc_type=row.doc_type or "",
                    strategy=row.strategy or "",
                )
            )
            if row.embedding:
                vectors.append(list(row.embedding))
            else:
                missing = True
        if not chunks or missing or len(vectors) != len(chunks):
            return chunks, None
        return chunks, np.asarray(vectors, dtype=np.float32)
