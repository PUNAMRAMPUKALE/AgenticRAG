from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.application.knowledge_service import KnowledgeService
from app.infrastructure.retrieval.corpus import SUPPORTED_SUFFIXES

log = logging.getLogger(__name__)


def _is_knowledge_file(path: str) -> bool:
    name = Path(path).name
    if name.startswith(".") or name.startswith("~$"):
        return False
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


class _KnowledgeEventHandler(FileSystemEventHandler):
    def __init__(self, on_change) -> None:
        self._on_change = on_change

    def on_any_event(self, event: FileSystemEvent) -> None:
        src = str(getattr(event, "src_path", "") or "")
        dest = str(getattr(event, "dest_path", "") or "")
        if event.is_directory:
            if event.event_type in {"deleted", "moved", "created"}:
                self._on_change()
            return
        if _is_knowledge_file(src) or _is_knowledge_file(dest):
            self._on_change()


class KnowledgeIngestWatcher:
    """Rebuild chunks + search index when knowledge files are added, changed, or removed."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        knowledge_dir: Path,
        debounce_seconds: float,
        poll_seconds: float,
    ) -> None:
        self._knowledge = knowledge
        self._dir = knowledge_dir
        self._debounce = debounce_seconds
        self._poll = poll_seconds
        self._observer: Observer | None = None
        self._debounce_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._loop = loop
        handler = _KnowledgeEventHandler(self._notify)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._dir), recursive=True)
        self._observer.start()
        self._poll_task = loop.create_task(self._poll_loop(), name="knowledge-ingest-poll")
        log.info("Watching knowledge dir %s (debounce %.2fs, poll %.1fs)", self._dir, self._debounce, self._poll)

    def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._debounce_task is not None:
            self._debounce_task.cancel()
            self._debounce_task = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None

    def _notify(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._schedule_debounce)

    def _schedule_debounce(self) -> None:
        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._run_after_debounce())

    async def _run_after_debounce(self) -> None:
        try:
            await asyncio.sleep(self._debounce)
            await self._knowledge.reindex_if_changed("ingest-pipeline")
        except asyncio.CancelledError:
            return

    async def _poll_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._poll)
                await self._knowledge.reindex_if_changed("ingest-pipeline")
        except asyncio.CancelledError:
            return
