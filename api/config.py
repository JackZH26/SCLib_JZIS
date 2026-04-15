"""Central settings loaded from environment variables / .env.

All runtime configuration for the API lives here. Pydantic-settings parses
types, applies defaults, and raises at startup if a required value is missing.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # === App ===
    environment: Literal["development", "test", "production"] = "production"
    frontend_url: str = "https://jzis.org/sclib"
    api_base_url: str = "https://api.jzis.org/sclib/v1"

    # === Database ===
    database_url: str = Field(..., description="SQLAlchemy URL, e.g. postgresql://u:p@host/db")

    # === Redis ===
    redis_url: str = "redis://redis:6379"

    # === Auth ===
    jwt_secret: str = Field(..., min_length=32)
    jwt_expiry_hours: int = 24
    api_key_prefix: str = "scl_"

    # === Rate limiting ===
    guest_daily_limit: int = 3

    # === Internal admin hooks ===
    # Shared secret for internal endpoints like POST /stats/refresh that
    # the nightly cron calls. Never exposed via Nginx's public location.
    internal_api_key: str = ""

    # === Email (Resend) ===
    resend_api_key: str = ""
    email_from: str = "SCLib <noreply@jzis.org>"
    # "resend" uses the real API; "stdout" prints to the log (dev/test)
    email_backend: Literal["resend", "stdout"] = "resend"

    # === GCP ===
    gcp_project: str = "jzis-sclib"
    gcp_region: str = "us-central1"
    gcs_bucket: str = "sclib-jzis"
    google_application_credentials: str = "/credentials/gcp-sa.json"
    vertex_ai_index_endpoint: str = ""
    vertex_ai_deployed_index_id: str = "sclib_papers_v1"

    # === AI models ===
    gemini_model: str = "gemini-2.5-flash"
    embedding_model: str = "text-embedding-005"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton. Import this, not Settings directly, so tests can
    monkeypatch the cache between runs."""
    return Settings()  # type: ignore[call-arg]
