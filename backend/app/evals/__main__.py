from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.core.aws import load_optional_secrets
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import setup_telemetry
from app.evals.runner import run_evals
from app.infrastructure.retrieval.vespa_index import VespaSearchIndex
from app.infrastructure.retrieval.vespa_store import VespaChunkStore


async def _main(generate: bool, out: Path | None) -> int:
    settings = get_settings()
    store = VespaChunkStore(
        settings.vespa_url.strip() or "http://127.0.0.1:8080",
        config_url=settings.vespa_config_url.strip() or "http://127.0.0.1:19071",
        auto_deploy=False,
    )
    if not await store.ping():
        print("Vespa query port is down. Start: docker compose up -d vespa", file=sys.stderr)
        return 2
    chunks = store.count_chunks()
    if chunks < 1:
        print("Vespa has no chunks. Ingest knowledge before running evals.", file=sys.stderr)
        return 2
    report = await run_evals(VespaSearchIndex(store), generate=generate)
    report["vespa_chunks"] = chunks
    text = json.dumps(report, indent=2)
    print(text)
    if out:
        out.write_text(text, encoding="utf-8")
    return 0 if report["ok"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AgenticRAG gold evals against live Vespa.")
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Call the chat generator (LLM if LLM_API_KEY is set). Default is retrieval + extractive answer.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Write JSON report to this path")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    load_dotenv(repo / ".env", override=True)
    load_dotenv(override=True)
    load_optional_secrets()
    get_settings.cache_clear()
    configure_logging()
    setup_telemetry(get_settings())
    raise SystemExit(asyncio.run(_main(args.generate, args.out)))


if __name__ == "__main__":
    main()
