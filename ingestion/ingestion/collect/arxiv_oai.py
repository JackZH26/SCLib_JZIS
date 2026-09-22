"""arXiv OAI-PMH harvest + source/pdf downloader.

Two responsibilities:

1. ``list_records`` — iterate metadata for papers in a date range, filtering
   client-side to ``cond-mat.supr-con`` (OAI-PMH only lets us request the
   coarser ``physics:cond-mat`` set).
2. ``download_source`` / ``download_pdf`` — fetch raw bytes for a paper,
   obeying the configured inter-request delay.

Callers are expected to pass the bytes directly to ``ingestion.storage`` for
GCS upload. This module does not touch GCS itself so it can be unit-tested
with ``httpx.MockTransport``.

Rate limits enforced here are module-level so a single process cannot
accidentally hammer arXiv even if multiple coroutines call into it
concurrently. A trailing ``_throttle`` call blocks on an asyncio lock.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ingestion.config import IngestionSettings, get_settings
from ingestion.models import PaperMetadata, split_arxiv_id

log = logging.getLogger(__name__)

OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}

ARXIV_SRC_URL = "https://export.arxiv.org/src/{id}"
ARXIV_PDF_URL = "https://export.arxiv.org/pdf/{id}"


class ArxivError(RuntimeError):
    """Raised on non-retriable arXiv errors (e.g. 404 for a missing paper)."""


class ArxivCaptureError(RuntimeError):
    """Integrity/binding failure: must not silently degrade to another input."""


@dataclass(frozen=True)
class ArxivDownload:
    """Observed response bytes; an explicit URL is not a publication timestamp."""

    data: bytes
    kind: str
    requested_id: str
    requested_url: str
    resolved_url: str
    captured_at: str

    def provenance(self) -> dict[str, Any]:
        if not isinstance(self.data, bytes) or not self.data:
            raise ArxivCaptureError("arXiv capture requires nonempty immutable bytes")
        if not isinstance(self.captured_at, str) or len(self.captured_at) > 40:
            raise ArxivCaptureError("invalid arXiv capture observation timestamp")
        try:
            observed = datetime.fromisoformat(self.captured_at)
        except ValueError as exc:
            raise ArxivCaptureError("invalid arXiv capture observation timestamp") from exc
        if observed.tzinfo is None:
            raise ArxivCaptureError("arXiv capture observation timestamp requires timezone")
        work, version = split_arxiv_id(self.requested_id)
        _validate_artifact_url(self.requested_url, work, version, self.kind)
        _validate_artifact_url(self.resolved_url, work, version, self.kind)
        return {
            "kind": self.kind,
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "byte_length": len(self.data),
            "captured_at": observed.isoformat(),
            "requested_url": self.requested_url,
            "resolved_url": self.resolved_url,
            "source_version": version,
            "version_status": "explicit_version_url" if version else "unversioned_unknown",
            "version_available_at": None,
        }


def _validate_artifact_url(url: str, work: str, version: str | None, kind: str) -> None:
    """Fail closed on ambiguous redirects; never store query tokens/credentials."""
    value = urlsplit(url)
    prefixes = {"source": ("/src/", "/e-print/"), "pdf": ("/pdf/",)}
    if (
        len(url) > 256 or value.scheme != "https"
        or value.netloc not in {"arxiv.org", "export.arxiv.org"}
        or value.query or value.fragment or kind not in prefixes
    ):
        raise ArxivCaptureError("untrusted arXiv artifact response URL")
    path_id = next((value.path[len(p):] for p in prefixes[kind]
                    if value.path.startswith(p)), None)
    if kind == "pdf" and path_id and path_id.endswith(".pdf"):
        path_id = path_id[:-4]
    try:
        resolved_work, resolved_version = split_arxiv_id(path_id or "")
    except ValueError as exc:
        raise ArxivCaptureError("unrecognized arXiv artifact response path") from exc
    if resolved_work != work or (version is not None and resolved_version != version):
        raise ArxivCaptureError("arXiv artifact response identity/version mismatch")


@dataclass
class _Throttle:
    """Simple leaky-bucket: permits one call every ``delay`` seconds."""

    delay: float
    _lock: asyncio.Lock = None  # type: ignore[assignment]
    _last: float = 0.0

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_for = self._last + self.delay - now
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last = time.monotonic()


class ArxivClient:
    def __init__(self, settings: IngestionSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._meta_throttle = _Throttle(self.settings.arxiv_metadata_delay)
        self._file_throttle = _Throttle(self.settings.arxiv_file_delay)
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.settings.arxiv_user_agent},
            timeout=httpx.Timeout(60.0, connect=15.0),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ArxivClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # --- OAI-PMH ListRecords ------------------------------------------------

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    async def _oai_get(self, params: dict[str, str]) -> ET.Element:
        await self._meta_throttle.wait()
        r = await self._client.get(self.settings.arxiv_oai_url, params=params)
        # arXiv rate-limit signal: they return 503 with Retry-After on throttling.
        if r.status_code == 503:
            raise httpx.HTTPError(f"arXiv OAI-PMH 503 — retrying: {r.text[:200]}")
        r.raise_for_status()
        return ET.fromstring(r.content)

    async def list_records(
        self,
        from_date: date,
        until_date: date,
        *,
        max_records: int | None = None,
    ) -> AsyncIterator[PaperMetadata]:
        """Yield paper metadata for the given date range, filtered to
        cond-mat.supr-con (arXiv's OAI-PMH set API only supports
        physics:cond-mat as the finest grain, so we filter client-side).
        """
        params: dict[str, str] = {
            "verb": "ListRecords",
            "metadataPrefix": "arXiv",
            "set": self.settings.arxiv_set,
            "from": from_date.isoformat(),
            "until": until_date.isoformat(),
        }
        target = self.settings.arxiv_primary_category
        yielded = 0
        while True:
            root = await self._oai_get(params)
            # OAI-PMH errors come back inside <error code=...>
            err = root.find("oai:error", OAI_NS)
            if err is not None:
                code = err.get("code")
                if code == "noRecordsMatch":
                    log.info("arXiv OAI-PMH reports no records for %s..%s",
                             from_date, until_date)
                    return
                raise ArxivError(f"OAI-PMH error {code}: {err.text}")

            for record in root.iterfind("oai:ListRecords/oai:record", OAI_NS):
                meta = _parse_record(record)
                if meta is None:
                    continue
                # Client-side filter: primary category must be supr-con
                if target and meta.primary_category != target:
                    continue
                yield meta
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return

            token_el = root.find("oai:ListRecords/oai:resumptionToken", OAI_NS)
            token = (token_el.text or "").strip() if token_el is not None else ""
            if not token:
                return
            # When resuming, all other params must be dropped per OAI-PMH spec
            params = {"verb": "ListRecords", "resumptionToken": token}

    async def get_record(self, arxiv_id: str) -> PaperMetadata:
        """Fetch one arXiv metadata record by its stable identifier.

        This is the targeted counterpart to :meth:`list_records`, intended
        for audited gap backfills where replaying an entire historical date
        window would needlessly reprocess papers already present in SCLib.
        """
        arxiv_id, requested_version = split_arxiv_id(arxiv_id)

        root = await self._oai_get(
            {
                "verb": "GetRecord",
                "metadataPrefix": "arXiv",
                "identifier": f"oai:arXiv.org:{arxiv_id}",
            }
        )
        err = root.find("oai:error", OAI_NS)
        if err is not None:
            code = err.get("code")
            raise ArxivError(f"OAI-PMH error {code}: {err.text}")

        record = root.find("oai:GetRecord/oai:record", OAI_NS)
        if record is None:
            raise ArxivError(f"arXiv metadata record not found: {arxiv_id}")
        meta = _parse_record(record)
        if meta is None:
            raise ArxivError(f"arXiv metadata record deleted or empty: {arxiv_id}")
        if meta.arxiv_id != arxiv_id:
            raise ArxivCaptureError("arXiv metadata response identity mismatch")
        # OAI exposes current metadata, even when the body request selects vN.
        # Never label this title/abstract as metadata from that historical vN.
        meta.requested_version = requested_version
        return meta

    # --- File download ------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    async def _file_get(
        self, url: str, *, work: str, version: str | None, kind: str,
    ) -> httpx.Response:
        for _ in range(6):
            # Validate redirects BEFORE requesting them: credentials, query
            # tokens, non-arXiv hosts and a lost explicit version are refused.
            _validate_artifact_url(url, work, version, kind)
            await self._file_throttle.wait()
            r = await self._client.get(url, follow_redirects=False)
            if r.is_redirect:
                location = r.headers.get("location")
                if not location:
                    raise ArxivCaptureError("arXiv redirect has no location")
                url = str(r.url.join(location))
                continue
            if r.status_code == 404:
                raise ArxivError("arXiv artifact not found")
            r.raise_for_status()
            return r
        raise ArxivCaptureError("too many arXiv artifact redirects")

    async def _download_capture(self, arxiv_id: str, kind: str) -> ArxivDownload:
        work, version = split_arxiv_id(arxiv_id)
        requested_id = work + (version or "")
        template = ARXIV_SRC_URL if kind == "source" else ARXIV_PDF_URL
        url = template.format(id=requested_id)
        response = await self._file_get(url, work=work, version=version, kind=kind)
        if not response.content or "text/html" in response.headers.get("content-type", ""):
            raise ArxivError("arXiv returned an empty/non-artifact response")
        capture = ArxivDownload(
            data=response.content, kind=kind, requested_id=requested_id,
            requested_url=url, resolved_url=str(response.url),
            captured_at=datetime.now(timezone.utc).isoformat(),
        )
        capture.provenance()  # validate binding before any archive/write
        return capture

    async def download_source_capture(self, arxiv_id: str) -> ArxivDownload:
        capture = await self._download_capture(arxiv_id, "source")
        if capture.data[:5] == b"%PDF-":
            raise ArxivError(f"{arxiv_id}: /src/ returned a PDF (no LaTeX source available)")
        return capture

    async def download_pdf_capture(self, arxiv_id: str) -> ArxivDownload:
        capture = await self._download_capture(arxiv_id, "pdf")
        if capture.data[:5] != b"%PDF-":
            raise ArxivError("arXiv PDF endpoint returned non-PDF bytes")
        return capture

    async def download_source(self, arxiv_id: str) -> bytes:
        """Download .tar.gz LaTeX source. Raises ArxivError if unavailable.

        arXiv's ``/src/`` endpoint returns the PDF itself for papers whose
        withdrawn or pdf-only submissions have no tex source. We detect
        the PDF magic here and raise, so the caller's fallback path can
        record the PDF without polluting the ``src/`` prefix in GCS with
        PDF bytes that will later blow up the LaTeX parser.
        """
        return (await self.download_source_capture(arxiv_id)).data

    async def download_pdf(self, arxiv_id: str) -> bytes:
        return (await self.download_pdf_capture(arxiv_id)).data


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def _parse_record(record: ET.Element) -> PaperMetadata | None:
    meta_el = record.find("oai:metadata/arxiv:arXiv", OAI_NS)
    if meta_el is None:
        # Deleted records carry a header status="deleted" and no metadata.
        return None

    raw_id = _text(meta_el.find("arxiv:id", OAI_NS))
    if not raw_id:
        return None
    try:
        arxiv_id, _ = split_arxiv_id(raw_id)
    except ValueError:
        log.warning("ignoring malformed arXiv metadata identifier")
        return None

    title = _collapse_ws(_text(meta_el.find("arxiv:title", OAI_NS)))
    abstract = _collapse_ws(_text(meta_el.find("arxiv:abstract", OAI_NS)))

    authors: list[str] = []
    for author in meta_el.iterfind("arxiv:authors/arxiv:author", OAI_NS):
        keyname = _text(author.find("arxiv:keyname", OAI_NS))
        forenames = _text(author.find("arxiv:forenames", OAI_NS))
        full = " ".join(p for p in (forenames, keyname) if p).strip()
        if full:
            authors.append(full)

    categories_raw = _text(meta_el.find("arxiv:categories", OAI_NS)) or ""
    categories = categories_raw.split()
    primary = categories[0] if categories else None

    doi = _text(meta_el.find("arxiv:doi", OAI_NS))
    created = _text(meta_el.find("arxiv:created", OAI_NS))
    submitted = _parse_date(created)

    return PaperMetadata(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        abstract=abstract,
        date_submitted=submitted,
        categories=categories,
        primary_category=primary,
        doi=doi or None,
        metadata_modified_date=_parse_date(_text(meta_el.find("arxiv:updated", OAI_NS))),
        metadata_datestamp=_metadata_datestamp(
            _text(record.find("oai:header/oai:datestamp", OAI_NS))
        ),
        metadata_captured_at=datetime.now(timezone.utc).isoformat(),
        # Hash explicitly refers to ElementTree serialization, NOT wire bytes.
        metadata_sha256=hashlib.sha256(ET.tostring(record, encoding="utf-8")).hexdigest(),
    )


def _metadata_datestamp(value: str) -> str | None:
    value = value.strip()
    if len(value) > 32:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
