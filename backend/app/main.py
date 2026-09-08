from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.application.container import AppContainer, build_container
from app.core.aws import load_optional_secrets
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.telemetry import instrument_app, setup_telemetry

_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env", override=True)
load_dotenv(override=True)
load_optional_secrets()
get_settings.cache_clear()
configure_logging()
setup_telemetry(get_settings())

log = logging.getLogger(__name__)


async def _migrate_in_background(container: AppContainer) -> None:
    migrate = getattr(container.conversations, "migrate", None)
    if migrate is None:
        return
    try:
        await migrate()
        log.info("Postgres schema migrate finished")
    except Exception:
        log.exception("Postgres schema migrate failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    container = await build_container(settings)
    app.state.container = container
    if settings.migrate_on_boot:
        asyncio.create_task(_migrate_in_background(container), name="alembic-migrate")
    if container.ingest_watcher is not None:
        container.ingest_watcher.start(asyncio.get_running_loop())
    if container.s3_pipeline is not None:
        container.s3_pipeline.start(asyncio.get_running_loop())
    yield
    await container.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="Agentic RAG", version="0.5.0", lifespan=lifespan)
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @application.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @application.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error")
        return JSONResponse({"detail": str(exc)[:500] or "Internal Server Error"}, status_code=500)

    application.include_router(api_router)
    instrument_app(application)
    return application


app = create_app()
