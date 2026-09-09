from __future__ import annotations

import json
from types import ModuleType

import app.infrastructure.agents.operations_agent as operations_agent
import app.infrastructure.agents.policy_agent as policy_agent
import app.infrastructure.agents.treasury_agent as treasury_agent
from app.domain.ports import SearchIndex
from app.infrastructure.llm.assistant import KnowledgeAssistant, extractive_answer

_ASSISTANT = KnowledgeAssistant()

AGENTS: dict[str, ModuleType] = {
    policy_agent.NAME: policy_agent,
    operations_agent.NAME: operations_agent,
    treasury_agent.NAME: treasury_agent,
}


def specialist_for(intent: str) -> ModuleType:
    return AGENTS.get(intent, policy_agent)


def format_tool_results(intent: str, query: str) -> tuple[str, list[dict]]:
    agent = specialist_for(intent)
    payloads = agent.call_tools(query)
    blob = json.dumps(payloads, indent=2)
    return f"{agent.NAME.upper()} TOOLS (mock until replaced):\n{blob}", payloads


def merge_context(vespa_context: str, tool_text: str) -> str:
    parts = [p for p in (vespa_context.strip(), tool_text.strip()) if p]
    return "\n\n".join(parts)


async def run_specialist(
    intent: str,
    query: str,
    index: SearchIndex,
    vespa_context: str,
    citations: list[dict],
    *,
    rewrite_hint: str = "",
) -> tuple[str, bool, str]:
    """Run the routed specialist. Returns answer, used_llm, combined context."""
    agent = specialist_for(intent)
    tool_text, _payloads = format_tool_results(intent, query)
    combined = merge_context(f"{agent.PROMPT}\n\n{vespa_context}", tool_text)
    question = query
    if rewrite_hint:
        question = (
            f"{query}\n\nRewrite using only CONTEXT and {agent.NAME} tool results. "
            f"Critic: {rewrite_hint}"
        )
    try:
        answer, used_llm = await _ASSISTANT.answer_from_retrieval(
            question, index, combined, citations
        )
    except Exception:
        answer, used_llm = extractive_answer(vespa_context, citations), False
    if not used_llm and tool_text:
        answer = f"{answer}\n\n{tool_text}"
    return answer, used_llm, combined
