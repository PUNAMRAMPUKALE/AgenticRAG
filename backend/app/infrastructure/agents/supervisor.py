from __future__ import annotations

import os
import re

INTENTS = ("policy", "operations", "treasury", "escalation")

_ESCALATION = re.compile(
    r"(?i)\b(furious|angry|complaint|lawsuit|sue|manager|human|escalate|ssn|password|wire me)\b"
)
_TREASURY = re.compile(r"(?i)\b(liquidity|treasury|capital ratio|lcr|nsfr)\b")
_OPERATIONS = re.compile(r"(?i)\b(sop|payment operations|runbook|wire transfer|ops )\b")
_POLICY = re.compile(r"(?i)\b(kyc|onboarding|compliance|aml|policy|procedure)\b")

_SYSTEM = (
    "Classify the Horizon Trust knowledge question into exactly one category:\n"
    '- "policy" — KYC, compliance, onboarding, procedures\n'
    '- "operations" — payment SOP, runbooks, operations\n'
    '- "treasury" — liquidity, capital, treasury risk reports\n'
    '- "escalation" — complaints, legal threats, SSN, requests for a human\n'
    "Respond with ONLY the category name."
)


def keyword_intent(query: str) -> str:
    """Deterministic supervisor fallback (zero LLM cost). Unrecognised → policy."""
    text = query or ""
    if _ESCALATION.search(text):
        return "escalation"
    if _TREASURY.search(text):
        return "treasury"
    if _OPERATIONS.search(text):
        return "operations"
    if _POLICY.search(text):
        return "policy"
    return "policy"


async def classify_intent(query: str) -> tuple[str, int, int, int]:
    """Returns intent, llm_calls, prompt_tokens, completion_tokens."""
    fallback = keyword_intent(query)
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        return fallback, 0, 0, 0
    from app.infrastructure.agents.cost import chat_model_name, count_tokens

    prompt_tokens = count_tokens(_SYSTEM + "\n" + query)
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=os.getenv("LLM_BASE_URL") or None)
        try:
            from langsmith.wrappers import wrap_openai

            client = wrap_openai(client)
        except Exception:
            pass
        response = client.chat.completions.create(
            model=chat_model_name(),
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": query},
            ],
            max_tokens=8,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip().lower().strip('"')
        intent = raw if raw in INTENTS else fallback
        completion = count_tokens(raw)
        return intent, 1, prompt_tokens, completion
    except Exception:
        return fallback, 0, prompt_tokens, 0
