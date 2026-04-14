"""Google Cloud Storage helpers for raw arXiv archives.

Layout mirrors PROJECT_SPEC.md §8:

    gs://{bucket}/src/{YYMM}/{arxiv_id}.tar.gz
    gs://{bucket}/pdf/{YYMM}/{arxiv_id}.pdf
    gs://{bucket}/metadata/harvest_state.json
    gs://{bucket}/metadata/failed_papers.json   # failure pool (see below)

The module deliberately wraps the google-cloud-storage client so the rest
of the pipeline never imports it directly — easier to mock in tests.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from google.cloud import storage

from ingestion.config import get_settings
from ingestion.models import PaperMetadata

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _bucket() -> storage.Bucket:
    settings = get_settings()
    client = storage.Client(project=settings.gcp_project)
    return client.bucket(settings.gcs_bucket)


def _src_blob_name(arxiv_id: str, yymm: str) -> str:
    return f"src/{yymm}/{arxiv_id.replace('/', '_')}.tar.gz"


def _pdf_blob_name(arxiv_id: str, yymm: str) -> str:
    return f"pdf/{yymm}/{arxiv_id.replace('/', '_')}.pdf"


def source_exists(arxiv_id: str, yymm: str) -> bool:
    return _bucket().blob(_src_blob_name(arxiv_id, yymm)).exists()


def pdf_exists(arxiv_id: str, yymm: str) -> bool:
    return _bucket().blob(_pdf_blob_name(arxiv_id, yymm)).exists()


def already_downloaded(arxiv_id: str, yymm: str) -> bool:
    """Idempotency check for resumable bulk runs."""
    b = _bucket()
    return (
        b.blob(_src_blob_name(arxiv_id, yymm)).exists()
        or b.blob(_pdf_blob_name(arxiv_id, yymm)).exists()
    )


def upload_source(arxiv_id: str, yymm: str, data: bytes) -> str:
    name = _src_blob_name(arxiv_id, yymm)
    blob = _bucket().blob(name)
    blob.upload_from_string(data, content_type="application/gzip")
    log.info("uploaded %s (%d bytes)", name, len(data))
    return name


def upload_pdf(arxiv_id: str, yymm: str, data: bytes) -> str:
    name = _pdf_blob_name(arxiv_id, yymm)
    blob = _bucket().blob(name)
    blob.upload_from_string(data, content_type="application/pdf")
    log.info("uploaded %s (%d bytes)", name, len(data))
    return name


def download_source(arxiv_id: str, yymm: str) -> bytes:
    return _bucket().blob(_src_blob_name(arxiv_id, yymm)).download_as_bytes()


def download_pdf(arxiv_id: str, yymm: str) -> bytes:
    return _bucket().blob(_pdf_blob_name(arxiv_id, yymm)).download_as_bytes()


# --- harvest state ---------------------------------------------------------

HARVEST_STATE_BLOB = "metadata/harvest_state.json"


@dataclass
class HarvestState:
    last_harvested_at: str | None = None  # ISO-8601
    bulk_cursor: str | None = None        # YYYY-MM-DD of last completed day

    def to_json(self) -> str:
        return json.dumps(
            {"last_harvested_at": self.last_harvested_at,
             "bulk_cursor": self.bulk_cursor},
            indent=2,
        )

    @classmethod
    def from_json(cls, data: str | bytes) -> "HarvestState":
        obj: dict[str, Any] = json.loads(data)
        return cls(
            last_harvested_at=obj.get("last_harvested_at"),
            bulk_cursor=obj.get("bulk_cursor"),
        )


def load_harvest_state() -> HarvestState:
    blob = _bucket().blob(HARVEST_STATE_BLOB)
    if not blob.exists():
        return HarvestState()
    return HarvestState.from_json(blob.download_as_bytes())


def save_harvest_state(state: HarvestState) -> None:
    blob = _bucket().blob(HARVEST_STATE_BLOB)
    blob.upload_from_string(state.to_json(), content_type="application/json")
    log.info("saved harvest_state: %s", state)


# --- failure pool ----------------------------------------------------------
#
# When a paper fails somewhere in the per-paper pipeline (download, parse,
# embed, NER, DB, or Vector Search), we record it here instead of losing
# it. A later ``--mode retry`` run loads this pool and re-attempts each
# paper with escalating strategies (force PDF, skip NER, abstract-only).
#
# Shape on disk::
#
#     {
#       "papers": {
#         "2603.16115": {
#           "arxiv_id": "...", "yymm": "2603",
#           "meta": { PaperMetadata.to_dict() },
#           "first_failed_at": "...", "last_failed_at": "...",
#           "attempt_count": 2, "last_stage": "embed",
#           "last_error": "...", "strategies_tried": ["default", "force_pdf"],
#           "status": "pending"
#         },
#         ...
#       }
#     }
#
# Kept as a single JSON object so the whole pool can be read/written
# atomically (GCS doesn't support partial object updates).

FAILED_PAPERS_BLOB = "metadata/failed_papers.json"

#: Ordered escalation path. Index N is tried on attempt N+1.
FAILURE_STRATEGIES: tuple[str, ...] = (
    "default",        # re-run the pipeline as-is (transient errors)
    "force_pdf",      # skip /src/ entirely, go straight to PDF fallback
    "skip_ner",       # keep VS, but let Gemini NER be skipped
    "skip_vs",        # DB-only (chunks still searchable by keyword)
    "abstract_only",  # give up on body, chunk abstract only
)


@dataclass
class FailedPaper:
    arxiv_id: str
    yymm: str
    meta: dict[str, Any]              # serialized PaperMetadata
    first_failed_at: str              # ISO-8601
    last_failed_at: str
    attempt_count: int = 1
    last_stage: str = ""              # "download"|"parse"|"embed"|"ner"|"db"|"vs"
    last_error: str = ""
    strategies_tried: list[str] = field(default_factory=list)
    status: str = "pending"           # "pending" | "dead"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailedPaper":
        return cls(
            arxiv_id=data["arxiv_id"],
            yymm=data["yymm"],
            meta=data.get("meta", {}),
            first_failed_at=data["first_failed_at"],
            last_failed_at=data["last_failed_at"],
            attempt_count=data.get("attempt_count", 1),
            last_stage=data.get("last_stage", ""),
            last_error=data.get("last_error", ""),
            strategies_tried=list(data.get("strategies_tried", [])),
            status=data.get("status", "pending"),
        )


def load_failed_papers() -> dict[str, FailedPaper]:
    blob = _bucket().blob(FAILED_PAPERS_BLOB)
    if not blob.exists():
        return {}
    raw = json.loads(blob.download_as_bytes())
    return {
        k: FailedPaper.from_dict(v)
        for k, v in raw.get("papers", {}).items()
    }


def save_failed_papers(pool: dict[str, FailedPaper]) -> None:
    payload = {"papers": {k: v.to_dict() for k, v in pool.items()}}
    _bucket().blob(FAILED_PAPERS_BLOB).upload_from_string(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
    log.info("saved failure pool: %d papers", len(pool))


def record_failure(
    pool: dict[str, FailedPaper],
    meta: PaperMetadata,
    *,
    stage: str,
    error: str,
    strategy: str = "default",
) -> FailedPaper:
    """Add or update a paper in the failure pool. Returns the updated record."""
    now = datetime.now(timezone.utc).isoformat()
    existing = pool.get(meta.arxiv_id)
    if existing is None:
        fp = FailedPaper(
            arxiv_id=meta.arxiv_id,
            yymm=meta.yymm,
            meta=meta.to_dict(),
            first_failed_at=now,
            last_failed_at=now,
            attempt_count=1,
            last_stage=stage,
            last_error=error[:500],
            strategies_tried=[strategy],
        )
    else:
        existing.last_failed_at = now
        existing.attempt_count += 1
        existing.last_stage = stage
        existing.last_error = error[:500]
        if strategy not in existing.strategies_tried:
            existing.strategies_tried.append(strategy)
        fp = existing
    pool[meta.arxiv_id] = fp
    return fp


def clear_failure(pool: dict[str, FailedPaper], arxiv_id: str) -> bool:
    """Remove a paper from the pool after a successful re-ingest.
    Returns True if the paper was in the pool."""
    return pool.pop(arxiv_id, None) is not None
