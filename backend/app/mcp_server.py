from __future__ import annotations

"""stdio MCP server: search_knowledge against live Vespa (Week 8 tool-shaped retrieval)."""

from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    load_dotenv(repo / ".env", override=True)
    from mcp.server.fastmcp import FastMCP

    from app.core.config import get_settings
    from app.infrastructure.agents.mcp_tools import search_knowledge
    from app.infrastructure.retrieval.vespa_index import VespaSearchIndex
    from app.infrastructure.retrieval.vespa_store import VespaChunkStore

    settings = get_settings()
    index = VespaSearchIndex(
        VespaChunkStore(
            settings.vespa_url.strip() or "http://127.0.0.1:8080",
            config_url=settings.vespa_config_url.strip() or "http://127.0.0.1:19071",
            auto_deploy=False,
        )
    )
    server = FastMCP("agenticrag-knowledge")

    @server.tool()
    def search_knowledge_tool(query: str, k: int = 4) -> str:
        """Hybrid search Horizon Trust chunks in Vespa."""
        result = search_knowledge(index, query, k=k)
        return str(result.get("context") or "")

    server.run()


if __name__ == "__main__":
    main()
