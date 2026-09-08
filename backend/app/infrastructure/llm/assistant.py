from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from app.core.errors import EmptyQuery, QueryRejected
from app.domain.ports import SearchIndex
from app.infrastructure.retrieval.guardrails import citation_snippet, guard_query

log = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    index: SearchIndex


def retrieve(index: SearchIndex, query: str, k: int = 4) -> tuple[str, list[dict]]:
    guarded = guard_query(query, k=k)
    hits = index.search(guarded.text, k=guarded.k)
    citations = [
        {
            "file_id": chunk.file_id,
            "title": chunk.title,
            "as_of": chunk.as_of,
            "section": chunk.section,
            "page": chunk.page,
            "score": round(float(score), 3),
            "snippet": citation_snippet(chunk.text),
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
        try:
            answer = await self._run_llm(query, index, api_key)
        except Exception:
            log.exception("LLM generate failed; using extractive answer")
            return extractive_answer(formatted, citations), citations, False
        return str(answer), citations, True

    async def _run_llm(self, query: str, index: SearchIndex, api_key: str) -> str:
        from pydantic_ai import Agent, RunContext
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        model = OpenAIChatModel(
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
            try:
                text, _ = await asyncio.to_thread(retrieve, ctx.deps.index, q)
            except (EmptyQuery, QueryRejected):
                text, _ = await asyncio.to_thread(retrieve, ctx.deps.index, query)
            return text

        result = await agent.run(query, deps=AgentDeps(index=index))
        return getattr(result, "output", None) or getattr(result, "data", None) or str(result)
