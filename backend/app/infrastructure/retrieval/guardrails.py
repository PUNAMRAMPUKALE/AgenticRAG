from __future__ import annotations

from dataclasses import dataclass, replace
import re
import unicodedata

from app.core.errors import EmptyQuery, QueryRejected
from app.domain.models import Chunk

MAX_QUERY_CHARS = 1000
MIN_SIGNAL_CHARS = 3
MAX_HITS = 6
MAX_K = 8
MIN_HIT_SCORE = 0.02
MAX_CHUNK_CHARS = 1200
MAX_SNIPPET_CHARS = 280

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_YQL_INJECTION = re.compile(
    r"(?i)(select\s+\*\s+from\s+knowledge_|knowledge_chunk\s+where|"
    r"\bnearestneighbor\s*\(|\buserquery\s*\(|input\.query\s*\()"
)
_ONLY_PUNCT = re.compile(r"^[\W_]+$", re.UNICODE)


@dataclass(frozen=True)
class GuardedQuery:
    text: str
    k: int


def sanitize_query(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "")
    text = _CONTROL.sub(" ", text)
    text = " ".join(text.split())
    if len(text) > MAX_QUERY_CHARS:
        text = text[:MAX_QUERY_CHARS].rsplit(" ", 1)[0] or text[:MAX_QUERY_CHARS]
    return text.strip()


def guard_query(raw: str, k: int = 4) -> GuardedQuery:
    text = sanitize_query(raw)
    if not text:
        raise EmptyQuery()
    signal = sum(1 for ch in text if ch.isalnum())
    if signal < MIN_SIGNAL_CHARS or _ONLY_PUNCT.match(text):
        raise QueryRejected("Query is too short or has no searchable terms")
    if _YQL_INJECTION.search(text):
        raise QueryRejected("Query looks like an index injection attempt")
    bounded_k = max(1, min(int(k), MAX_K))
    return GuardedQuery(text=text, k=bounded_k)


def guard_hits(hits: list[tuple[Chunk, float]], *, k: int = MAX_HITS) -> list[tuple[Chunk, float]]:
    cleaned: list[tuple[Chunk, float]] = []
    for chunk, score in hits:
        if not chunk.text.strip() or not chunk.file_id.strip():
            continue
        if score < MIN_HIT_SCORE:
            continue
        trimmed = chunk.text.strip()
        if len(trimmed) > MAX_CHUNK_CHARS:
            trimmed = trimmed[:MAX_CHUNK_CHARS].rsplit(" ", 1)[0] or trimmed[:MAX_CHUNK_CHARS]
        cleaned.append((replace(chunk, text=trimmed), float(score)))
    cleaned.sort(key=lambda item: item[1], reverse=True)
    return cleaned[: max(1, min(k, MAX_HITS))]


def citation_snippet(text: str) -> str:
    snippet = " ".join((text or "").split())
    if len(snippet) <= MAX_SNIPPET_CHARS:
        return snippet
    return snippet[:MAX_SNIPPET_CHARS].rsplit(" ", 1)[0] or snippet[:MAX_SNIPPET_CHARS]
