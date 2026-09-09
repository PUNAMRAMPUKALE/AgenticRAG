from __future__ import annotations

import os

from app.core.metrics import LLM_COST, LLM_TOKENS

# GPT-4o-mini list prices from Week 8 slides ($ / 1M tokens).
_INPUT_PER_M = 0.15
_OUTPUT_PER_M = 0.60


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    raw = text or ""
    try:
        import tiktoken

        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(raw))
    except Exception:
        return max(1, len(raw) // 4)


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens * _INPUT_PER_M + completion_tokens * _OUTPUT_PER_M) / 1_000_000


def record_usage(*, intent: str, prompt_tokens: int, completion_tokens: int, cost: float, llm_calls: int) -> None:
    LLM_TOKENS.labels("prompt", intent).inc(prompt_tokens)
    LLM_TOKENS.labels("completion", intent).inc(completion_tokens)
    LLM_COST.labels(intent).inc(cost)


def chat_model_name() -> str:
    return os.getenv("LLM_CHOICE") or "gpt-4o-mini"
