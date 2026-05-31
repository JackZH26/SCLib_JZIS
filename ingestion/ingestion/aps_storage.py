"""Transient storage + secure deletion + TDM audit for APS Licensed Materials.

This module is the compliance heart of the APS ingest. Unlike
``ingestion.storage`` (which uploads arXiv archives to GCS *permanently*),
nothing here is persistent: APS BagIt content is extracted to a temp dir,
handed to the parser/NER, then **force-deleted and verified gone**. The
only thing that survives is a row in ``tdm_audit_log`` proving the raw
content was purged.

Usage (see aps_pipeline):

    with TempBagit(meta.doi_slug) as work:
        work.extract(zip_bytes)              # BagIt ZIP → work.root
        parsed = parse_bagit_dir(work.root, meta)
        ... run NER ...
    # __exit__ force-deletes work.root and verifies it is gone.

    await write_audit_log(audit)             # persistent deletion proof

Deletion guarantees:

* ``TempBagit`` is a context manager — the temp dir is removed in
  ``__exit__`` even if extraction/NER raises.
* After ``rmtree`` we re-check ``os.path.exists``; ``deleted`` is True
  only if the path is actually gone. The caller writes this into
  ``tdm_audit_log.deletion_confirmed``.
* Temp dirs default to a tmpfs (``/dev/shm``) when available, so the
  Licensed Materials live in RAM and never touch persistent disk.

Extraction is hardened against malicious/oversized archives (path
traversal + absolute paths + total-size cap) — defensive, since the
payload is third-party.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func

from ingestion.config import get_settings

log = logging.getLogger(__name__)

#: Hard cap on total uncompressed BagIt size (zip-bomb guard). APS
#: full-text packages are a few MB; 500 MB is generous headroom.
_MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024


def _temp_base() -> Path:
    """Pick the base dir for transient extraction.

    Order: explicit config → tmpfs (/dev/shm) if writable → system temp.
    A tmpfs keeps Licensed Materials in RAM (never persisted to disk).
    """
    settings = get_settings()
    if settings.aps_temp_base:
        base = Path(settings.aps_temp_base)
        base.mkdir(parents=True, exist_ok=True)
        return base
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        base = shm / "sclib-aps"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(tempfile.gettempdir())


@dataclass
class FileRecord:
    """Name + size + kind of one Licensed file that passed through the
    temp dir. Names/sizes only — never content — for the audit row."""

    name: str
    bytes: int
    kind: str  # "xml" | "pdf" | "ocr" | "other"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "bytes": self.bytes, "kind": self.kind}


def _classify(name: str) -> str:
    low = name.lower()
    if low.endswith(".xml"):
        return "xml"
    if low.endswith(".pdf"):
        return "pdf"
    if low.endswith((".txt", ".ocr")):
        return "ocr"
    return "other"


class TempBagit:
    """Context manager owning one paper's transient extraction dir.

    The dir (0700) is created on ``__enter__`` and force-deleted +
    verified-gone on ``__exit__``. ``deleted`` / ``deleted_at`` /
    ``files`` / ``bagit_bytes`` are populated for the audit row.
    """

    def __init__(self, doi_slug: str) -> None:
        self.doi_slug = doi_slug
        self.root: Path | None = None
        self.files: list[FileRecord] = []
        self.bagit_bytes: int = 0
        self.deleted: bool = False
        self.deleted_at: datetime | None = None

    def __enter__(self) -> "TempBagit":
        base = _temp_base()
        # mkdtemp creates the dir with 0700 already.
        self.root = Path(tempfile.mkdtemp(prefix=f"aps-{self.doi_slug}-", dir=base))
        os.chmod(self.root, 0o700)
        log.debug("aps temp dir created: %s", self.root)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.purge()

    # --- extraction --------------------------------------------------------

    def extract(self, zip_bytes: bytes) -> Path:
        """Safely unpack the BagIt ZIP into the temp dir.

        Guards against path traversal, absolute paths, and zip bombs.
        Records each extracted file (name/size/kind) for the audit row.
        Returns the extraction root.
        """
        assert self.root is not None, "use TempBagit as a context manager"
        self.bagit_bytes = len(zip_bytes)
        total = 0
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                dest = self._safe_dest(info.filename)
                total += info.file_size
                if total > _MAX_UNCOMPRESSED_BYTES:
                    raise ApsStorageError(
                        f"BagIt exceeds {_MAX_UNCOMPRESSED_BYTES} bytes "
                        f"uncompressed — refusing (zip-bomb guard)"
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                self.files.append(FileRecord(
                    name=info.filename,
                    bytes=info.file_size,
                    kind=_classify(info.filename),
                ))
        log.info("extracted BagIt for %s: %d files, %d zip bytes",
                 self.doi_slug, len(self.files), self.bagit_bytes)
        return self.root

    def _safe_dest(self, member_name: str) -> Path:
        """Resolve a ZIP member to a path strictly inside ``self.root``."""
        assert self.root is not None
        # Reject absolute paths and parent-dir escapes.
        member = member_name.replace("\\", "/")
        if member.startswith("/") or ".." in Path(member).parts:
            raise ApsStorageError(f"unsafe BagIt member path: {member_name!r}")
        dest = (self.root / member).resolve()
        root_resolved = self.root.resolve()
        if not str(dest).startswith(str(root_resolved) + os.sep):
            raise ApsStorageError(f"BagIt member escapes temp dir: {member_name!r}")
        return dest

    # --- deletion ----------------------------------------------------------

    def purge(self) -> bool:
        """Force-delete the temp dir and verify it is gone.

        Idempotent and never raises — deletion must not be defeated by an
        error. Sets ``deleted`` / ``deleted_at``. Returns ``deleted``.
        """
        if self.root is None:
            self.deleted = True
            return True
        try:
            shutil.rmtree(self.root, ignore_errors=True)
        except Exception as e:  # noqa: BLE001 — never let cleanup throw
            log.error("rmtree failed for %s: %s", self.root, e)
        # Verification: the proof the audit row attests to.
        self.deleted = not self.root.exists()
        self.deleted_at = datetime.now(timezone.utc)
        if self.deleted:
            log.info("aps temp dir purged + verified gone: %s", self.root)
        else:
            log.error("aps temp dir STILL EXISTS after purge: %s", self.root)
        return self.deleted


class ApsStorageError(RuntimeError):
    """Raised on unsafe BagIt extraction (traversal / zip-bomb)."""


# ---------------------------------------------------------------------------
# TDM audit log
# ---------------------------------------------------------------------------

@dataclass
class TdmAudit:
    """Builder for one ``tdm_audit_log`` row — the persistent deletion
    proof. Populated across the pipeline; written once at the end."""

    doi: str
    paper_id: str | None = None
    source: str = "aps"
    harvested_at: datetime | None = None
    processed_at: datetime | None = None
    bagit_bytes: int | None = None
    files_processed: list[dict[str, Any]] = field(default_factory=list)
    ner_record_count: int = 0
    deleted_at: datetime | None = None
    deletion_confirmed: bool = False
    temp_path: str | None = None
    status: str = "pending"  # pending | processed | deleted | error
    error: str | None = None

    def from_temp(self, work: TempBagit) -> "TdmAudit":
        """Copy file/size/deletion facts off a TempBagit."""
        self.bagit_bytes = work.bagit_bytes
        self.files_processed = [f.to_dict() for f in work.files]
        self.deleted_at = work.deleted_at
        self.deletion_confirmed = work.deleted
        self.temp_path = str(work.root) if work.root else None
        return self

    def to_values(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "doi": self.doi,
            "paper_id": self.paper_id,
            "harvested_at": self.harvested_at,
            "processed_at": self.processed_at,
            "bagit_bytes": self.bagit_bytes,
            "files_processed": self.files_processed,
            "ner_record_count": self.ner_record_count,
            "deleted_at": self.deleted_at,
            "deletion_confirmed": self.deletion_confirmed,
            "temp_path": self.temp_path,
            "status": self.status,
            "error": self.error,
        }


async def write_audit_log(audit: TdmAudit) -> None:
    """Insert one ``tdm_audit_log`` row (the persistent deletion proof).

    Imported lazily so this module stays importable (and unit-testable)
    without a DB / the indexer's heavy GCP imports.
    """
    from ingestion.index.indexer import _session_factory, tdm_audit_log_table

    async with _session_factory()() as session:
        async with session.begin():
            await session.execute(
                tdm_audit_log_table.insert().values(**audit.to_values())
            )
    log.info("tdm_audit_log written: doi=%s status=%s deleted=%s",
             audit.doi, audit.status, audit.deletion_confirmed)


# ---------------------------------------------------------------------------
# Janitor (backstop for the Phase-8 cron)
# ---------------------------------------------------------------------------

def sweep_stale_temp_dirs(max_age_seconds: int | None = None) -> list[str]:
    """Delete any ``aps-*`` temp dir older than ``max_age_seconds``.

    A backstop for the case where a hard crash skips ``TempBagit.purge``.
    Returns the paths removed (for logging by the cron). Uses wall-clock
    mtime — fine for a janitor (unlike the pipeline, which is event-driven).
    """
    import time

    settings = get_settings()
    max_age = (max_age_seconds if max_age_seconds is not None
               else settings.aps_temp_max_age_seconds)
    base = _temp_base()
    removed: list[str] = []
    now = time.time()
    for entry in base.glob("aps-*"):
        if not entry.is_dir():
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:
            continue
        if age >= max_age:
            shutil.rmtree(entry, ignore_errors=True)
            if not entry.exists():
                removed.append(str(entry))
                log.warning("janitor purged stale aps temp dir (%.0fs old): %s",
                            age, entry)
    return removed
