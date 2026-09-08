from __future__ import annotations

from app.domain.models import Chunk


def format_hits(hits: list[tuple[Chunk, float]]) -> str:
    if not hits:
        return "No relevant documents found."
    parts = []
    for chunk, score in hits:
        parts.append(
            f"# Document ID: {chunk.file_id}\n"
            f"# Title: {chunk.title}\n"
            f"# As-of: {chunk.as_of}\n"
            f"# Section: {chunk.section or '-'}\n"
            f"# Page: {chunk.page or '-'}\n"
            f"# Score: {score:.3f}\n\n{chunk.text}"
        )
    return "\n\n---\n\n".join(parts)
