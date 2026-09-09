from __future__ import annotations

import json
import os

from app.infrastructure.agents.cost import chat_model_name, count_tokens

_CRITIC = (
    "Score whether the answer is faithful to CONTEXT. "
    "Score 1.0 = every claim is in context; 0.5 = partial; 0.0 = hallucinated. "
    'Respond ONLY JSON: {"score": <float>, "reason": "...", "rewrite_needed": <bool>}'
)


async def critique(answer: str, context: str) -> tuple[float, str, bool, int, int]:
    """LLM-as-judge faithfulness. Returns score, reason, rewrite_needed, prompt_tokens, completion_tokens."""
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key or not (answer or "").strip():
        return 1.0, "skipped", False, 0, 0
    payload = f"CONTEXT:\n{(context or '')[:4000]}\n\nANSWER:\n{(answer or '')[:2000]}"
    prompt_tokens = count_tokens(_CRITIC + payload)
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
                {"role": "system", "content": _CRITIC},
                {"role": "user", "content": payload},
            ],
            max_tokens=120,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        parsed = json.loads(raw[start : end + 1]) if start >= 0 and end > start else {}
        score = float(parsed.get("score", 0.5))
        reason = str(parsed.get("reason") or "")[:300]
        rewrite = bool(parsed.get("rewrite_needed")) or score < 0.7
        return score, reason, rewrite, prompt_tokens, count_tokens(raw)
    except Exception:
        return 0.5, "judge_failed", False, prompt_tokens, 0
