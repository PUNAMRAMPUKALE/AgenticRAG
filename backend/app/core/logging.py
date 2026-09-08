from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.ingest_context import ingest_source_key, ingest_trace_id


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


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(PipelineContextFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
