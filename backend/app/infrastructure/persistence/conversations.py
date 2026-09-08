from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.models import Conversation, ConversationSummary, Message
from app.infrastructure.persistence.migrate import run_alembic_upgrade
from app.infrastructure.persistence.orm import (
    ConversationRow,
    MessageRow,
    QueryRequestRow,
    UserProfileRow,
)
from app.infrastructure.persistence.rls import apply_rls, apply_row_context


class PostgresConversationRepository:
    def __init__(self, settings: Settings):
        self._settings = settings
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self._schema_ready = asyncio.Event()
        if not settings.migrate_on_boot:
            self._schema_ready.set()

        @event.listens_for(self.engine.sync_engine, "checkout")
        def _reset_role(dbapi_connection, connection_record, connection_proxy) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("RESET ROLE")
            finally:
                cursor.close()

    async def init_schema(self) -> None:
        return

    async def migrate(self) -> None:
        if not self._settings.migrate_on_boot:
            self._schema_ready.set()
            return
        admin = self._settings.database_admin_url.strip() or self._settings.database_url
        await asyncio.to_thread(run_alembic_upgrade, admin)
        if admin == self._settings.database_url:
            async with self.engine.begin() as conn:
                await apply_rls(conn)
            self._schema_ready.set()
            return
        from sqlalchemy.ext.asyncio import create_async_engine

        admin_engine = create_async_engine(admin)
        try:
            async with admin_engine.begin() as conn:
                await apply_rls(conn)
        finally:
            await admin_engine.dispose()
        self._schema_ready.set()


    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(select(1))
            return True
        except Exception:
            return False

    async def _wait_schema(self) -> None:
        if self._schema_ready.is_set():
            return
        try:
            await asyncio.wait_for(self._schema_ready.wait(), timeout=30)
        except TimeoutError as exc:
            raise AppError(
                503,
                "Postgres is still applying the chat schema. Try sign-in again in a few seconds.",
            ) from exc

    @asynccontextmanager
    async def _ctx(self, user_id: str, is_manager: bool, *, service: bool = False):
        await self._wait_schema()
        async with self._sessions() as db:
            try:
                await apply_row_context(db, user_id=user_id, is_manager=is_manager, service=service)
            except SQLAlchemyError as exc:
                raise AppError(
                    503,
                    "Postgres row security is not ready. The API can serve login config, but sign-in waits on schema.",
                ) from exc
            yield db
            await db.commit()

    async def upsert_profile(self, user_id: str, email: str, full_name: str, *, is_manager: bool) -> None:
        async with self._ctx(user_id, is_manager, service=True) as db:
            row = await db.get(UserProfileRow, user_id)
            if row is None:
                db.add(
                    UserProfileRow(
                        id=user_id,
                        email=email or user_id,
                        full_name=full_name or None,
                        is_manager=is_manager,
                    )
                )
                return
            row.email = email or row.email
            row.full_name = full_name or row.full_name
            row.is_manager = is_manager
            row.updated_at = datetime.now(timezone.utc)

    async def log_request(
        self, user_id: str, user_query: str, session_id: str | None, *, is_manager: bool = False
    ) -> None:
        async with self._ctx(user_id, is_manager) as db:
            db.add(
                QueryRequestRow(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    session_id=session_id,
                    user_query=user_query,
                )
            )

    async def create(self, session_id: str, user_id: str, title: str, *, is_manager: bool = False) -> None:
        now = datetime.now(timezone.utc)
        async with self._ctx(user_id, is_manager) as db:
            db.add(
                ConversationRow(
                    session_id=session_id,
                    user_id=user_id,
                    title=title[:200],
                    last_message_at=now,
                )
            )

    async def get(self, session_id: str, user_id: str, *, is_manager: bool = False) -> Conversation | None:
        async with self._ctx(user_id, is_manager) as db:
            row = await db.get(ConversationRow, session_id)
            if not row or (row.user_id != user_id and not is_manager):
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

    async def list_for_user(self, user_id: str, *, is_manager: bool = False) -> list[ConversationSummary]:
        async with self._ctx(user_id, is_manager) as db:
            count_col = func.count(MessageRow.id)
            q = (
                select(ConversationRow.session_id, ConversationRow.title, count_col)
                .outerjoin(MessageRow, MessageRow.session_id == ConversationRow.session_id)
                .group_by(ConversationRow.session_id, ConversationRow.title, ConversationRow.created_at)
                .order_by(ConversationRow.created_at.desc())
            )
            if not is_manager:
                q = q.where(ConversationRow.user_id == user_id)
            result = await db.execute(q)
            return [
                ConversationSummary(session_id=sid, title=title, message_count=int(n))
                for sid, title, n in result.all()
            ]

    async def add_message(
        self, session_id: str, message: Message, *, user_id: str, is_manager: bool = False
    ) -> None:
        async with self._ctx(user_id, is_manager) as db:
            db.add(
                MessageRow(
                    session_id=session_id,
                    role=message.role,
                    content=message.content,
                    citations=message.citations,
                    cache_hit=message.cache_hit,
                )
            )
            conv = await db.get(ConversationRow, session_id)
            if conv is not None:
                conv.last_message_at = datetime.now(timezone.utc)

    async def count(self) -> int:
        try:
            async with self.engine.connect() as conn:
                n = await conn.scalar(select(func.count()).select_from(ConversationRow))
            return int(n or 0)
        except SQLAlchemyError:
            return 0

    async def close(self) -> None:
        await self.engine.dispose()
