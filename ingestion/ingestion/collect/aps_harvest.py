"""APS Harvest API client — TDM metadata + BagIt downloader.

The APS counterpart of ``collect/arxiv_oai.py``. Two responsibilities:

1. ``get_article`` — fetch one article's authorized metadata (title,
   abstract, authors, bibliographic ref) as an ``ApsArticleMeta``.
2. ``download_bagit`` — fetch the BagIt ZIP (full-text XML + PDF + OCR)
   for TDM processing. These bytes are *transient* Licensed Materials:
   the caller (aps_pipeline via aps_storage) must delete them right after
   NER extraction. This module never writes to disk or GCS, so it stays
   unit-testable with ``httpx.MockTransport``.

Auth is **IP-whitelist only** — VPS2's egress IPs are registered with
APS, so no key/token is sent; access is granted by source IP. If a call
comes back 401/403, the running host's IP is not on the allow-list
(rather than a bad credential).

Rate limits are enforced module-locally via an asyncio throttle, exactly
like the arXiv client, so concurrent coroutines can't hammer APS.

NOTE (updated 2026-05-31 after the VPS2 live check): the metadata path
(/v2/journals/articles/{doi}) and its JSON field mapping are CONFIRMED
working (200). The full-text path is /v2/journals/articles/{doi}/
accepted_fulltext — APS serves no BagIt ZIP (there is no /bag endpoint).
That endpoint currently returns 401 (an APS full-text/TDM authorization
scope is still pending — separate from the metadata IP whitelist), so
the full-text response FORMAT (ZIP vs bare XML) is still unconfirmed;
``download_bagit`` assumes a ZIP and raises clearly if it isn't, leaving
a small adapter for later once we get a 200.
"""
from __future__ import annotations

import asyncio
import logging
import time
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
from ingestion.models import ApsArticleMeta, journal_from_doi

log = logging.getLogger(__name__)

#: BagIt packages are ZIP archives — used to sanity-check the download.
_ZIP_MAGIC = b"PK\x03\x04"


class ApsError(RuntimeError):
    """Non-retriable APS error (e.g. 404 for a missing DOI, or a 403 that
    means this host's IP is not on the APS allow-list)."""


@dataclass
class _Throttle:
    """Leaky-bucket: permits one call every ``delay`` seconds. Mirrors
    ``collect.arxiv_oai._Throttle`` so both sources behave identically."""

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


class ApsClient:
    def __init__(self, settings: IngestionSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._meta_throttle = _Throttle(self.settings.aps_metadata_delay)
        self._file_throttle = _Throttle(self.settings.aps_file_delay)
        self._client = httpx.AsyncClient(
            base_url=self.settings.aps_harvest_url,
            headers={
                "User-Agent": self.settings.aps_user_agent,
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(120.0, connect=15.0),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ApsClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # --- metadata ----------------------------------------------------------

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    async def _meta_get(self, path: str) -> dict[str, Any]:
        await self._meta_throttle.wait()
        r = await self._client.get(path, headers={"Accept": "application/json"})
        # APS throttling, if any, mirrors HTTP 503 + Retry-After.
        if r.status_code == 503:
            raise httpx.HTTPError(f"APS Harvest 503 — retrying: {r.text[:200]}")
        if r.status_code == 404:
            raise ApsError(f"404 not found: {path}")
        if r.status_code in (401, 403):
            raise ApsError(
                f"{r.status_code} from APS Harvest ({path}) — this host's IP "
                f"is likely not on the APS allow-list (auth is IP-whitelist)"
            )
        r.raise_for_status()
        return r.json()

    async def get_article(self, doi: str) -> ApsArticleMeta:
        """Fetch + parse one article's authorized metadata."""
        path = self.settings.aps_metadata_path.format(doi=doi)
        payload = await self._meta_get(path)
        return _parse_metadata(doi, payload)

    # --- BagIt full-text (transient) ---------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    async def download_bagit(self, doi: str) -> bytes:
        """Download the BagIt ZIP for ``doi``. Raises ApsError if missing
        or if the payload isn't a ZIP. The returned bytes are Licensed
        Materials — the caller must delete them after extraction."""
        await self._file_throttle.wait()
        path = self.settings.aps_bagit_path.format(doi=doi)
        r = await self._client.get(path, headers={"Accept": "application/zip"})
        if r.status_code == 404:
            raise ApsError(f"BagIt 404 not found: {path}")
        if r.status_code in (401, 403):
            raise ApsError(
                f"{r.status_code} downloading BagIt ({path}) — host IP likely "
                f"not on the APS allow-list"
            )
        r.raise_for_status()
        data = r.content
        if data[:4] != _ZIP_MAGIC:
            raise ApsError(
                f"{doi}: BagIt endpoint did not return a ZIP "
                f"(got {data[:16]!r})"
            )
        return data


# ---------------------------------------------------------------------------
# Metadata JSON parsing
# ---------------------------------------------------------------------------


def _parse_metadata(doi: str, payload: dict[str, Any]) -> ApsArticleMeta:
    """Map an APS Harvest metadata JSON object to ApsArticleMeta.

    Tolerant of a few key spellings because the exact schema is confirmed
    against a live sample later. The journal handle is derived from the
    DOI (authoritative) and only falls back to the JSON if the DOI token
    is unrecognised.
    """
    # APS Harvest sometimes nests the article under a top-level key.
    art = payload
    for key in ("article", "data", "result"):
        if isinstance(payload.get(key), dict):
            art = payload[key]
            break

    journal_full, journal_abbrev = journal_from_doi(doi)
    if journal_full is None:
        journal_full = _first_str(art, "journal", "journalName", "publication")
        journal_abbrev = _first_str(art, "journalAbbrev", "journalShortName")

    return ApsArticleMeta(
        doi=doi,
        title=_collapse_ws(_first_str(art, "title", "articleTitle") or ""),
        authors=_parse_authors(art),
        abstract=_collapse_ws(_first_str(art, "abstract", "summary") or ""),
        journal=journal_full,
        journal_abbrev=journal_abbrev,
        volume=_first_str(art, "volume", "vol"),
        issue=_first_str(art, "issue", "issueNumber"),
        article_id=_first_str(art, "articleId", "article_id", "eid", "pageStart"),
        page=_first_str(art, "page", "pageStart", "firstPage"),
        date_published=_parse_date(
            _first_str(art, "publicationDate", "publishedDate", "date", "issued")
        ),
        categories=_parse_categories(art),
    )


def _parse_authors(art: dict[str, Any]) -> list[str]:
    raw = art.get("authors") or art.get("author") or []
    out: list[str] = []
    for a in raw:
        if isinstance(a, str):
            name = a
        elif isinstance(a, dict):
            name = (
                a.get("name")
                or a.get("fullName")
                or " ".join(
                    p for p in (a.get("givenName"), a.get("surname")) if p
                )
                or " ".join(
                    p for p in (a.get("first"), a.get("last")) if p
                )
            )
        else:
            name = ""
        name = _collapse_ws(name or "")
        if name:
            out.append(name)
    return out


def _parse_categories(art: dict[str, Any]) -> list[str]:
    raw = (
        art.get("subjectAreas")
        or art.get("concepts")
        or art.get("categories")
        or art.get("subjects")
        or []
    )
    out: list[str] = []
    for c in raw:
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, dict):
            label = c.get("label") or c.get("name") or c.get("term")
            if label:
                out.append(str(label))
    return out


def _first_str(d: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _collapse_ws(s: str) -> str:
    import re

    return re.sub(r"\s+", " ", s).strip()


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    # Accept full ISO timestamps and plain dates; APS uses YYYY-MM-DD.
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    # Last resort: leading YYYY-MM-DD slice.
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
