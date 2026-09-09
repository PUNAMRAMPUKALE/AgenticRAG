from __future__ import annotations

from app.domain.ports import SearchIndex
from app.infrastructure.llm.assistant import retrieve

TOOL_SEARCH = "search_knowledge"


def search_knowledge(index: SearchIndex, query: str, k: int = 4) -> dict:
    """MCP-shaped retrieval tool: Vespa hybrid search, no corpus in RAM."""
    formatted, citations = retrieve(index, query, k=k)
    return {"context": formatted, "citations": citations}
