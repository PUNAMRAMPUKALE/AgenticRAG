from __future__ import annotations

from dataclasses import asdict

from app.domain.models import Chunk


def chunk_record(chunk: Chunk) -> dict:
    """One stored retrieval unit: text + metadata (same fields Vespa will hold)."""
    return asdict(chunk)
