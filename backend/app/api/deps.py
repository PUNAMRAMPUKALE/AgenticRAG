from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.cookies import SESSION_COOKIE
from app.application.container import AppContainer
from app.core.errors import AuthError
from app.domain.identity import Principal

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> AppContainer:
    container: AppContainer | None = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(503, "Application is not ready")
    return container


async def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    container: AppContainer = Depends(get_container),
) -> Principal:
    try:
        if creds:
            return container.identity.verify_id_token(creds.credentials)
        principal = await container.sessions.get(request.cookies.get(SESSION_COOKIE) or "")
        if principal is None:
            raise AuthError(401, "Not signed in. Use Sign in with Google.")
        return principal
    except AuthError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def require_any_role(*roles: str) -> Callable[..., Principal]:
    async def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.roles.isdisjoint(roles):
            raise HTTPException(403, f"Insufficient role. Requires one of: {', '.join(roles)}")
        return principal

    return _dep
