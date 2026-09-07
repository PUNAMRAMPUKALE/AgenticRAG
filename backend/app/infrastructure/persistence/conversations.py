from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.domain.models import Conversation, ConversationSummary, Message
from app.infrastructure.persistence.orm import Base, ConversationRow, MessageRow


class PostgresConversationRepository:
    def __init__(self, settings: Settings):
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def init_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(select(1))
            return True
        except Exception:
            return False

    async def create(self, session_id: str, user_id: str, title: str) -> None:
        async with self._sessions() as db:
            db.add(ConversationRow(session_id=session_id, user_id=user_id, title=title[:200]))
            await db.commit()

    async def get(self, session_id: str, user_id: str) -> Conversation | None:
        async with self._sessions() as db:
            row = await db.get(ConversationRow, session_id)
            if not row or row.user_id != user_id:
                return None
            result = await db.execute(
                select(MessageRow).where(MessageRow.session_id == session_id).order_by(MessageRow.id)
            )
            msgs = result.scalars().all()
            return Conversation(
                session_id=row.session_id,
                user_id=row.user_id,
                title=row.title,
                messages=[
                    Message(
                        role=m.role,
                        content=m.content,
                        citations=list(m.citations or []),
                        cache_hit=m.cache_hit,
                    )
                    for m in msgs
                ],
            )

    async def list_for_user(self, user_id: str) -> list[ConversationSummary]:
        async with self._sessions() as db:
            count_col = func.count(MessageRow.id)
            result = await db.execute(
                select(ConversationRow.session_id, ConversationRow.title, count_col)
                .outerjoin(MessageRow, MessageRow.session_id == ConversationRow.session_id)
                .where(ConversationRow.user_id == user_id)
                .group_by(ConversationRow.session_id, ConversationRow.title, ConversationRow.created_at)
                .order_by(ConversationRow.created_at.desc())
            )
            return [
                ConversationSummary(session_id=sid, title=title, message_count=int(n))
                for sid, title, n in result.all()
            ]

    async def add_message(self, session_id: str, message: Message) -> None:
        async with self._sessions() as db:
            db.add(
                MessageRow(
                    session_id=session_id,
                    role=message.role,
                    content=message.content,
                    citations=message.citations,
                    cache_hit=message.cache_hit,
                )
            )
            await db.commit()

    async def count(self) -> int:
        async with self._sessions() as db:
            n = await db.scalar(select(func.count()).select_from(ConversationRow))
            return int(n or 0)

    async def close(self) -> None:
        await self.engine.dispose()
