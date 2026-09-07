from __future__ import annotations

from dataclasses import dataclass

ROLE_ANALYST = "analyst"
ROLE_ADMIN = "admin"
APP_ROLES = frozenset({ROLE_ANALYST, ROLE_ADMIN})


@dataclass(frozen=True)
class Principal:
    subject: str
    username: str
    roles: frozenset[str]
