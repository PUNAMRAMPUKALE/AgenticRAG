from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chunk:
    chunk_id: str
    file_id: str
    title: str
    text: str
    as_of: str
    section: str = ""
    page: str = ""
    doc_type: str = ""
    strategy: str = ""


@dataclass
class Message:
    role: str
    content: str
    citations: list[dict] = field(default_factory=list)
    cache_hit: bool = False


@dataclass
class Conversation:
    session_id: str
    user_id: str
    messages: list[Message] = field(default_factory=list)
    title: str = "New conversation"


@dataclass(frozen=True)
class ConversationSummary:
    session_id: str
    title: str
    message_count: int
