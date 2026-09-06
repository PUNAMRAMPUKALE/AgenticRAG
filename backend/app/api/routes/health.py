from __future__ import annotations

import os

from fastapi import APIRouter, Request

from app.settings import get_settings

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(request: Request):
    settings = get_settings()
    runtime = getattr(request.app.state, "runtime", None)
    pg_ok = await runtime.store.ping() if runtime else False
    oidc_ok = bool(runtime and runtime.verifier.ready)
    return {
        "ok": pg_ok and oidc_ok,
        "environment": settings.environment,
        "postgres": pg_ok,
        "oidc": oidc_ok,
        "oidc_issuer": settings.oidc_issuer,
        "docs_indexed": len(runtime.chunks) if runtime else 0,
        "index_version": runtime.index_version if runtime else "",
        "redis": runtime.cache.enabled if runtime else False,
        "cache_ttl_seconds": settings.cache_ttl_seconds,
        "llm_enabled": bool((os.getenv("LLM_API_KEY") or "").strip()),
        "conversations": await runtime.store.count() if runtime and pg_ok else 0,
    }
