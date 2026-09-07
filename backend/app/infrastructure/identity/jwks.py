from __future__ import annotations

import httpx
import jwt
from jwt import PyJWKClient

from app.core.errors import AuthError
from app.domain.identity import APP_ROLES, Principal


def _extract_roles(payload: dict) -> frozenset[str]:
    found: set[str] = set()
    realm = payload.get("realm_access")
    if isinstance(realm, dict):
        found.update(str(r) for r in realm.get("roles") or [])
    resources = payload.get("resource_access")
    if isinstance(resources, dict):
        for entry in resources.values():
            if isinstance(entry, dict):
                found.update(str(r) for r in entry.get("roles") or [])
    claim = payload.get("roles")
    if isinstance(claim, list):
        found.update(str(r) for r in claim)
    return frozenset(r for r in found if r in APP_ROLES)


class JwksTokenVerifier:
    def __init__(self, issuer: str, audience: str, jwks_url: str | None = None):
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self._jwks_url = (jwks_url or "").strip() or None
        self._jwks: PyJWKClient | None = None

    @property
    def ready(self) -> bool:
        return self._jwks is not None

    async def warmup(self) -> None:
        url = self._jwks_url or await self._discover_jwks()
        self._jwks = PyJWKClient(url, cache_keys=True, lifespan=3600)

    async def _discover_jwks(self) -> str:
        well_known = f"{self.issuer}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(well_known)
                res.raise_for_status()
                jwks_uri = res.json().get("jwks_uri")
        except Exception as exc:
            raise RuntimeError(
                f"Cannot load OIDC discovery from {well_known}. Start Keycloak: docker compose up -d keycloak"
            ) from exc
        if not jwks_uri:
            raise RuntimeError("OIDC discovery document is missing jwks_uri")
        return str(jwks_uri)

    def verify(self, authorization: str | None) -> Principal:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError(401, "Missing Authorization: Bearer <access_token>")
        if self._jwks is None:
            raise AuthError(503, "OIDC verifier is not ready")
        token = authorization.split(" ", 1)[1].strip()
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                key.key,
                algorithms=["RS256", "ES256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=30,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError(401, "Token expired. Sign in again.") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthError(401, "Token audience is not this API") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthError(401, "Token issuer is not the configured identity provider") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthError(401, "Invalid token") from exc
        subject = str(payload.get("sub") or "")
        if not subject:
            raise AuthError(401, "Token missing sub")
        username = str(payload.get("preferred_username") or payload.get("email") or subject)
        return Principal(subject=subject, username=username, roles=_extract_roles(payload))
