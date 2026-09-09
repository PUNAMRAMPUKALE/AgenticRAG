from __future__ import annotations

from app.core.telemetry import get_tracer
from app.domain.ports import AgentTurn, SearchIndex
from app.infrastructure.agents.cost import estimate_cost, record_usage
from app.infrastructure.agents.guards import SAFE_FALLBACK, input_guard, output_guard
from app.infrastructure.agents.hitl import HitlQueue
from app.infrastructure.agents.mcp_tools import search_knowledge
from app.infrastructure.agents.quality import critique
from app.infrastructure.agents.supervisor import classify_intent
from app.infrastructure.llm.assistant import KnowledgeAssistant, extractive_answer

_HITL_MSG = (
    "This needs a human reviewer (complaint, legal, or sensitive request). "
    "A manager has been queued. I will not auto-answer from the knowledge base."
)


class KnowledgeOrchestrator:
    """Supervisor → specialist (MCP retrieve + RAG) → quality critic; HITL on escalation."""

    def __init__(self, hitl: HitlQueue | None = None):
        self._hitl = hitl or HitlQueue()
        self._assistant = KnowledgeAssistant()

    async def generate(
        self,
        query: str,
        index: SearchIndex,
        *,
        user_id: str = "",
        session_id: str = "",
    ) -> AgentTurn:
        tracer = get_tracer()
        blocked, _reason = input_guard(query)
        if blocked:
            return AgentTurn(answer=blocked, blocked=True, intent="blocked")

        with tracer.start_as_current_span("agent.supervisor"):
            intent, calls, ptok, ctok = await classify_intent(query)
        prompt_tokens, completion_tokens, llm_calls = ptok, ctok, calls

        if intent == "escalation":
            await self._hitl.enqueue(
                query=query, user_id=user_id, session_id=session_id, reason="escalation"
            )
            answer = output_guard(_HITL_MSG, query)
            cost = estimate_cost(prompt_tokens, completion_tokens)
            record_usage(
                intent=intent,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                llm_calls=llm_calls,
            )
            return AgentTurn(
                answer=answer,
                intent=intent,
                hitl_pending=True,
                llm_calls=llm_calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
            )

        with tracer.start_as_current_span("agent.retrieve"):
            tool = search_knowledge(index, query, k=4)
        context, citations = tool["context"], tool["citations"]

        with tracer.start_as_current_span("agent.specialist"):
            try:
                answer, used_llm = await self._assistant.answer_from_retrieval(query, index, context, citations)
            except Exception:
                answer, used_llm = extractive_answer(context, citations), False
            turn = AgentTurn(answer=answer, citations=citations, used_llm=used_llm, context=context)
        prompt_tokens += 400
        completion_tokens += max(20, len(turn.answer) // 4)
        llm_calls += 1 if turn.used_llm else 0
        retries = 0

        if turn.used_llm and context:
            with tracer.start_as_current_span("agent.quality"):
                score, reason, rewrite, qp, qc = await critique(turn.answer, context)
            prompt_tokens += qp
            completion_tokens += qc
            llm_calls += 1 if qp else 0
            if rewrite and retries < 1:
                retries = 1
                with tracer.start_as_current_span("agent.quality_retry"):
                    hint = f"{query}\n\nRewrite using only the retrieved documents. Critic: {reason}"
                    answer, used_llm = await self._assistant.answer_from_retrieval(
                        hint, index, context, citations
                    )
                    turn = AgentTurn(answer=answer, citations=citations, used_llm=used_llm, context=context)
                    llm_calls += 1 if used_llm else 0

        answer = output_guard(turn.answer or extractive_answer(context, citations), query)
        cost = estimate_cost(prompt_tokens, completion_tokens)
        record_usage(
            intent=intent,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            llm_calls=llm_calls,
        )
        return AgentTurn(
            answer=answer,
            citations=citations or turn.citations,
            used_llm=turn.used_llm,
            intent=intent,
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=round(cost, 6),
            quality_retries=retries,
            context=context,
            blocked=answer == SAFE_FALLBACK and not citations,
        )
