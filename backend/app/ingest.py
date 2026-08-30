from __future__ import annotations

from pathlib import Path

from app.models import Chunk
from app.search import SparseIndex

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


def _as_of_from_text(text: str) -> str:
    for line in text.splitlines():
        if "as of" in line.lower() or "effective as of" in line.lower():
            return line.strip()[:80]
    return "unknown"


def ingest_knowledge() -> tuple[list[Chunk], SparseIndex]:
    chunks: list[Chunk] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        file_id = path.stem
        title = text.splitlines()[0].lstrip("# ").strip() if text else file_id
        as_of = _as_of_from_text(text)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        for i, para in enumerate(paragraphs):
            chunks.append(
                Chunk(
                    chunk_id=f"{file_id}:{i}",
                    file_id=file_id,
                    title=title,
                    text=para,
                    as_of=as_of,
                )
            )
    index = SparseIndex(chunks)
    return chunks, index
