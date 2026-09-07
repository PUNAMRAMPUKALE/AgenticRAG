from __future__ import annotations

from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3]


def sync_database_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
        "postgresql+psycopg2://", "postgresql+psycopg://"
    )


def run_alembic_upgrade(admin_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_database_url(admin_url))
    command.upgrade(cfg, "head")
