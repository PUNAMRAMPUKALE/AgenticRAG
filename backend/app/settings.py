from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://agenticrag:agenticrag@127.0.0.1:5432/agenticrag"
    redis_url: str = "redis://127.0.0.1:6379/0"
    cache_ttl_seconds: int = 900
    jwt_secret: str = "dev-only-change-me"
    jwt_hours: int = 12
    auth_allow_dev_login: bool = True
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:5175,http://127.0.0.1:5175"
    )

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def require_production_guards(self) -> None:
        if self.environment.lower() != "production":
            return
        if self.jwt_secret in ("", "dev-only-change-me"):
            raise RuntimeError("Set JWT_SECRET to a strong value when ENVIRONMENT=production")
        if self.auth_allow_dev_login:
            raise RuntimeError("Set AUTH_ALLOW_DEV_LOGIN=false when ENVIRONMENT=production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
