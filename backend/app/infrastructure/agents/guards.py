from __future__ import annotations

import hashlib
import logging
import re
import time

from app.core.metrics import GUARD_EVENTS

log = logging.getLogger(__name__)

SAFE_FALLBACK = (
    "I can only answer from Horizon Trust knowledge-base documents "
    "(policies, operations, treasury). Please ask about those topics "
    "or contact your manager for anything else."
)

INPUT_BLOCK_PATTERNS = {
    "ssn": r"\bssn\b|social\s*security",
    "advice": r"\binvest\b|\bcrypto\b|stock\s*market|should\s+i\s+buy",
    "competitor": r"\bchase\b|wells\s*fargo|\bciti\b|capital\s*one|jpmorgan|goldman",
    "harm": r"\bbomb\b|\bweapon\b|\bexplosi",
}

OUTPUT_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
OUTPUT_COMPETITOR = re.compile(
    r"(?i)\b(chase|wells fargo|citi|capital one|jpmorgan|goldman sachs)\b"
)


def log_guard(guard_type: str, decision: str, reason: str, latency_ms: float, query: str) -> None:
    GUARD_EVENTS.labels(guard_type, decision).inc()
    log.info(
        "guardrail %s %s",
        guard_type,
        decision,
        extra={
            "pipeline": "guard",
            "stage": guard_type,
            "outcome": decision,
            "status": reason,
            "duration_ms": int(latency_ms),
            "source_key": hashlib.sha256((query or "").encode()).hexdigest()[:16],
        },
    )


def input_guard(query: str) -> tuple[str | None, str | None]:
    """Block before any LLM call. Fail-open on errors. Never leak why to the user."""
    started = time.perf_counter()
    try:
        lowered = (query or "").lower()
        for reason, pattern in INPUT_BLOCK_PATTERNS.items():
            if re.search(pattern, lowered):
                log_guard("regex_input", "blocked", reason, (time.perf_counter() - started) * 1000, query)
                return SAFE_FALLBACK, reason
        log_guard("regex_input", "passed", "", (time.perf_counter() - started) * 1000, query)
        return None, None
    except Exception:
        log.exception("input_guard failed; fail-open")
        return None, None


def output_guard(answer: str, query: str) -> str:
    """Fail-closed: unvalidated output is replaced with SAFE_FALLBACK."""
    started = time.perf_counter()
    try:
        text = answer or ""
        if OUTPUT_SSN.search(text):
            log_guard("regex_output", "blocked", "ssn", (time.perf_counter() - started) * 1000, query)
            return SAFE_FALLBACK
        if OUTPUT_COMPETITOR.search(text):
            log_guard("regex_output", "blocked", "competitor", (time.perf_counter() - started) * 1000, query)
            return SAFE_FALLBACK
        log_guard("regex_output", "passed", "", (time.perf_counter() - started) * 1000, query)
        return text
    except Exception:
        log.exception("output_guard failed; fail-closed")
        log_guard("regex_output", "error", "exception", (time.perf_counter() - started) * 1000, query)
        return SAFE_FALLBACK
