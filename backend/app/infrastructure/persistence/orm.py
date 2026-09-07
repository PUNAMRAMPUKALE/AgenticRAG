from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    __tablename__ = "conversations"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    messages: Mapped[list["MessageRow"]] = relationship(back_populates="conversation")


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.session_id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")


class KnowledgeSourceRow(Base):
    """One knowledge file. etag/stamp changes ⇒ re-chunk only this file."""

    __tablename__ = "knowledge_sources"

    source_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    etag: Mapped[str] = mapped_column(String(128))
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    chunks: Mapped[list["KnowledgeChunkRow"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class KnowledgeChunkRow(Base):
    """Persisted chunk text + embedding. Survives API restart."""

    __tablename__ = "knowledge_chunks"

    chunk_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    source_key: Mapped[str] = mapped_column(
        String(512), ForeignKey("knowledge_sources.source_key", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str] = mapped_column(String(512), index=True)
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    as_of: Mapped[str] = mapped_column(String(80), default="")
    section: Mapped[str] = mapped_column(String(200), default="")
    page: Mapped[str] = mapped_column(String(32), default="")
    doc_type: Mapped[str] = mapped_column(String(32), default="")
    strategy: Mapped[str] = mapped_column(String(64), default="")
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    source: Mapped[KnowledgeSourceRow] = relationship(back_populates="chunks")
