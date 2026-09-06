from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_principal
from app.core.security import Principal
from app.settings import get_settings

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.get("/config")
def auth_config():
    settings = get_settings()
    return {
        "issuer": settings.oidc_issuer,
        "client_id": settings.oidc_spa_client_id,
        "audience": settings.oidc_audience,
    }


@router.get("/me")
def me(principal: Principal = Depends(get_principal)):
    return {
        "sub": principal.subject,
        "username": principal.username,
        "roles": sorted(principal.roles),
    }
