from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://agenticrag:agenticrag@127.0.0.1:5432/agenticrag"
    redis_url: str = "redis://127.0.0.1:6379/0"
    cache_ttl_seconds: int = 900
    google_client_id: str = ""
    google_admin_emails: str = ""
    google_allowed_domain: str = ""
    session_hours: int = 12
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:5175,http://127.0.0.1:5175"
    )

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.google_admin_emails.split(",") if e.strip()}

    def require_production_guards(self) -> None:
        if not self.google_client_id.strip():
            raise RuntimeError(
                "GOOGLE_CLIENT_ID is required. Create an OAuth 2.0 Web client in Google Cloud Console."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
