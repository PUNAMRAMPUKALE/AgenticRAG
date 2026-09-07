from __future__ import annotations

import hashlib
from pathlib import Path

from app.domain.models import Chunk
from app.infrastructure.retrieval.sparse import SparseIndex

KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"


def _as_of_from_text(text: str) -> str:
    for line in text.splitlines():
        if "as of" in line.lower() or "effective as of" in line.lower():
            return line.strip()[:80]
    return "unknown"


def compute_index_version(knowledge_dir: Path = KNOWLEDGE_DIR) -> str:
    h = hashlib.sha256()
    for path in sorted(knowledge_dir.glob("*.md")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


class MarkdownKnowledgeLoader:
    def __init__(self, knowledge_dir: Path = KNOWLEDGE_DIR):
        self._dir = knowledge_dir

    def load(self) -> tuple[list[Chunk], SparseIndex, str]:
        chunks: list[Chunk] = []
        for path in sorted(self._dir.glob("*.md")):
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
        return chunks, SparseIndex(chunks), compute_index_version(self._dir)
