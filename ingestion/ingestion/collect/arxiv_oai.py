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
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ingestion.config import IngestionSettings, get_settings
from ingestion.models import PaperMetadata

log = logging.getLogger(__name__)

OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}

ARXIV_SRC_URL = "https://export.arxiv.org/src/{id}"
ARXIV_PDF_URL = "https://export.arxiv.org/pdf/{id}"


class ArxivError(RuntimeError):
    """Raised on non-retriable arXiv errors (e.g. 404 for a missing paper)."""


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

    # --- File download ------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    async def _file_get(self, url: str) -> bytes:
        await self._file_throttle.wait()
        r = await self._client.get(url)
        if r.status_code == 404:
            raise ArxivError(f"404 not found: {url}")
        r.raise_for_status()
        return r.content

    async def download_source(self, arxiv_id: str) -> bytes:
        """Download .tar.gz LaTeX source. Raises ArxivError if unavailable.

        arXiv's ``/src/`` endpoint returns the PDF itself for papers whose
        withdrawn or pdf-only submissions have no tex source. We detect
        the PDF magic here and raise, so the caller's fallback path can
        record the PDF without polluting the ``src/`` prefix in GCS with
        PDF bytes that will later blow up the LaTeX parser.
        """
        data = await self._file_get(ARXIV_SRC_URL.format(id=arxiv_id))
        if data[:5] == b"%PDF-":
            raise ArxivError(
                f"{arxiv_id}: /src/ returned a PDF (no LaTeX source available)"
            )
        return data

    async def download_pdf(self, arxiv_id: str) -> bytes:
        return await self._file_get(ARXIV_PDF_URL.format(id=arxiv_id))


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"^(?:cond-mat/)?([\w\-./]+)$")


def _parse_record(record: ET.Element) -> PaperMetadata | None:
    meta_el = record.find("oai:metadata/arxiv:arXiv", OAI_NS)
    if meta_el is None:
        # Deleted records carry a header status="deleted" and no metadata.
        return None

    raw_id = _text(meta_el.find("arxiv:id", OAI_NS))
    if not raw_id:
        return None
    match = _ID_RE.match(raw_id.strip())
    arxiv_id = match.group(1) if match else raw_id.strip()

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
    )


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
