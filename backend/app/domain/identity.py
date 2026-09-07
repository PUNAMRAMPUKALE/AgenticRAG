from __future__ import annotations

from dataclasses import dataclass

ROLE_ANALYST = "analyst"
ROLE_SENIOR_ANALYST = "senior_analyst"
ROLE_MANAGER = "manager"
APP_ROLES = frozenset({ROLE_ANALYST, ROLE_SENIOR_ANALYST, ROLE_MANAGER})
CHAT_ROLES = APP_ROLES
REINDEX_ROLES = frozenset({ROLE_MANAGER})


@dataclass(frozen=True)
class Principal:
    subject: str
    username: str
    roles: frozenset[str]
