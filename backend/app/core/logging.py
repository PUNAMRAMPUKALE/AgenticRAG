from __future__ import annotations

import json
import logging
import sys
from collections import deque
from datetime import datetime, timezone

from app.core.ingest_context import ingest_source_key, ingest_trace_id
from app.core.telemetry import current_trace_ids

_LOG_RING: deque[dict] = deque(maxlen=800)


class PipelineContextFilter(logging.Filter):
    """Copy ingest trace/source from contextvars onto every log record in this run."""

    def filter(self, record: logging.LogRecord) -> bool:
        tid = ingest_trace_id.get()
        if tid and not getattr(record, "ingest_trace_id", None):
            record.ingest_trace_id = tid
        if tid and not getattr(record, "pipeline", None):
            record.pipeline = "ingest"
        key = ingest_source_key.get()
        if key and not getattr(record, "source_key", None):
            record.source_key = key
        trace_id, span_id = current_trace_ids()
        if trace_id and not getattr(record, "trace_id", None):
            record.trace_id = trace_id
        if span_id and not getattr(record, "span_id", None):
            record.span_id = span_id
        return True


class JsonLogFormatter(logging.Formatter):
    _PASSTHROUGH = (
        "request_id",
        "method",
        "path",
        "status",
        "duration_ms",
        "pipeline",
        "stage",
        "ingest_trace_id",
        "source_key",
        "outcome",
        "chunks",
        "files_total",
        "files_done",
        "files_failed",
        "files_changed",
        "files_reused",
        "actor",
        "bytes",
        "strategy",
        "suffix",
        "pages",
        "chunk_chars_min",
        "chunk_chars_avg",
        "chunk_chars_max",
        "trace_id",
        "span_id",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in self._PASSTHROUGH:
            value = getattr(record, key, None)
            if value is not None and value != "":
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class MemoryLogHandler(logging.Handler):
    """Keep recent JSON log records for the Observability UI."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.loads(self.format(record))
        except Exception:
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
        _LOG_RING.append(payload)


def recent_logs(limit: int = 400) -> list[dict]:
    rows = list(_LOG_RING)
    return list(reversed(rows))[: max(1, min(limit, 800))]


def configure_logging() -> None:
    formatter = JsonLogFormatter()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(PipelineContextFilter())
    memory = MemoryLogHandler()
    memory.setFormatter(formatter)
    memory.addFilter(PipelineContextFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(stream)
    root.addHandler(memory)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
