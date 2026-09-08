from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.identity import ROLE_ANALYST, ROLE_MANAGER, ROLE_SENIOR_ANALYST

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env", override=True)
load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://agenticrag:agenticrag@127.0.0.1:5432/agenticrag"
    redis_url: str = "redis://127.0.0.1:6379/0"
    cache_ttl_seconds: int = 900
    google_client_id: str = ""
    google_analyst_emails: str = ""
    google_senior_analyst_emails: str = ""
    google_manager_emails: str = ""
    google_allowed_domain: str = ""
    session_hours: int = 12
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:5175,http://127.0.0.1:5175"
    )
    knowledge_watch: bool = True
    knowledge_watch_debounce_ms: int = 800
    knowledge_poll_seconds: float = 5.0
    knowledge_source: str = "local"
    knowledge_s3_bucket: str = ""
    knowledge_s3_prefix: str = "knowledge"
    knowledge_s3_region: str = ""
    knowledge_s3_poll_seconds: float = 30.0
    knowledge_s3_queue_url: str = ""
    knowledge_s3_dlq_url: str = ""
    knowledge_s3_max_receive: int = 5
    knowledge_s3_visibility_timeout: int = 900
    knowledge_s3_reconcile_seconds: float = 3600.0
    vespa_url: str = "http://127.0.0.1:8080"
    vespa_config_url: str = "http://127.0.0.1:19071"
    ingest_in_api: bool = True
    migrate_on_boot: bool = True
    database_admin_url: str = ""
    aws_secrets_arn: str = ""
    llm_api_key: str = ""
    llm_choice: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    openai_embedding_model: str = "text-embedding-3-small"

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def _email_set(self, raw: str) -> set[str]:
        return {e.strip().lower() for e in raw.split(",") if e.strip()}

    def roles_for_email(self, email: str) -> frozenset[str]:
        addr = email.strip().lower()
        if addr in self._email_set(self.google_manager_emails):
            return frozenset({ROLE_MANAGER})
        if addr in self._email_set(self.google_senior_analyst_emails):
            return frozenset({ROLE_SENIOR_ANALYST})
        return frozenset({ROLE_ANALYST})

    def require_production_guards(self) -> None:
        if self.environment.lower() != "production":
            return
        if not self.google_client_id.strip():
            raise RuntimeError(
                "GOOGLE_CLIENT_ID is required. Create an OAuth 2.0 Web client in Google Cloud Console."
            )
        if self.knowledge_source.strip().lower() == "s3" and not self.knowledge_s3_bucket.strip():
            raise RuntimeError("KNOWLEDGE_S3_BUCKET is required when KNOWLEDGE_SOURCE=s3.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
