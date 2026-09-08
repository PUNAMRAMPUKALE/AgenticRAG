from __future__ import annotations

from contextvars import ContextVar
from typing import Any

ingest_trace_id: ContextVar[str] = ContextVar("ingest_trace_id", default="")
ingest_source_key: ContextVar[str] = ContextVar("ingest_source_key", default="")
ingest_tracker: ContextVar[Any] = ContextVar("ingest_tracker", default=None)
