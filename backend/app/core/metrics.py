from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "agenticrag_http_requests_total",
    "HTTP requests",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "agenticrag_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
INGEST_FILES = Counter(
    "agenticrag_ingest_files_total",
    "Ingest file outcomes",
    ["outcome"],
)
INGEST_CHUNKS = Counter("agenticrag_ingest_chunks_total", "Chunks written to Vespa")
CHAT_REQUESTS = Counter(
    "agenticrag_chat_requests_total",
    "Chat asks",
    ["result"],
)
VESPA_SEARCH = Histogram(
    "agenticrag_vespa_search_duration_seconds",
    "Vespa hybrid search latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
VESPA_CHUNKS = Gauge("agenticrag_vespa_chunks", "Chunks currently in Vespa")
EVAL_RUNS = Counter("agenticrag_eval_runs_total", "Gold eval suite runs", ["result"])
EVAL_CASES = Counter("agenticrag_eval_cases_total", "Gold eval cases", ["result"])
GUARD_EVENTS = Counter("agenticrag_guard_events_total", "Guardrail decisions", ["guard_type", "decision"])
LLM_TOKENS = Counter("agenticrag_llm_tokens_total", "Estimated LLM tokens", ["direction", "intent"])
LLM_COST = Counter("agenticrag_llm_cost_usd_total", "Estimated LLM USD", ["intent"])


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
