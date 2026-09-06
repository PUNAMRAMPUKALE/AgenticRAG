from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

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
    oidc_issuer: str = "http://127.0.0.1:8080/realms/agenticrag"
    oidc_audience: str = "agenticrag-api"
    oidc_spa_client_id: str = "agenticrag-spa"
    oidc_jwks_url: str = ""
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:5175,http://127.0.0.1:5175"
    )

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def require_production_guards(self) -> None:
        if not self.oidc_issuer.strip() or not self.oidc_audience.strip():
            raise RuntimeError("OIDC_ISSUER and OIDC_AUDIENCE are required")
        if self.environment.lower() != "production":
            return
        parsed = urlparse(self.oidc_issuer)
        if parsed.scheme != "https":
            raise RuntimeError("OIDC_ISSUER must use https when ENVIRONMENT=production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
