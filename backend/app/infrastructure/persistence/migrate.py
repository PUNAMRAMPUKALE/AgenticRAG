from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3]


def sync_database_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
        "postgresql+psycopg2://", "postgresql+psycopg://"
    )


def _without_backend_on_path() -> list[str]:
    """Do not let a local folder named alembic shadow the installed package."""
    backend = _BACKEND.resolve()
    kept: list[str] = []
    for entry in sys.path:
        if entry in ("", "."):
            continue
        try:
            if Path(entry).resolve() == backend:
                continue
        except OSError:
            pass
        kept.append(entry)
    return kept


def run_alembic_upgrade(admin_url: str) -> None:
    original = sys.path[:]
    sys.path[:] = _without_backend_on_path()
    try:
        from alembic import command
        from alembic.config import Config

        scripts = _BACKEND / "migrations"
        if not scripts.is_dir():
            scripts = _BACKEND / "alembic"
        cfg = Config(str(_BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(scripts))
        cfg.set_main_option("sqlalchemy.url", sync_database_url(admin_url))
        command.upgrade(cfg, "head")
    finally:
        sys.path[:] = original
