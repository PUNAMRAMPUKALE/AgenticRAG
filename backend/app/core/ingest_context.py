from __future__ import annotations

from contextvars import ContextVar

ingest_trace_id: ContextVar[str] = ContextVar("ingest_trace_id", default="")
ingest_source_key: ContextVar[str] = ContextVar("ingest_source_key", default="")
