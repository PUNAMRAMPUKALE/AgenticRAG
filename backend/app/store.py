from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.models import Conversation, Message

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "conversations.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    def __init__(self, db_path: Path = DEFAULT_DB):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    citations TEXT NOT NULL DEFAULT '[]',
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES conversations(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
                """
            )
            self._conn.commit()

    def create(self, session_id: str, user_id: str, title: str) -> Conversation:
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (session_id, user_id, title, created_at) VALUES (?, ?, ?, ?)",
                (session_id, user_id, title, _now()),
            )
            self._conn.commit()
        return Conversation(session_id=session_id, user_id=user_id, title=title)

    def get(self, session_id: str, user_id: str) -> Conversation | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id, user_id, title FROM conversations WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if not row:
                return None
            msgs = self._conn.execute(
                "SELECT role, content, citations, cache_hit FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        messages = [
            Message(
                role=m["role"],
                content=m["content"],
                citations=json.loads(m["citations"]),
                cache_hit=bool(m["cache_hit"]),
            )
            for m in msgs
        ]
        return Conversation(
            session_id=row["session_id"],
            user_id=row["user_id"],
            title=row["title"],
            messages=messages,
        )

    def list_for_user(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT c.session_id, c.title, COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.session_id = c.session_id
                WHERE c.user_id = ?
                GROUP BY c.session_id, c.title, c.created_at
                ORDER BY c.created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "session_id": r["session_id"],
                "title": r["title"],
                "message_count": r["message_count"],
            }
            for r in rows
        ]

    def add_message(self, session_id: str, message: Message) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO messages (session_id, role, content, citations, cache_hit, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    message.role,
                    message.content,
                    json.dumps(message.citations),
                    1 if message.cache_hit else 0,
                    _now(),
                ),
            )
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM conversations").fetchone()
        return int(row["n"]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
