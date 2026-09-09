from __future__ import annotations

NAME = "treasury"
PROMPT = (
    "You are the Horizon Trust TREASURY specialist (liquidity, LCR, capital). "
    "Use TREASURY tool results and CONTEXT. Cite file_id when CONTEXT has it. "
    "Do not invent ratios beyond those sources."
)


def lookup_liquidity_snapshot(query: str) -> dict:
    """Placeholder treasury tool. Replace with the real liquidity/risk feed later."""
    return {
        "tool": "lookup_liquidity_snapshot",
        "mock": True,
        "query": query[:200],
        "as_of": "2026-06-30",
        "report": "Q2 2026 liquidity risk report",
        "lcr": 1.32,
        "nsfr": 1.18,
        "note": "Figures are mock placeholders until the treasury tool is wired.",
    }


def call_tools(query: str) -> list[dict]:
    return [lookup_liquidity_snapshot(query)]
