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
    gemini_model: str = "gemini-3.5-flash"
    gemini_location: str = "global"
    gemini_use_enterprise: bool = True
    gemini_api_version: str = "v1"

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

    # --- APS Harvest (TDM) --------------------------------------------------
    # APS is an additive new source alongside arXiv (see
    # docs/APS_INGESTION_PLAN.md). Auth is IP-whitelist only: VPS2's egress
    # IPs (72.62.251.29, 76.13.191.130) are registered with APS, so the
    # client sends NO credentials — access is granted by source IP. Full
    # text fetched here is transient TDM working data and must be deleted
    # after NER (handled in aps_storage / aps_pipeline, not here).
    aps_harvest_url: str = "https://harvest.aps.org"
    aps_user_agent: str = "SCLib-JZIS/1.0 (jzis.org; jack@jzis.org)"
    #: Per-DOI metadata endpoint (JSON). {doi} is substituted verbatim.
    #: CONFIRMED against the live Harvest API on VPS2 (2026-05-31): returns
    #: 200, VPS2 IP is on the metadata allow-list, field mapping verified
    #: (journal=PRB, title, abstract, DOI all parse correctly).
    aps_metadata_path: str = "/v2/journals/articles/{doi}"
    #: Per-DOI full-text (ZIP) endpoint for TDM. CORRECTED 2026-06-03 from
    #: APS IT's own working example:
    #:   curl -H "accept: application/zip" \
    #:        "https://harvest.aps.org/v2/journals/articles/10.1103/hbdj-2hgf"
    #: The full-text ZIP is the SAME base path as the metadata — content is
    #: negotiated purely by the Accept header (json → metadata, zip → the
    #: full-text package). There is NO /accepted_fulltext (or /bag) subpath;
    #: hitting one returns a generic 401 "Unauthorized" (route miss), which
    #: is exactly the spurious 401 we mistook for a pending TDM scope. APS
    #: confirmed the ZIP needs NO key — access is the same IP whitelist as
    #: metadata. See docs/APS_VALIDATION_FOR_OPENCLAW.md.
    aps_bagit_path: str = "/v2/journals/articles/{doi}"
    #: seconds between metadata calls (APS fair use)
    aps_metadata_delay: float = 2.0
    #: seconds between BagIt downloads (large payloads)
    aps_file_delay: float = 3.0
    #: Base dir for transient BagIt extraction. Empty → auto: prefer a
    #: tmpfs (/dev/shm) so Licensed Materials live in RAM and never hit
    #: persistent disk, else fall back to the system temp dir. Each paper
    #: gets a 0700 subdir that is force-deleted after NER.
    aps_temp_base: str = ""
    #: A janitor (Phase 8 cron) deletes any stray aps-* temp dir older
    #: than this — a backstop in case a crash skips the try/finally purge.
    aps_temp_max_age_seconds: int = 1800

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
