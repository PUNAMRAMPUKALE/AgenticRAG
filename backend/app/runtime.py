from __future__ import annotations

from dataclasses import dataclass, field

from app.cache import AnswerCache
from app.core.security import TokenVerifier
from app.search import SparseIndex
from app.store import ConversationStore


@dataclass
class Runtime:
    store: ConversationStore
    cache: AnswerCache
    verifier: TokenVerifier
    chunks: list = field(default_factory=list)
    index: SparseIndex | None = None
    index_version: str = ""
