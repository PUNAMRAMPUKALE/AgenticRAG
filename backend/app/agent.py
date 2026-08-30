from __future__ import annotations

import os
from dataclasses import dataclass

from app.search import SparseIndex


@dataclass
class AgentDeps:
    index: SparseIndex


def retrieve(index: SparseIndex, query: str, k: int = 4) -> tuple[str, list[dict]]:
    hits = index.search(query, k=k)
    citations = [
        {
            "file_id": chunk.file_id,
            "title": chunk.title,
            "as_of": chunk.as_of,
            "score": round(score, 3),
            "snippet": chunk.text[:280],
        }
        for chunk, score in hits
    ]
    return index.format_for_agent(hits), citations


def extractive_answer(formatted: str, citations: list[dict]) -> str:
    if not citations:
        return "I could not find this in the knowledge base."
    lines = ["Here is what the knowledge base says:", ""]
    for c in citations:
        lines.append(f"**{c['title']}** (`{c['file_id']}`, {c['as_of']})")
        lines.append(c["snippet"])
        lines.append("")
    return "\n".join(lines).strip()


async def generate_answer(user_query: str, index: SparseIndex) -> tuple[str, list[dict], bool]:
    """Returns (answer, citations, used_llm)."""
    formatted, citations = retrieve(index, user_query)
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        return extractive_answer(formatted, citations), citations, False

    from pydantic_ai import Agent, RunContext
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.providers.openai import OpenAIProvider

    model = OpenAIModel(
        os.getenv("LLM_CHOICE") or "gpt-4o-mini",
        provider=OpenAIProvider(
            base_url=os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1",
            api_key=api_key,
        ),
    )
    agent = Agent(
        model,
        system_prompt=(
            "You are a fintech knowledge assistant. Answer only from tool results. "
            "Cite file_id and as-of. If nothing was retrieved, say it is not in the knowledge base. "
            "Lead with the direct answer."
        ),
        deps_type=AgentDeps,
        retries=2,
    )

    @agent.tool
    async def retrieve_relevant_documents(ctx: RunContext[AgentDeps], query: str) -> str:
        """Retrieve relevant document chunks from the Horizon Trust knowledge base."""
        text, _ = retrieve(ctx.deps.index, query)
        return text

    result = await agent.run(user_query, deps=AgentDeps(index=index))
    answer = getattr(result, "output", None) or getattr(result, "data", None) or str(result)
    return str(answer), citations, True
