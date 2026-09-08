from __future__ import annotations

import hashlib
from pathlib import Path

from app.infrastructure.retrieval.incremental import stamp_fingerprint

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
        return stamp_fingerprint(self.list_stamps())

    def list_stamps(self) -> dict[str, str]:
        stamps: dict[str, str] = {}
        for path in iter_source_files(self._dir):
            rel = path.relative_to(self._dir).as_posix()
            st = path.stat()
            stamps[rel] = f"{st.st_mtime_ns}:{st.st_size}"
        return stamps

    def read_bytes(self, source_key: str) -> bytes:
        path = (self._dir / source_key).resolve()
        if not str(path).startswith(str(self._dir.resolve())):
            raise ValueError("Invalid knowledge path")
        return path.read_bytes()


MarkdownKnowledgeLoader = CorpusKnowledgeLoader
