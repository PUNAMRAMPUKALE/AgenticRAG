from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from app.domain.ports import SearchIndex


@dataclass
class AgentDeps:
    index: SearchIndex


def retrieve(index: SearchIndex, query: str, k: int = 4) -> tuple[str, list[dict]]:
    hits = index.search(query, k=k)
    citations = [
        {
            "file_id": chunk.file_id,
            "title": chunk.title,
            "as_of": chunk.as_of,
            "section": chunk.section,
            "page": chunk.page,
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


class KnowledgeAssistant:
    async def generate(self, query: str, index: SearchIndex) -> tuple[str, list[dict], bool]:
        formatted, citations = await asyncio.to_thread(retrieve, index, query)
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
        async def retrieve_relevant_documents(ctx: RunContext[AgentDeps], q: str) -> str:
            """Retrieve relevant document chunks from the Horizon Trust knowledge base."""
            text, _ = await asyncio.to_thread(retrieve, ctx.deps.index, q)
            return text

        result = await agent.run(query, deps=AgentDeps(index=index))
        answer = getattr(result, "output", None) or getattr(result, "data", None) or str(result)
        return str(answer), citations, True
