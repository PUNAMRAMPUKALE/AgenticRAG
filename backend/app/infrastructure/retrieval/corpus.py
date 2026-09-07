from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.infrastructure.retrieval.ingest import ingest_bytes
from app.infrastructure.retrieval.sparse import build_index

log = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf", ".xlsx", ".xlsm", ".jsonl"}


def iter_source_files(knowledge_dir: Path) -> list[Path]:
    if not knowledge_dir.is_dir():
        return []
    files: list[Path] = []
    for path in knowledge_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.name.startswith("~$"):
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    return sorted(files)


def compute_index_version(knowledge_dir: Path = KNOWLEDGE_DIR) -> str:
    h = hashlib.sha256()
    for path in iter_source_files(knowledge_dir):
        rel = path.relative_to(knowledge_dir).as_posix()
        h.update(rel.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


class CorpusKnowledgeLoader:
    def __init__(self, knowledge_dir: Path = KNOWLEDGE_DIR):
        self._dir = knowledge_dir

    @property
    def knowledge_dir(self) -> Path:
        return self._dir

    def fingerprint(self) -> str:
        return compute_index_version(self._dir)

    def load(self):
        chunks = []
        files = iter_source_files(self._dir)
        for path in files:
            rel = path.relative_to(self._dir).as_posix()
            try:
                built = ingest_bytes(rel, path.read_bytes())
            except Exception:
                log.exception("Failed to ingest %s", path)
                continue
            if not built:
                log.warning("No usable chunks from %s", path)
                continue
            chunks.extend(built)
        log.info("Loaded %s chunks from %s files in %s", len(chunks), len(files), self._dir)
        return chunks, build_index(chunks), self.fingerprint()


MarkdownKnowledgeLoader = CorpusKnowledgeLoader
