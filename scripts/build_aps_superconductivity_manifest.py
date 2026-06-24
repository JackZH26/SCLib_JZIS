#!/usr/bin/env python3
"""Build an APS superconductivity DOI manifest and coverage report.

This script is deliberately a discovery/reporting tool. It does not ingest
papers and never downloads APS licensed full text. The output DOI list can be
fed to ``python -m ingestion.aps_batch`` after review.

Primary source:
  Crossref public metadata, filtered to APS prefix 10.1103 and journal articles.

Optional enrichment:
  If ``psql`` and DATABASE_URL are available, compare the DOI universe against
  the current SCLib ``papers`` table.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CROSSREF_BASE = "https://api.crossref.org/works"
APS_PREFIX_FILTER = "prefix:10.1103,type:journal-article"
USER_AGENT = "SCLib-JZIS/1.0 (mailto:jack@jzis.org)"
MAILTO = "jack@jzis.org"
DEFAULT_MIN_DATE = dt.date(1986, 1, 1)
DEFAULT_MAX_DATE = dt.date(2026, 12, 31)

CORE_QUERIES = [
    "superconductivity",
    "superconducting",
    "superconductor",
    "superconductors",
    "josephson",
    "andreev",
    "meissner",
    "cooper pair",
    "cuprate",
    "pnictide",
    "nickelate",
    "hydride",
    "magnesium diboride",
    "mgb2",
    "transmon",
    "squid",
    "unconventional superconductivity",
]

EXPANDED_QUERIES = CORE_QUERIES + [
    "topological superconductivity",
    "majorana superconductivity",
    "bcs superconductivity",
    "abrikosov vortex",
    "vortex lattice superconductor",
    "critical current josephson",
    "high temperature superconductivity",
    "heavy fermion superconductor",
    "organic superconductor",
    "charge-density-wave superconductor",
]

SELECT_FIELDS = ",".join(
    [
        "DOI",
        "title",
        "container-title",
        "short-container-title",
        "issued",
        "published-online",
        "published-print",
        "published",
        "volume",
        "issue",
        "article-number",
        "page",
        "resource",
        "URL",
        "subject",
        "score",
        "type",
        "abstract",
    ]
)

JOURNAL_ABBREV_BY_TITLE = {
    "Physical Review": "PR",
    "Physical Review Letters": "PRL",
    "Physical Review X": "PRX",
    "Reviews of Modern Physics": "RMP",
    "Physical Review A": "PRA",
    "Physical Review B": "PRB",
    "Physical Review C": "PRC",
    "Physical Review D": "PRD",
    "Physical Review E": "PRE",
    "Physical Review Applied": "PRApplied",
    "Physical Review Fluids": "PRFluids",
    "Physical Review Accelerators and Beams": "PRAB",
    "Physical Review Special Topics - Accelerators and Beams": "PRAB",
    "Physical Review Physics Education Research": "PRPER",
    "Physical Review Special Topics - Physics Education Research": "PRPER",
    "Physical Review Materials": "PRMaterials",
    "Physical Review Research": "PRResearch",
    "PRX Quantum": "PRXQuantum",
    "PRX Energy": "PRXEnergy",
    "PRX Life": "PRXLife",
    "Physics": "Physics",
}

P0_JOURNALS = {"PRB", "PRL", "PRX", "PRResearch", "PRMaterials"}
P1_JOURNALS = {"PRApplied", "RMP", "PRXQuantum", "PRA"}
EXCLUDED_HARVEST_JOURNALS = {"Physics", "PRPER"}
EXCLUDED_HARVEST_DOI_PREFIXES = ("10.1103/PhysRevFocus.",)
LEGACY_PAGE_DOI_MAX_YEAR = 2001

DOI_RE = re.compile(r"10\.1103/[A-Za-z0-9._;()/:+-]+", re.I)
APS_LEGACY_PAGE_DOI_RE = re.compile(
    r"^10\.1103/[A-Za-z][A-Za-z0-9]*\.\d+\.[A-Za-z]?\d+[A-Za-z]?(?:\.\d+)?$",
    re.I,
)
TAG_PATTERNS = {
    "superconduct": re.compile(r"\bsuperconduct\w*\b", re.I),
    "josephson": re.compile(r"\bjosephson\b", re.I),
    "andreev": re.compile(r"\bandreev\b", re.I),
    "meissner": re.compile(r"\bmeissner\b", re.I),
    "cooper_pair": re.compile(r"\bcooper[-\s]?pair\w*\b", re.I),
    "squid": re.compile(r"\bsquid\b|\bSQUID\b", re.I),
    "transmon": re.compile(r"\btransmon\w*\b", re.I),
    "cuprate": re.compile(r"\bcuprate\w*\b|copper[-\s]?oxide", re.I),
    "pnictide": re.compile(r"\bpnictide\w*\b|iron[-\s]?based", re.I),
    "nickelate": re.compile(r"\bnickelate\w*\b", re.I),
    "hydride": re.compile(r"\bhydride\w*\b", re.I),
    "mgb2": re.compile(r"\bmg\s*b\s*2\b|\bmgb2\b|magnesium diboride", re.I),
    "heavy_fermion": re.compile(r"heavy[-\s]?fermion", re.I),
    "organic": re.compile(r"\borganic\b", re.I),
    "topological": re.compile(r"\btopological\b|\bmajorana\b", re.I),
    "vortex": re.compile(r"\bvort(?:ex|ices)\b|\babrikosov\b", re.I),
    "tc": re.compile(r"\bT\s*c\b|\bcritical temperature\b|\btransition temperature\b", re.I),
    "pairing": re.compile(r"\bpairing\b|\bd[-\s]?wave\b|\bs[-\s]?wave\b|\bp[-\s]?wave\b", re.I),
    "charge_density_wave": re.compile(r"charge[-\s]?density[-\s]?wave|\bCDW\b", re.I),
}

MATERIAL_TAGS = {
    "cuprate",
    "pnictide",
    "nickelate",
    "hydride",
    "mgb2",
    "heavy_fermion",
    "organic",
    "tc",
    "charge_density_wave",
}
DEVICE_TAGS = {"josephson", "andreev", "squid", "transmon", "topological"}


def flatten_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(flatten_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(flatten_text(v) for v in value.values())
    if value is None:
        return ""
    return clean_markup(str(value))


def clean_markup(value: str) -> str:
    """Turn Crossref title/abstract fragments with HTML/MathML into text."""
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"/\s*e\s*m\s*p\s*h\s*>", " ", text, flags=re.I)
    return text


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def has_text(value: Any) -> bool:
    if value is None:
        return False
    return bool(collapse_ws(str(value)))


def parse_date(item: dict[str, Any]) -> str | None:
    for key in ("published-online", "published-print", "published", "issued"):
        raw = item.get(key)
        if not isinstance(raw, dict):
            continue
        parts = raw.get("date-parts")
        if not parts or not parts[0]:
            continue
        nums = [int(p) for p in parts[0] if isinstance(p, int)]
        if not nums:
            continue
        year = nums[0]
        month = nums[1] if len(nums) > 1 else 1
        day = nums[2] if len(nums) > 2 else 1
        try:
            return dt.date(year, month, day).isoformat()
        except ValueError:
            return f"{year:04d}"
    return None


def date_year(date_s: str | None) -> int | None:
    if not date_s:
        return None
    m = re.match(r"(\d{4})", date_s)
    return int(m.group(1)) if m else None


def item_year(item: dict[str, Any]) -> int | None:
    raw_year = item.get("year")
    if isinstance(raw_year, int):
        return raw_year
    if isinstance(raw_year, str) and raw_year.isdigit():
        return int(raw_year)
    published = item.get("published_date")
    if isinstance(published, str):
        return date_year(published)
    return None


def coerce_date(date_s: str | None) -> dt.date | None:
    if not date_s:
        return None
    try:
        return dt.date.fromisoformat(date_s)
    except ValueError:
        pass
    year = date_year(date_s)
    return dt.date(year, 1, 1) if year is not None else None


def in_publication_window(
    published_date: str | None,
    *,
    min_date: dt.date,
    max_date: dt.date,
) -> bool:
    published = coerce_date(published_date)
    if published is None:
        return False
    return min_date <= published <= max_date


def canonical_doi(item: dict[str, Any]) -> str | None:
    candidates = []
    resource = item.get("resource") or {}
    if isinstance(resource, dict):
        primary = resource.get("primary") or {}
        if isinstance(primary, dict):
            candidates.append(primary.get("URL"))
    candidates.append(item.get("URL"))
    candidates.append(item.get("DOI"))

    for raw in candidates:
        if not raw:
            continue
        text = urllib.parse.unquote(str(raw))
        m = DOI_RE.search(text)
        if m:
            return m.group(0).rstrip(".,;)]}")
    return None


def item_doi(item: dict[str, Any]) -> str | None:
    doi = item.get("doi") or item.get("DOI")
    if doi:
        text = urllib.parse.unquote(str(doi))
        m = DOI_RE.search(text)
        if m:
            return m.group(0).rstrip(".,;)]}")
    return canonical_doi(item)


def is_excluded_harvest_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi_lower = doi.lower()
    for prefix in EXCLUDED_HARVEST_DOI_PREFIXES:
        if doi_lower.startswith(prefix.lower()):
            return f"excluded_doi_prefix:{prefix}"
    return None


def has_legacy_page_locator(item: dict[str, Any]) -> bool:
    """Return True when old APS DOI syntax itself carries the page locator.

    Crossref often omits ``page`` for pre-2002 APS records even though the DOI
    has the canonical ``Journal.Volume.Page`` form and APS Harvest can retrieve
    it directly. Keep the modern metadata guardrails for newer records, where
    missing locators correlate with Harvest 404s.
    """
    year = item_year(item)
    if year is None or year > LEGACY_PAGE_DOI_MAX_YEAR:
        return False
    doi = item_doi(item)
    return bool(doi and APS_LEGACY_PAGE_DOI_RE.fullmatch(doi))


def journal_title(item: dict[str, Any]) -> str:
    title = flatten_text(item.get("container-title"))
    return collapse_ws(title)


def journal_abbrev(item: dict[str, Any]) -> str | None:
    title = journal_title(item)
    if title in JOURNAL_ABBREV_BY_TITLE:
        return JOURNAL_ABBREV_BY_TITLE[title]
    short = collapse_ws(flatten_text(item.get("short-container-title")))
    short_map = {
        "Phys. Rev.": "PR",
        "Phys. Rev. Lett.": "PRL",
        "Phys. Rev. X": "PRX",
        "Rev. Mod. Phys.": "RMP",
        "Phys. Rev. A": "PRA",
        "Phys. Rev. B": "PRB",
        "Phys. Rev. C": "PRC",
        "Phys. Rev. D": "PRD",
        "Phys. Rev. E": "PRE",
    }
    return short_map.get(short)


def matched_tags(item: dict[str, Any]) -> list[str]:
    text = " ".join(
        [
            flatten_text(item.get("title")),
            flatten_text(item.get("subject")),
            flatten_text(item.get("abstract")),
        ]
    )
    text = collapse_ws(text)
    return sorted(tag for tag, pat in TAG_PATTERNS.items() if pat.search(text))


def should_keep(tags: list[str]) -> bool:
    if "superconduct" in tags:
        return True
    if {"josephson", "andreev", "meissner", "cooper_pair", "squid", "transmon"} & set(tags):
        return True
    if {"cuprate", "pnictide", "nickelate", "mgb2"} & set(tags):
        return True
    if "hydride" in tags and ({"tc", "pairing", "vortex"} & set(tags)):
        return True
    if "topological" in tags and ({"josephson", "andreev", "pairing"} & set(tags)):
        return True
    return False


def candidate_class(tags: list[str]) -> str:
    tagset = set(tags)
    if tagset & MATERIAL_TAGS:
        if "superconduct" in tagset or tagset & {"cuprate", "pnictide", "nickelate", "mgb2"}:
            return "materials_tc_likely"
    if tagset & DEVICE_TAGS:
        return "devices_or_theory"
    if "superconduct" in tagset:
        return "general_superconductivity"
    return "keyword_candidate"


def priority_for(abbrev: str | None, cls: str) -> str:
    if abbrev in P0_JOURNALS:
        return "P0" if cls != "devices_or_theory" else "P1"
    if abbrev in P1_JOURNALS:
        return "P1"
    return "P2"


def harvest_filter_reason(item: dict[str, Any], abbrev: str | None) -> str | None:
    """Return why a Crossref row should not enter the Harvest ingest manifest.

    Two known noisy classes are filtered here:

    1. Commentary/non-research APS venues such as ``Physics`` and
       ``PhysRevFocus`` that are not part of the full-text Harvest ingest
       target set.
    2. Online DOI registrations that exist in Crossref but do not yet have the
       final APS article bibliographic identity needed for Harvest retrieval.
       Empirically these correlate with missing volume/issue metadata and cause
       stable Harvest 404s. Pre-2002 APS page-style DOI records are an
       exception: Crossref frequently omits ``page``, but the DOI itself
       encodes the page locator and Harvest retrieves these packages.
    """

    if abbrev in EXCLUDED_HARVEST_JOURNALS:
        return f"excluded_journal:{abbrev}"
    doi_exclusion = is_excluded_harvest_doi(item_doi(item))
    if doi_exclusion:
        return doi_exclusion
    if not has_text(item.get("volume")):
        return "missing_volume"
    if not has_text(item.get("issue")):
        return "missing_issue"
    if not (has_text(item.get("article-number")) or has_text(item.get("page"))):
        if has_legacy_page_locator(item):
            return None
        return "missing_locator"
    return None


def crossref_get(params: dict[str, str], timeout: int = 60) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{CROSSREF_BASE}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def fetch_query(
    term: str,
    *,
    rows: int,
    max_pages: int,
    sleep_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    total = None
    page = 0
    while True:
        page += 1
        offset = (page - 1) * rows
        params = {
            "filter": APS_PREFIX_FILTER,
            "query.bibliographic": term,
            "rows": str(rows),
            "offset": str(offset),
            "mailto": MAILTO,
            "select": SELECT_FIELDS,
        }
        data = crossref_get(params)
        message = data.get("message", {})
        if total is None:
            total = message.get("total-results")
        batch = message.get("items") or []
        items.extend(batch)
        if not batch:
            break
        if total is not None and len(items) >= int(total):
            break
        if page >= max_pages:
            break
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    summary = {
        "query": term,
        "reported_total": total,
        "pages_fetched": page,
        "items_fetched": len(items),
        "truncated": bool(total and len(items) < int(total)),
    }
    return items, summary


def build_candidates(
    query_terms: list[str],
    *,
    rows: int,
    max_pages: int,
    sleep_seconds: float,
    min_date: dt.date,
    max_date: dt.date,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    candidates: dict[str, dict[str, Any]] = {}
    query_summaries: list[dict[str, Any]] = []
    for term in query_terms:
        print(f"[crossref] query={term!r}", flush=True)
        items, summary = fetch_query(
            term,
            rows=rows,
            max_pages=max_pages,
            sleep_seconds=sleep_seconds,
        )
        kept = 0
        kept_in_window = 0
        rejected_not_harvest_ready = 0
        for item in items:
            doi = canonical_doi(item)
            if not doi:
                continue
            tags = matched_tags(item)
            if not should_keep(tags):
                continue
            published = parse_date(item)
            if not in_publication_window(published, min_date=min_date, max_date=max_date):
                continue
            abbrev = journal_abbrev(item)
            if harvest_filter_reason(item, abbrev):
                rejected_not_harvest_ready += 1
                continue
            key = doi.lower()
            title = collapse_ws(flatten_text(item.get("title")))
            cls = candidate_class(tags)
            rec = candidates.get(key)
            if rec is None:
                rec = {
                    "doi": doi,
                    "doi_lower": key,
                    "title": title,
                    "journal": journal_title(item),
                    "journal_abbrev": abbrev,
                    "published_date": published,
                    "year": date_year(published),
                    "volume": item.get("volume"),
                    "issue": item.get("issue"),
                    "article_number": item.get("article-number"),
                    "page": item.get("page"),
                    "url": item.get("URL"),
                    "aps_url": (item.get("resource") or {}).get("primary", {}).get("URL")
                    if isinstance(item.get("resource"), dict)
                    else None,
                    "crossref_score_max": item.get("score"),
                    "discovery_sources": ["crossref"],
                    "discovery_queries": [],
                    "matched_terms": tags,
                    "candidate_class": cls,
                    "priority": priority_for(abbrev, cls),
                    "existing_sources": [],
                    "existing_paper_ids": [],
                    "existing_aps": False,
                    "arxiv_overlap": False,
                    "related_arxiv_ids": [],
                }
                candidates[key] = rec
            rec["discovery_queries"].append(term)
            rec["matched_terms"] = sorted(set(rec["matched_terms"]) | set(tags))
            try:
                rec["crossref_score_max"] = max(
                    float(rec.get("crossref_score_max") or 0),
                    float(item.get("score") or 0),
                )
            except (TypeError, ValueError):
                pass
            kept += 1
            kept_in_window += 1
        summary["items_kept_after_local_filter"] = kept_in_window
        summary["rejected_not_harvest_ready"] = rejected_not_harvest_ready
        summary["unique_candidates_after_query"] = len(candidates)
        query_summaries.append(summary)
        print(
            f"[crossref] fetched={summary['items_fetched']} kept={kept} "
            f"in_window={kept_in_window} harvest_rejects={rejected_not_harvest_ready} "
            f"unique={len(candidates)}",
            flush=True,
        )
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return candidates, query_summaries


def parse_database_url_from_env_file(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DATABASE_URL":
            return value.strip().strip("'\"")
    return None


def psql_db_coverage(database_url: str | None) -> dict[str, dict[str, Any]] | None:
    if not database_url or shutil.which("psql") is None:
        return None
    sql = r"""
SELECT lower(doi) AS doi_lower,
       string_agg(id, ',' ORDER BY id) AS paper_ids,
       string_agg(DISTINCT source, ',' ORDER BY source) AS sources,
       string_agg(DISTINCT COALESCE(arxiv_id, ''), ',' ORDER BY COALESCE(arxiv_id, '')) AS arxiv_ids
FROM papers
WHERE doi ILIKE '10.1103/%'
GROUP BY lower(doi)
ORDER BY lower(doi);
"""
    cmd = ["psql", database_url, "-X", "-q", "-A", "-F", "\t", "-c", sql]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=120)
    except Exception as exc:
        print(f"[db] psql coverage skipped: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(f"[db] psql coverage skipped: {proc.stderr.strip()}", file=sys.stderr)
        return None
    lines = [line for line in proc.stdout.splitlines() if line and not line.startswith("(")]
    if not lines:
        return {}
    header = lines[0].split("\t")
    coverage: dict[str, dict[str, Any]] = {}
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != len(header):
            continue
        row = dict(zip(header, parts))
        key = row["doi_lower"]
        sources = [s for s in row.get("sources", "").split(",") if s]
        paper_ids = [s for s in row.get("paper_ids", "").split(",") if s]
        arxiv_ids = [s for s in row.get("arxiv_ids", "").split(",") if s]
        coverage[key] = {
            "sources": sources,
            "paper_ids": paper_ids,
            "arxiv_ids": arxiv_ids,
        }
    return coverage


def apply_db_coverage(candidates: dict[str, dict[str, Any]], coverage: dict[str, dict[str, Any]]) -> None:
    for key, db in coverage.items():
        rec = candidates.get(key)
        if rec is None:
            continue
        sources = db.get("sources") or []
        rec["existing_sources"] = sources
        rec["existing_paper_ids"] = db.get("paper_ids") or []
        rec["existing_aps"] = "aps" in sources
        rec["arxiv_overlap"] = "arxiv" in sources
        rec["related_arxiv_ids"] = db.get("arxiv_ids") or []


def sorted_records(candidates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    class_rank = {
        "materials_tc_likely": 0,
        "general_superconductivity": 1,
        "devices_or_theory": 2,
        "keyword_candidate": 3,
    }
    return sorted(
        candidates.values(),
        key=lambda r: (
            priority_rank.get(r.get("priority"), 9),
            class_rank.get(r.get("candidate_class"), 9),
            r.get("year") or 9999,
            r.get("journal_abbrev") or "",
            r.get("doi_lower") or "",
        ),
    )


def write_outputs(
    records: list[dict[str, Any]],
    query_summaries: list[dict[str, Any]],
    out_dir: Path,
    *,
    query_set: str,
    db_coverage_available: bool,
    min_date: dt.date,
    max_date: dt.date,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "aps_superconductivity_manifest.jsonl"
    doi_txt = out_dir / "aps_superconductivity_dois.txt"
    csv_path = out_dir / "aps_superconductivity_manifest.csv"
    query_csv = out_dir / "crossref_query_summary.csv"
    report = out_dir / "APS_SUPERCONDUCTIVITY_COVERAGE.md"

    with manifest.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True))
            f.write("\n")

    doi_txt.write_text("\n".join(rec["doi"] for rec in records) + "\n", encoding="utf-8")

    fieldnames = [
        "doi",
        "title",
        "journal_abbrev",
        "journal",
        "year",
        "published_date",
        "volume",
        "issue",
        "article_number",
        "page",
        "priority",
        "candidate_class",
        "matched_terms",
        "discovery_queries",
        "existing_aps",
        "arxiv_overlap",
        "existing_sources",
        "existing_paper_ids",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            row = dict(rec)
            row["matched_terms"] = ",".join(rec.get("matched_terms") or [])
            row["discovery_queries"] = ",".join(rec.get("discovery_queries") or [])
            row["existing_sources"] = ",".join(rec.get("existing_sources") or [])
            row["existing_paper_ids"] = ",".join(rec.get("existing_paper_ids") or [])
            writer.writerow({k: row.get(k) for k in fieldnames})

    with query_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "query",
                "reported_total",
                "pages_fetched",
                "items_fetched",
                "items_kept_after_local_filter",
                "unique_candidates_after_query",
                "truncated",
            ],
        )
        writer.writeheader()
        for row in query_summaries:
            writer.writerow(row)

    report.write_text(
        render_report(
            records,
            query_summaries,
            query_set,
            db_coverage_available,
            min_date=min_date,
            max_date=max_date,
        ),
        encoding="utf-8",
    )
    return {
        "manifest": manifest,
        "doi_txt": doi_txt,
        "csv": csv_path,
        "query_csv": query_csv,
        "report": report,
    }


def top_counts(counter: Counter[str], n: int = 20) -> list[tuple[str, int]]:
    return [(k or "(unknown)", v) for k, v in counter.most_common(n)]


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(out)


def render_report(
    records: list[dict[str, Any]],
    query_summaries: list[dict[str, Any]],
    query_set: str,
    db_coverage_available: bool,
    *,
    min_date: dt.date,
    max_date: dt.date,
) -> str:
    generated = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    by_journal = Counter(r.get("journal_abbrev") or "(unknown)" for r in records)
    by_year = Counter(str(r.get("year") or "(unknown)") for r in records)
    by_priority = Counter(r.get("priority") for r in records)
    by_class = Counter(r.get("candidate_class") for r in records)
    rejected_not_harvest_ready = sum(int(row.get("rejected_not_harvest_ready") or 0)
                                     for row in query_summaries)
    existing_aps = sum(1 for r in records if r.get("existing_aps"))
    arxiv_overlap = sum(1 for r in records if r.get("arxiv_overlap"))
    pending = len(records) - existing_aps if db_coverage_available else "n/a"

    lines = [
        "# APS Superconductivity DOI Manifest Coverage",
        "",
        f"- Generated UTC: `{generated}`",
        f"- Query set: `{query_set}`",
        f"- Publication window: `{min_date.isoformat()}` to `{max_date.isoformat()}`",
        "- Source: Crossref public metadata filtered to APS DOI prefix `10.1103` and `type:journal-article`.",
        "- Scope note: this is a DOI discovery manifest only. It does not ingest papers or download APS licensed full text.",
        f"- Database coverage: `{'available' if db_coverage_available else 'not available in this run'}`",
        "",
        "## Summary",
        "",
        markdown_table(
            ["Metric", "Value"],
            [
                ["candidate DOI records", len(records)],
                ["Crossref rows rejected as not Harvest-ready", rejected_not_harvest_ready],
                ["already ingested as APS", existing_aps if db_coverage_available else "n/a"],
                ["arXiv DOI overlap", arxiv_overlap if db_coverage_available else "n/a"],
                ["pending APS DOI candidates", pending],
            ],
        ),
        "",
        "## By Priority",
        "",
        markdown_table(["Priority", "Count"], [[k, v] for k, v in top_counts(by_priority)]),
        "",
        "## By Candidate Class",
        "",
        markdown_table(["Class", "Count"], [[k, v] for k, v in top_counts(by_class)]),
        "",
        "## Top Journals",
        "",
        markdown_table(["Journal", "Count"], [[k, v] for k, v in top_counts(by_journal, 30)]),
        "",
        "## Year Distribution",
        "",
        markdown_table(
            ["Year", "Count"],
            [[k, by_year[k]] for k in sorted(by_year, key=lambda x: (x == '(unknown)', x))],
        ),
        "",
        "## Crossref Query Coverage",
        "",
        markdown_table(
            [
                "Query",
                "Reported total",
                "Fetched",
                "Kept",
                "Rejected not Harvest-ready",
                "Unique after query",
                "Truncated",
            ],
            [
                [
                    row.get("query"),
                    row.get("reported_total"),
                    row.get("items_fetched"),
                    row.get("items_kept_after_local_filter"),
                    row.get("rejected_not_harvest_ready"),
                    row.get("unique_candidates_after_query"),
                    row.get("truncated"),
                ]
                for row in query_summaries
            ],
        ),
        "",
        "## Recommended Next Step",
        "",
        "Run the 500-paper calibration batch from `aps_superconductivity_dois.txt`, selecting only records that are not already `existing_aps=true` when database coverage is available. After that batch, run material aggregation and the scoped data audit before expanding to larger waves.",
        "",
        "## Caveats",
        "",
        "- APS subject browse pages were not used in this run because local non-browser requests are Cloudflare-challenged; Crossref is used as the durable public metadata source.",
        "- Crossref search is relevance based, so this script performs a second local keyword filter and records matched terms for auditability.",
        "- The manifest excludes `Physics`/`PRPER` commentary-style venues and rows missing the final APS volume/issue/locator metadata, because those entries have been observed to produce stable Harvest 404s.",
        "- For final production coverage, rerun this script on VPS2 with `DATABASE_URL` and `psql` available so the existing APS/arXiv overlap columns are filled.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Default: audit/aps_manifest_<UTC timestamp>",
    )
    parser.add_argument(
        "--query-set",
        choices=["core", "expanded"],
        default="core",
        help="Crossref query set. Expanded is slower and noisier.",
    )
    parser.add_argument("--rows", type=int, default=1000, help="Crossref rows per cursor page")
    parser.add_argument(
        "--max-pages-per-query",
        type=int,
        default=30,
        help="Safety cap for Crossref cursor pages per query",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.35,
        help="Seconds to sleep between Crossref page/query calls",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional Postgres DATABASE_URL for existing APS/arXiv coverage",
    )
    parser.add_argument(
        "--min-date",
        default=DEFAULT_MIN_DATE.isoformat(),
        help=f"Earliest publication date to keep (default: {DEFAULT_MIN_DATE.isoformat()})",
    )
    parser.add_argument(
        "--max-date",
        default=DEFAULT_MAX_DATE.isoformat(),
        help=f"Latest publication date to keep (default: {DEFAULT_MAX_DATE.isoformat()})",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip database coverage even if DATABASE_URL and psql are available",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or Path("audit") / f"aps_manifest_{timestamp}"
    query_terms = CORE_QUERIES if args.query_set == "core" else EXPANDED_QUERIES
    min_date = dt.date.fromisoformat(args.min_date)
    max_date = dt.date.fromisoformat(args.max_date)

    candidates, query_summaries = build_candidates(
        query_terms,
        rows=args.rows,
        max_pages=args.max_pages_per_query,
        sleep_seconds=args.sleep,
        min_date=min_date,
        max_date=max_date,
    )

    coverage = None
    if not args.no_db:
        db_url = (
            args.database_url
            or os.environ.get("DATABASE_URL")
            or parse_database_url_from_env_file(Path(".env"))
        )
        coverage = psql_db_coverage(db_url)
        if coverage is not None:
            print(f"[db] loaded coverage for {len(coverage)} APS-prefix DOIs", flush=True)
            apply_db_coverage(candidates, coverage)
        else:
            print("[db] coverage not available in this environment", flush=True)

    records = sorted_records(candidates)
    paths = write_outputs(
        records,
        query_summaries,
        out_dir,
        query_set=args.query_set,
        db_coverage_available=coverage is not None,
        min_date=min_date,
        max_date=max_date,
    )
    print("[done] wrote outputs:")
    for name, path in paths.items():
        print(f"  {name}: {path}")
    print(f"[done] candidate DOI records: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
