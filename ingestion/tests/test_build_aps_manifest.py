from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_aps_superconductivity_manifest.py"
_SPEC = importlib.util.spec_from_file_location("build_aps_manifest", _SCRIPT)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def test_harvest_filter_rejects_commentary_physics() -> None:
    item = {
        "volume": "18",
        "issue": None,
        "article-number": "143",
        "page": None,
    }
    assert _MOD.harvest_filter_reason(item, "Physics") == "excluded_journal:Physics"


def test_harvest_filter_rejects_physrevfocus_by_doi() -> None:
    item = {
        "doi": "10.1103/PhysRevFocus.3.1",
        "year": 1999,
        "volume": "3",
        "issue": None,
        "article-number": "1",
        "page": None,
    }
    assert _MOD.harvest_filter_reason(item, None) == (
        "excluded_doi_prefix:10.1103/PhysRevFocus."
    )


def test_harvest_filter_rejects_missing_bibliography() -> None:
    item = {
        "volume": None,
        "issue": None,
        "article-number": None,
        "page": None,
    }
    assert _MOD.harvest_filter_reason(item, "PRB") == "missing_volume"


def test_harvest_filter_rejects_modern_missing_locator() -> None:
    item = {
        "doi": "10.1103/PhysRevB.105.014501",
        "year": 2022,
        "volume": "105",
        "issue": "1",
        "article-number": None,
        "page": None,
    }
    assert _MOD.harvest_filter_reason(item, "PRB") == "missing_locator"


def test_harvest_filter_accepts_modern_article_number() -> None:
    item = {
        "volume": "112",
        "issue": "16",
        "article-number": "165416",
        "page": None,
    }
    assert _MOD.harvest_filter_reason(item, "PRB") is None


def test_harvest_filter_accepts_legacy_page_locator() -> None:
    item = {
        "volume": "33",
        "issue": "3",
        "article-number": None,
        "page": "2046-2052",
    }
    assert _MOD.harvest_filter_reason(item, "PRB") is None


def test_harvest_filter_accepts_legacy_missing_page_when_doi_has_locator() -> None:
    item = {
        "doi": "10.1103/PhysRevB.55.11100",
        "year": 1997,
        "volume": "55",
        "issue": "17",
        "article-number": None,
        "page": None,
    }
    assert _MOD.harvest_filter_reason(item, "PRB") is None


def test_harvest_filter_accepts_legacy_rapid_page_locator() -> None:
    item = {
        "doi": "10.1103/PhysRevA.59.R31",
        "published_date": "1999-01-01",
        "volume": "59",
        "issue": "1",
        "article-number": None,
        "page": None,
    }
    assert _MOD.harvest_filter_reason(item, "PRA") is None


def test_harvest_filter_accepts_legacy_correction_suffix() -> None:
    item = {
        "doi": "10.1103/PhysRevLett.56.996.2",
        "published_date": "1986-03-03",
        "volume": "56",
        "issue": "9",
        "article-number": None,
        "page": None,
    }
    assert _MOD.harvest_filter_reason(item, "PRL") is None
