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
    """In-memory ingest timeline for /v1/ingest/status (last 250 events)."""

    def __init__(self) -> None:
        self.live = IngestLive()
        self.events: deque[IngestEvent] = deque(maxlen=250)

    def start(self, trace_id: str, actor: str) -> None:
        self.live = IngestLive(
            active=True,
            trace_id=trace_id,
            actor=actor,
            stage="starting",
            started_at=_now(),
            updated_at=_now(),
        )
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
        )
        self.events.append(event)
        return event

    def snapshot(self) -> dict[str, Any]:
        return {
            "live": asdict(self.live),
            "events": [asdict(e) for e in reversed(self.events)],
        }
