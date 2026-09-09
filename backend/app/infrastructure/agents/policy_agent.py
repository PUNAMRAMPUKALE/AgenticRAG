from __future__ import annotations

NAME = "policy"
PROMPT = (
    "You are the Horizon Trust POLICY specialist (KYC, AML, onboarding, compliance). "
    "Use POLICY tool results and CONTEXT. Cite file_id when CONTEXT has it. "
    "Do not invent procedures beyond those sources."
)


def lookup_kyc_onboarding(query: str) -> dict:
    """Placeholder policy tool. Replace with the real KYC/compliance API later."""
    return {
        "tool": "lookup_kyc_onboarding",
        "mock": True,
        "query": query[:200],
        "procedure": "KYC client onboarding: collect identity evidence, verify, apply the business rule, record the decision.",
        "required_documents": ["government ID", "proof of address"],
        "sla_hours": 48,
    }


def call_tools(query: str) -> list[dict]:
    return [lookup_kyc_onboarding(query)]
