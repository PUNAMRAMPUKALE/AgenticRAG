from __future__ import annotations

NAME = "operations"
PROMPT = (
    "You are the Horizon Trust OPERATIONS specialist (payment SOP, runbooks, wires). "
    "Use OPERATIONS tool results and CONTEXT. Cite file_id when CONTEXT has it. "
    "Do not invent cutoffs or steps beyond those sources."
)


def lookup_payment_sop(query: str) -> dict:
    """Placeholder operations tool. Replace with the real payments/ops API later."""
    return {
        "tool": "lookup_payment_sop",
        "mock": True,
        "query": query[:200],
        "covers": "Payment operations SOP: initiation, dual control, exception handling, and evidence.",
        "wire_cutoff_et": "16:00",
        "dual_control": True,
    }


def lookup_service_runbook(query: str) -> dict:
    """Placeholder runbook tool. Replace with the real service-ops catalog later."""
    return {
        "tool": "lookup_service_runbook",
        "mock": True,
        "query": query[:200],
        "covers": "Service operations runbook: incident intake, severity, and handoff to operations.",
    }


def call_tools(query: str) -> list[dict]:
    return [lookup_payment_sop(query), lookup_service_runbook(query)]
