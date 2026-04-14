"""Google Cloud Storage helpers for raw arXiv archives.

Layout mirrors PROJECT_SPEC.md §8:

    gs://{bucket}/src/{YYMM}/{arxiv_id}.tar.gz
    gs://{bucket}/pdf/{YYMM}/{arxiv_id}.pdf
    gs://{bucket}/metadata/harvest_state.json

The module deliberately wraps the google-cloud-storage client so the rest
of the pipeline never imports it directly — easier to mock in tests.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from google.cloud import storage

from ingestion.config import get_settings

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
