"""Unit tests for ingestion.collect.aps_harvest + APS models.

No network: the ApsClient's httpx transport is swapped for a
MockTransport. Fast enough to run on every commit.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import httpx
import pytest

from ingestion.collect.aps_harvest import ApsClient, ApsError, _parse_metadata
from ingestion.models import ApsArticleMeta, journal_from_doi


# === journal_from_doi (pure) ===============================================

def test_journal_from_doi_prb():
    full, abbrev = journal_from_doi("10.1103/PhysRevB.108.054515")
    assert full == "Physical Review B"
    assert abbrev == "PRB"


def test_journal_from_doi_handles_prefixes_and_case():
    assert journal_from_doi("https://doi.org/10.1103/PhysRevLett.130.236002")[1] == "PRL"
    assert journal_from_doi("doi:10.1103/RevModPhys.95.011001")[1] == "RMP"
    assert journal_from_doi("10.1103/PhysRevX.13.041027")[1] == "PRX"
    assert journal_from_doi("10.1103/PRXQuantum.4.040314")[1] == "PRXQuantum"


def test_journal_from_doi_non_aps_returns_none():
    assert journal_from_doi("10.1038/nature12373") == (None, None)
    assert journal_from_doi("") == (None, None)
    assert journal_from_doi("10.1103/UnknownJournal.1.1") == (None, None)


# === ApsArticleMeta helpers ================================================

def test_paper_id_and_doi_slug():
    m = ApsArticleMeta(doi="10.1103/PhysRevB.108.054515", title="t",
                       authors=[], abstract="a")
    assert m.paper_id == "aps:10.1103/PhysRevB.108.054515"
    assert m.doi_slug == "10.1103_PhysRevB.108.054515"


def test_publication_ref_drops_empty():
    m = ApsArticleMeta(
        doi="10.1103/PhysRevB.108.054515", title="t", authors=[], abstract="a",
        volume="108", article_id="054515", date_published=date(2023, 8, 15),
    )
    ref = m.publication_ref()
    assert ref == {"volume": "108", "article_id": "054515",
                   "published_date": "2023-08-15"}
    assert "issue" not in ref  # None dropped


def test_to_from_dict_roundtrip():
    m = ApsArticleMeta(
        doi="10.1103/PhysRevB.1.1", title="T", authors=["A B"], abstract="x",
        journal="Physical Review B", journal_abbrev="PRB", volume="1",
        date_published=date(2020, 1, 2), categories=["Superconductivity"],
    )
    m2 = ApsArticleMeta.from_dict(m.to_dict())
    assert m2 == m


# === _parse_metadata (tolerant JSON mapping) ===============================

def test_parse_metadata_derives_journal_from_doi():
    doi = "10.1103/PhysRevB.108.054515"
    payload = {
        "title": "Superconductivity in   FeSe",
        "abstract": "We report\nTc = 9 K.",
        "authors": [{"name": "Jane Doe"}, {"givenName": "John", "surname": "Roe"}],
        "volume": "108",
        "articleId": "054515",
        "publicationDate": "2023-08-15",
        "subjectAreas": [{"label": "Superconductivity"}],
        # journal name intentionally absent — must come from the DOI
    }
    m = _parse_metadata(doi, payload)
    assert m.journal == "Physical Review B"
    assert m.journal_abbrev == "PRB"
    assert m.title == "Superconductivity in FeSe"   # ws collapsed
    assert m.abstract == "We report Tc = 9 K."
    assert m.authors == ["Jane Doe", "John Roe"]
    assert m.volume == "108"
    assert m.article_id == "054515"
    assert m.date_published == date(2023, 8, 15)
    assert m.categories == ["Superconductivity"]


def test_parse_metadata_nested_under_article_key():
    doi = "10.1103/PhysRevLett.130.236002"
    payload = {"article": {"title": "X", "abstract": "y", "author": ["A One"]}}
    m = _parse_metadata(doi, payload)
    assert m.title == "X"
    assert m.authors == ["A One"]
    assert m.journal_abbrev == "PRL"


# === ApsClient (MockTransport, no network) =================================

def _mock_client(handler) -> ApsClient:
    c = ApsClient()
    c._client = httpx.AsyncClient(
        base_url="https://harvest.aps.org",
        transport=httpx.MockTransport(handler),
    )
    # Zero the throttles so tests don't sleep.
    c._meta_throttle.delay = 0.0
    c._file_throttle.delay = 0.0
    return c


@pytest.mark.asyncio
async def test_get_article_happy_path():
    doi = "10.1103/PhysRevB.108.054515"

    def handler(request: httpx.Request) -> httpx.Response:
        assert doi in str(request.url)
        return httpx.Response(200, json={
            "title": "T", "abstract": "a", "authors": [{"name": "N"}],
        })

    async with _mock_client(handler) as c:
        m = await c.get_article(doi)
    assert m.doi == doi
    assert m.journal_abbrev == "PRB"
    assert m.authors == ["N"]


@pytest.mark.asyncio
async def test_get_article_404_raises_apserror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    async with _mock_client(handler) as c:
        with pytest.raises(ApsError):
            await c.get_article("10.1103/PhysRevB.1.1")


@pytest.mark.asyncio
async def test_get_article_403_flags_ip_allowlist():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    async with _mock_client(handler) as c:
        with pytest.raises(ApsError, match="allow-list"):
            await c.get_article("10.1103/PhysRevB.1.1")


@pytest.mark.asyncio
async def test_download_bagit_returns_zip_bytes():
    # Build a tiny valid zip in memory.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bag-info.txt", "x")
    zip_bytes = buf.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=zip_bytes)

    async with _mock_client(handler) as c:
        data = await c.download_bagit("10.1103/PhysRevB.1.1")
    assert data[:4] == b"PK\x03\x04"
    # Round-trips as a real zip.
    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == ["bag-info.txt"]


@pytest.mark.asyncio
async def test_download_bagit_rejects_non_zip():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not a zip</html>")

    async with _mock_client(handler) as c:
        with pytest.raises(ApsError, match="did not return a ZIP"):
            await c.download_bagit("10.1103/PhysRevB.1.1")
