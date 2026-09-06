from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import AuthError, Principal, TokenVerifier
from app.runtime import Runtime
from app.store import ConversationStore

_bearer = HTTPBearer(auto_error=False)


def get_runtime(request: Request) -> Runtime:
    runtime: Runtime | None = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(503, "Application is not ready")
    return runtime


def get_store(runtime: Runtime = Depends(get_runtime)) -> ConversationStore:
    return runtime.store


def get_verifier(runtime: Runtime = Depends(get_runtime)) -> TokenVerifier:
    return runtime.verifier


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
            raise HTTPException(
                403,
                f"Insufficient role. Requires one of: {', '.join(roles)}",
            )
        return principal

    return _dep
