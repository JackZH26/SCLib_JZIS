"""Ingestion settings — read from env / .env.

Deliberately separate from api.config.Settings so ingestion can run
without the API deps. Values that overlap (DATABASE_URL, GCP_PROJECT,
GCS_BUCKET, VERTEX_AI_*, EMBEDDING_MODEL, GEMINI_MODEL) intentionally
share variable names with the API so a single .env works for both.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database (shared with api) -----------------------------------------
    database_url: str = Field(..., description="SQLAlchemy URL")

    # --- GCP ----------------------------------------------------------------
    gcp_project: str = "jzis-sclib"
    gcp_region: str = "us-central1"
    gcs_bucket: str = "sclib-jzis"
    google_application_credentials: str | None = None
    vertex_ai_index_endpoint: str = ""
    vertex_ai_deployed_index_id: str = "sclib_papers_v1"

    # --- AI models ----------------------------------------------------------
    embedding_model: str = "text-embedding-005"
    gemini_model: str = "gemini-2.5-flash"

    # --- arXiv fetch --------------------------------------------------------
    arxiv_oai_url: str = "https://export.arxiv.org/oai2"
    arxiv_user_agent: str = "SCLib-JZIS/1.0 (jzis.org; jack@jzis.org)"
    #: seconds between OAI-PMH ListRecords calls (arXiv fair use)
    arxiv_metadata_delay: float = 5.0
    #: seconds between source/PDF downloads
    arxiv_file_delay: float = 3.0
    #: hard cap on papers processed per run
    arxiv_daily_limit: int = 5000
    #: OAI-PMH set spec
    arxiv_set: str = "physics:cond-mat"  # most granular available via OAI-PMH
    #: arXiv primary-category filter applied client-side after OAI-PMH
    arxiv_primary_category: str = "cond-mat.supr-con"

    # --- Chunking -----------------------------------------------------------
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    #: Vertex embedding batch size (text-embedding-005 allows up to 250)
    embed_batch_size: int = 100

    # --- Failure pool -------------------------------------------------------
    #: A batch run is considered successful (exit 0) if the per-paper
    #: success ratio meets this threshold. Failed papers aren't lost —
    #: they land in the GCS failure pool for a later `--mode retry` run.
    failure_success_threshold: float = 0.66
    #: How many times to retry a failed paper (across all escalation
    #: strategies) before marking it ``dead``.
    failure_max_attempts: int = 5


@lru_cache(maxsize=1)
def get_settings() -> IngestionSettings:
    return IngestionSettings()  # type: ignore[call-arg]
