from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.application.container import build_container
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.middleware import RequestContextMiddleware

_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env", override=True)
load_dotenv(override=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = await build_container(get_settings())
    app.state.container = container
    if container.ingest_watcher is not None:
        container.ingest_watcher.start(asyncio.get_running_loop())
    if container.s3_pipeline is not None:
        await container.s3_pipeline.sync_now()
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

    application.include_router(api_router)
    return application


app = create_app()
