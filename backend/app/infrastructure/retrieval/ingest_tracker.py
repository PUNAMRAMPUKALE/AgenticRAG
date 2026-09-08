from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class IngestEvent:
    ts: str
    trace_id: str
    stage: str
    status: str
    source_key: str = ""
    detail: str = ""
    chunks: int = 0
    duration_ms: int = 0
    files_done: int = 0
    files_total: int = 0
    strategy: str = ""
    suffix: str = ""
    pages: int = 0
    chunk_chars_min: int = 0
    chunk_chars_avg: int = 0
    chunk_chars_max: int = 0


@dataclass
class IngestLive:
    active: bool = False
    trace_id: str = ""
    actor: str = ""
    stage: str = "idle"
    source_key: str = ""
    files_total: int = 0
    files_changed: int = 0
    files_reused: int = 0
    files_done: int = 0
    files_failed: int = 0
    last_error: str = ""
    started_at: str = ""
    updated_at: str = ""


class IngestTracker:
    """In-memory ingest timeline for the Observability UI (last 2000 events)."""

    def __init__(self) -> None:
        self.live = IngestLive()
        self.events: deque[IngestEvent] = deque(maxlen=2000)
        self.traces: deque[str] = deque(maxlen=50)

    def start(self, trace_id: str, actor: str) -> None:
        self.live = IngestLive(
            active=True,
            trace_id=trace_id,
            actor=actor,
            stage="starting",
            started_at=_now(),
            updated_at=_now(),
        )
        if trace_id:
            self.traces.appendleft(trace_id)
        self._push("run_start", "ok", detail=f"actor={actor}")

    def finish(self, *, ok: bool, detail: str = "") -> None:
        self.live.active = False
        self.live.stage = "succeeded" if ok else "failed"
        self.live.updated_at = _now()
        if detail:
            self.live.last_error = detail if not ok else self.live.last_error
        self._push("run_end", "ok" if ok else "error", detail=detail)

    def emit(
        self,
        stage: str,
        *,
        status: str = "ok",
        source_key: str = "",
        detail: str = "",
        chunks: int = 0,
        duration_ms: int = 0,
        files_done: int | None = None,
        files_total: int | None = None,
        files_changed: int | None = None,
        files_reused: int | None = None,
        files_failed: int | None = None,
        strategy: str = "",
        suffix: str = "",
        pages: int = 0,
        chunk_chars_min: int = 0,
        chunk_chars_avg: int = 0,
        chunk_chars_max: int = 0,
    ) -> IngestEvent:
        if files_total is not None:
            self.live.files_total = files_total
        if files_changed is not None:
            self.live.files_changed = files_changed
        if files_reused is not None:
            self.live.files_reused = files_reused
        if files_done is not None:
            self.live.files_done = files_done
        if files_failed is not None:
            self.live.files_failed = files_failed
        self.live.stage = stage
        if source_key:
            self.live.source_key = source_key
        self.live.updated_at = _now()
        if status == "error" and detail:
            self.live.last_error = detail[:2000]
        return self._push(
            stage,
            status,
            source_key=source_key,
            detail=detail[:2000],
            chunks=chunks,
            duration_ms=duration_ms,
            strategy=strategy,
            suffix=suffix,
            pages=pages,
            chunk_chars_min=chunk_chars_min,
            chunk_chars_avg=chunk_chars_avg,
            chunk_chars_max=chunk_chars_max,
        )

    def _push(self, stage: str, status: str, **kwargs: Any) -> IngestEvent:
        event = IngestEvent(
            ts=_now(),
            trace_id=self.live.trace_id,
            stage=stage,
            status=status,
            source_key=str(kwargs.get("source_key") or ""),
            detail=str(kwargs.get("detail") or ""),
            chunks=int(kwargs.get("chunks") or 0),
            duration_ms=int(kwargs.get("duration_ms") or 0),
            files_done=self.live.files_done,
            files_total=self.live.files_changed or self.live.files_total,
            strategy=str(kwargs.get("strategy") or ""),
            suffix=str(kwargs.get("suffix") or ""),
            pages=int(kwargs.get("pages") or 0),
            chunk_chars_min=int(kwargs.get("chunk_chars_min") or 0),
            chunk_chars_avg=int(kwargs.get("chunk_chars_avg") or 0),
            chunk_chars_max=int(kwargs.get("chunk_chars_max") or 0),
        )
        self.events.append(event)
        return event

    def documents(self) -> list[dict[str, Any]]:
        by_key: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for event in self.events:
            if not event.source_key:
                continue
            if event.source_key not in by_key:
                order.append(event.source_key)
                by_key[event.source_key] = []
            by_key[event.source_key].append(asdict(event))
        docs: list[dict[str, Any]] = []
        for key in reversed(order):
            evs = by_key[key]
            chunk_ev = next((x for x in reversed(evs) if x["stage"] == "chunk_ok"), None)
            last = evs[-1]
            docs.append(
                {
                    "source_key": key,
                    "trace_id": last.get("trace_id") or "",
                    "stage": last["stage"],
                    "status": last["status"],
                    "strategy": (chunk_ev or last).get("strategy") or "",
                    "suffix": (chunk_ev or last).get("suffix") or "",
                    "chunks": (chunk_ev or last).get("chunks") or 0,
                    "pages": (chunk_ev or last).get("pages") or 0,
                    "duration_ms": last.get("duration_ms") or 0,
                    "chunk_chars_min": (chunk_ev or {}).get("chunk_chars_min") or 0,
                    "chunk_chars_avg": (chunk_ev or {}).get("chunk_chars_avg") or 0,
                    "chunk_chars_max": (chunk_ev or {}).get("chunk_chars_max") or 0,
                    "events": list(reversed(evs)),
                }
            )
        return docs

    def snapshot(self) -> dict[str, Any]:
        events = [asdict(e) for e in reversed(self.events)]
        return {
            "live": asdict(self.live),
            "events": events,
            "documents": self.documents(),
            "errors": [e for e in events if e.get("status") == "error"],
            "trace_ids": list(self.traces),
        }
