from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from app.application.container import build_container
from app.core.aws import load_optional_secrets
from app.core.config import get_settings
from app.core.logging import configure_logging

log = logging.getLogger(__name__)


async def _run() -> None:
    settings = get_settings()
    container = await build_container(settings, run_ingest=True)
    loop = asyncio.get_running_loop()
    try:
        if container.s3_pipeline is not None:
            container.s3_pipeline.start(loop)
            log.info("Ingest worker running S3 pipeline")
        elif container.ingest_watcher is not None:
            container.ingest_watcher.start(loop)
            log.info("Ingest worker watching local knowledge files")
        else:
            await container.knowledge.reindex("ingest-worker")
            log.info("One-shot ingest finished")
            return
        await asyncio.Future()
    except asyncio.CancelledError:
        return
    finally:
        await container.aclose()


def main() -> None:
    repo = Path(__file__).resolve().parents[3]
    load_dotenv(repo / ".env", override=True)
    load_dotenv(override=True)
    load_optional_secrets()
    get_settings.cache_clear()
    configure_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
