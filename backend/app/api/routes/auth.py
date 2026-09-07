from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_principal
from app.application.container import AppContainer
from app.domain.identity import Principal

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.get("/config")
def auth_config(container: AppContainer = Depends(get_container)):
    s = container.settings
    return {
        "issuer": s.oidc_issuer,
        "client_id": s.oidc_spa_client_id,
        "audience": s.oidc_audience,
    }


@router.get("/me")
def me(principal: Principal = Depends(get_principal)):
    return {
        "sub": principal.subject,
        "username": principal.username,
        "roles": sorted(principal.roles),
    }
