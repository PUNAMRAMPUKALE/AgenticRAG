from __future__ import annotations

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import Settings
from app.core.errors import AuthError
from app.domain.identity import Principal


class GoogleIdentity:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._request = google_requests.Request()

    @property
    def ready(self) -> bool:
        return bool(self._settings.google_client_id.strip())

    def verify_id_token(self, token: str) -> Principal:
        if not token.strip():
            raise AuthError(401, "Missing Google ID token")
        try:
            payload = id_token.verify_oauth2_token(
                token,
                self._request,
                audience=self._settings.google_client_id,
                clock_skew_in_seconds=30,
            )
        except Exception as exc:
            raise AuthError(401, "Invalid Google ID token") from exc
        iss = str(payload.get("iss") or "")
        if iss not in ("https://accounts.google.com", "accounts.google.com"):
            raise AuthError(401, "Token issuer is not Google")
        if not payload.get("email_verified"):
            raise AuthError(401, "Google email is not verified")
        email = str(payload.get("email") or "").lower()
        if not email:
            raise AuthError(401, "Google token missing email")
        domain = self._settings.google_allowed_domain.strip().lower()
        if domain and not email.endswith(f"@{domain}"):
            raise AuthError(403, f"Sign-in is limited to @{domain} accounts")
        roles = self._settings.roles_for_email(email)
        subject = str(payload.get("sub") or "")
        if not subject:
            raise AuthError(401, "Google token missing sub")
        name = str(payload.get("name") or email)
        return Principal(subject=subject, username=name, roles=frozenset(roles))
