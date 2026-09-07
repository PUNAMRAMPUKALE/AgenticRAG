from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.container import AppContainer
from app.core.errors import AuthError
from app.domain.identity import Principal
from app.domain.ports import TokenVerifier

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> AppContainer:
    container: AppContainer | None = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(503, "Application is not ready")
    return container


def get_verifier(container: AppContainer = Depends(get_container)) -> TokenVerifier:
    return container.verifier


def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    verifier: TokenVerifier = Depends(get_verifier),
) -> Principal:
    header = f"Bearer {creds.credentials}" if creds else None
    try:
        return verifier.verify(header)
    except AuthError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def require_any_role(*roles: str) -> Callable[..., Principal]:
    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.roles.isdisjoint(roles):
            raise HTTPException(403, f"Insufficient role. Requires one of: {', '.join(roles)}")
        return principal

    return _dep
