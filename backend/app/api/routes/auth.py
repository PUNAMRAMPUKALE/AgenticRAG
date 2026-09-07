from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.cookies import SESSION_COOKIE
from app.api.deps import get_container, get_principal
from app.application.container import AppContainer
from app.domain.identity import Principal

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=20)


@router.get("/config")
async def auth_config(container: AppContainer = Depends(get_container)):
    return {
        "provider": "google",
        "client_id": container.settings.google_client_id,
    }


@router.post("/google")
async def google_login(
    body: GoogleLoginRequest,
    response: Response,
    container: AppContainer = Depends(get_container),
):
    principal = container.identity.verify_id_token(body.id_token)
    sid = await container.sessions.create(principal)
    secure = container.settings.environment.lower() == "production"
    response.set_cookie(
        key=SESSION_COOKIE,
        value=sid,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=container.settings.session_hours * 3600,
        path="/",
    )
    return {
        "sub": principal.subject,
        "username": principal.username,
        "roles": sorted(principal.roles),
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    container: AppContainer = Depends(get_container),
):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        await container.sessions.delete(sid)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(principal: Principal = Depends(get_principal)):
    return {
        "sub": principal.subject,
        "username": principal.username,
        "roles": sorted(principal.roles),
    }
