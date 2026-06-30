#!/usr/bin/env python3
"""Backfill APS paper geography from transient JATS front matter.

This is the APS counterpart to ``scripts/backfill_paper_geo.py``. It is
intentionally narrower than the arXiv flow:

* fetch the APS BagIt ZIP through the approved Harvest endpoint;
* extract it only inside ``TempBagit``;
* parse JATS ``<front>/<article-meta>/<aff>`` affiliation elements;
* for older no-JATS packages, scan only the transient OCR front matter
  for low-confidence country/region signals;
* persist only derived structured geography fields;
* force-delete the temp directory and write a TDM audit row.

It never stores BagIt ZIPs, XML, PDFs, OCR, or article prose.

Run on VPS2 from the SCLib repo root:

    docker compose run --rm ingestion \\
      python /app/ASP_SC_ScopeReview/scripts/backfill_aps_paper_geo.py --limit 100

Then rerun the freeze preflight. A full pass over 28k APS papers is rate
limited by ``APS_FILE_DELAY`` and is expected to take many hours.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import re
import sys
import time
from typing import Any
import xml.etree.ElementTree as ET

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "ingestion"):
    sp = str(path)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from ingestion.aps_storage import TdmAudit, TempBagit, write_audit_log  # noqa: E402
from ingestion.collect.aps_harvest import ApsClient  # noqa: E402
from ingestion.index.indexer import _session_factory, dispose, upsert_paper_geo  # noqa: E402
from ingestion.parse.aps_xml import find_fulltext_ocr, find_fulltext_xml, _replace_html_entities  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_aps_geo")

METHOD = "aps_geo_jats_aff_v1"
COUNTRY_NORMALIZATION = "aps_geo_country_aliases_v1"


@dataclass(frozen=True, slots=True)
class PaperRow:
    paper_id: str
    doi: str
    year: int | None


@dataclass(frozen=True, slots=True)
class CountryHit:
    canonical: str
    start: int
    end: int
    alias: str


# Common APS author-affiliation country/region aliases. The goal is stable,
# auditable normalization for manuscript geography, not a gazetteer.
_COUNTRY_ALIAS_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("USA", ("United States of America", "United States", "U.S.A.", "U.S.", "USA")),
    ("UK", ("United Kingdom", "Great Britain", "England", "Scotland", "Wales", "U.K.", "UK")),
    ("China", ("People's Republic of China", "P. R. China", "PR China", "P.R. China", "China")),
    ("Hong Kong", ("Hong Kong SAR", "Hong Kong")),
    ("Macau", ("Macao", "Macau")),
    ("Taiwan", ("Republic of China", "R.O.C.", "Taiwan")),
    ("South Korea", ("Republic of Korea", "South Korea", "Korea")),
    ("North Korea", ("DPRK", "North Korea")),
    ("Japan", ("Japan",)),
    ("Germany", ("Federal Republic of Germany", "Germany", "Deutschland")),
    ("France", ("France",)),
    ("Italy", ("Italy",)),
    ("Spain", ("Spain",)),
    ("Portugal", ("Portugal",)),
    ("Netherlands", ("The Netherlands", "Netherlands", "Holland")),
    ("Belgium", ("Belgium",)),
    ("Switzerland", ("Switzerland", "Suisse", "Schweiz")),
    ("Austria", ("Austria",)),
    ("Sweden", ("Sweden",)),
    ("Norway", ("Norway",)),
    ("Denmark", ("Denmark",)),
    ("Finland", ("Finland",)),
    ("Iceland", ("Iceland",)),
    ("Ireland", ("Ireland",)),
    ("Poland", ("Poland",)),
    ("Czech Republic", ("Czech Republic", "Czechia")),
    ("Slovakia", ("Slovakia",)),
    ("Hungary", ("Hungary",)),
    ("Romania", ("Romania",)),
    ("Bulgaria", ("Bulgaria",)),
    ("Greece", ("Greece",)),
    ("Croatia", ("Croatia",)),
    ("Slovenia", ("Slovenia",)),
    ("Serbia", ("Serbia",)),
    ("Ukraine", ("Ukraine",)),
    ("Belarus", ("Belarus",)),
    ("Russia", ("Russian Federation", "Russia", "USSR")),
    ("Estonia", ("Estonia",)),
    ("Latvia", ("Latvia",)),
    ("Lithuania", ("Lithuania",)),
    ("Canada", ("Canada",)),
    ("Mexico", ("Mexico",)),
    ("Brazil", ("Brazil", "Brasil")),
    ("Argentina", ("Argentina",)),
    ("Chile", ("Chile",)),
    ("Colombia", ("Colombia",)),
    ("Peru", ("Peru",)),
    ("Uruguay", ("Uruguay",)),
    ("Venezuela", ("Venezuela",)),
    ("Australia", ("Australia",)),
    ("New Zealand", ("New Zealand",)),
    ("India", ("India",)),
    ("Pakistan", ("Pakistan",)),
    ("Bangladesh", ("Bangladesh",)),
    ("Sri Lanka", ("Sri Lanka",)),
    ("Singapore", ("Singapore",)),
    ("Malaysia", ("Malaysia",)),
    ("Thailand", ("Thailand",)),
    ("Vietnam", ("Viet Nam", "Vietnam")),
    ("Indonesia", ("Indonesia",)),
    ("Philippines", ("Philippines",)),
    ("Israel", ("Israel",)),
    ("Turkey", ("Turkey", "Turkiye")),
    ("Iran", ("Islamic Republic of Iran", "Iran")),
    ("Saudi Arabia", ("Saudi Arabia",)),
    ("United Arab Emirates", ("United Arab Emirates", "UAE")),
    ("Qatar", ("Qatar",)),
    ("Egypt", ("Egypt",)),
    ("South Africa", ("South Africa",)),
    ("Morocco", ("Morocco",)),
    ("Tunisia", ("Tunisia",)),
)

_ALIAS_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = []
for canonical, aliases in _COUNTRY_ALIAS_GROUPS:
    for alias in aliases:
        body = re.escape(alias).replace(r"\ ", r"\s+")
        _ALIAS_PATTERNS.append((
            canonical,
            alias,
            re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.IGNORECASE),
        ))
_ALIAS_PATTERNS.sort(key=lambda x: len(x[1]), reverse=True)

_INSTITUTION_HINT_RE = re.compile(
    r"\b(university|college|department|institute|institut|laborator|laboratory|"
    r"lab\.?|center|centre|school|faculty|academy|division|facility|synchrotron|"
    r"observatory|corporation|company|gmbh|inc\.?|ltd\.?)\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_LEADING_LABEL_RE = re.compile(
    r"^\s*(?:\(?[0-9a-zA-Z*#\u2020\u2021\u00a7]+\)?[\s,.;:]+)+"
)
_ZIP_RE = re.compile(
    r"\b(?:[A-Z]{1,3}-)?\d{3,6}(?:-\d{3,4})?\b|"
    r"\b[A-Z]\d[A-Z]\s*\d[A-Z]\d\b|"
    r"\b[A-Z]{2}\s*\d{5}(?:-\d{4})?\b",
    re.IGNORECASE,
)
_OCR_FRONT_MAX_CHARS = 12_000
_OCR_FRONT_STOP_RE = re.compile(
    r"\n\s*(?:abstract|pacs\b|i\.\s+introduction|1\.\s+introduction|introduction)\b",
    re.IGNORECASE,
)

_US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}
_US_STATE_NAMES = {v.casefold(): v for v in _US_STATES.values()}
_CANADA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba",
    "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia", "NT": "Northwest Territories", "NU": "Nunavut",
    "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("\x00", " ")).strip()


def _clean_affiliation_text(text_value: str) -> str:
    text_value = _EMAIL_RE.sub(" ", text_value)
    text_value = re.sub(r"\bElectronic address\s*:\s*", " ", text_value, flags=re.I)
    text_value = _LEADING_LABEL_RE.sub("", text_value)
    return _norm(text_value.strip(" ,;:."))


def extract_jats_affiliation_strings(xml_path: Path) -> list[str]:
    root = ET.fromstring(_replace_html_entities(xml_path.read_bytes()))
    article_meta = None
    for el in root.iter():
        if _local(el.tag) == "article-meta":
            article_meta = el
            break
    scope = article_meta if article_meta is not None else root

    affiliations: list[str] = []
    seen: set[str] = set()
    for aff in scope.iter():
        if _local(aff.tag) != "aff":
            continue
        text_value = _clean_affiliation_text(" ".join(t.strip() for t in aff.itertext() if t.strip()))
        if not text_value:
            continue
        key = text_value.casefold()
        if key in seen:
            continue
        seen.add(key)
        affiliations.append(text_value)
    return affiliations


def _decode_ocr_prefix(ocr_path: Path) -> str:
    text_value = ocr_path.read_bytes().decode("utf-8", errors="replace")
    text_value = text_value.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text_value = text_value.replace("\f", "\n")
    text_value = re.sub(r"[ \t]+", " ", text_value)
    text_value = text_value[:_OCR_FRONT_MAX_CHARS]
    match = _OCR_FRONT_STOP_RE.search(text_value)
    if match and match.start() > 400:
        text_value = text_value[:match.start()]
    lines: list[str] = []
    for raw in text_value.splitlines():
        line = _norm(raw)
        if not line:
            continue
        if re.fullmatch(r"\d{1,4}", line):
            continue
        if "American Physical Society" in line:
            continue
        if re.match(r"^(PHYSICAL REVIEW|REVIEWS OF MODERN PHYSICS)\b", line, re.I):
            continue
        lines.append(line)
    return "\n".join(lines)


def structured_ocr_front_affiliations(ocr_path: Path) -> list[dict[str, Any]]:
    """Return low-confidence country signals from OCR front matter only.

    Older APS packages often lack JATS XML but include ``fulltext.ocr``.
    We avoid persisting any OCR text and extract only country/region
    signals from the title/author/affiliation front matter prefix. City
    is intentionally left blank because OCR line reconstruction is too
    noisy for a reliable city parser at scale.
    """
    front = _decode_ocr_prefix(ocr_path)
    hits = _country_hits(front)
    affiliations: list[dict[str, Any]] = []
    for hit in hits:
        region = _region_from_text(front, hit.canonical)
        affiliations.append({
            "institution": "",
            "city": "",
            "region": region,
            "country": hit.canonical,
            "city_source": "none",
            "method": METHOD,
            "geo_signal": "ocr_front_country",
            "source_hash": hashlib.sha256(
                f"{hit.canonical}\n{front}".encode("utf-8")
            ).hexdigest()[:16],
        })
    return affiliations


def _country_hits(text_value: str) -> list[CountryHit]:
    hits: list[CountryHit] = []
    for canonical, alias, pattern in _ALIAS_PATTERNS:
        match = pattern.search(text_value)
        if match:
            hits.append(CountryHit(canonical, match.start(), match.end(), alias))

    hits.sort(key=lambda h: (h.start, -(h.end - h.start), h.canonical))
    out: list[CountryHit] = []
    seen: set[str] = set()
    for hit in hits:
        if hit.canonical in seen:
            continue
        seen.add(hit.canonical)
        out.append(hit)

    canonicals = {h.canonical for h in out}
    suppress_china_regions = {"Hong Kong", "Macau", "Taiwan"}
    if "China" in canonicals and canonicals.intersection(suppress_china_regions):
        out = [h for h in out if h.canonical != "China"]
    return out


def _split_segments(text_value: str) -> list[str]:
    return [
        _norm(part.strip(" ,;:."))
        for part in re.split(r"[,;]", text_value)
        if _norm(part.strip(" ,;:."))
    ]


def _extract_institution(segments: list[str]) -> str:
    for segment in segments[:5]:
        if _INSTITUTION_HINT_RE.search(segment):
            return segment[:180]
    return segments[0][:180] if segments else ""


def _region_from_text(text_value: str, country: str) -> str:
    if country == "USA":
        for abbrev, name in _US_STATES.items():
            if re.search(rf"\b{re.escape(abbrev)}\b", text_value):
                return name
        folded = text_value.casefold()
        for key, name in _US_STATE_NAMES.items():
            if re.search(rf"\b{re.escape(key)}\b", folded):
                return name
    if country == "Canada":
        for abbrev, name in _CANADA_PROVINCES.items():
            if re.search(rf"\b{re.escape(abbrev)}\b", text_value):
                return name
            if re.search(rf"\b{re.escape(name)}\b", text_value, re.I):
                return name
    return ""


def _remove_region_words(candidate: str, region: str) -> str:
    out = candidate
    if region:
        out = re.sub(rf"\b{re.escape(region)}\b", " ", out, flags=re.I)
    for abbrev, name in _US_STATES.items():
        out = re.sub(rf"\b{re.escape(abbrev)}\b", " ", out)
        out = re.sub(rf"\b{re.escape(name)}\b", " ", out, flags=re.I)
    for abbrev, name in _CANADA_PROVINCES.items():
        out = re.sub(rf"\b{re.escape(abbrev)}\b", " ", out)
        out = re.sub(rf"\b{re.escape(name)}\b", " ", out, flags=re.I)
    return _norm(out.strip(" ,;:."))


def _clean_city_candidate(segment: str, region: str) -> str:
    candidate = _ZIP_RE.sub(" ", segment)
    candidate = re.sub(r"\b(?:P\.?\s*O\.?\s*Box|Box)\b.*$", " ", candidate, flags=re.I)
    candidate = _remove_region_words(candidate, region)
    candidate = _norm(candidate.strip(" ,;:.-"))
    if not candidate:
        return ""
    if _INSTITUTION_HINT_RE.search(candidate):
        return ""
    if len(candidate) > 70:
        return ""
    if sum(ch.isalpha() for ch in candidate) < 2:
        return ""
    return candidate


def _extract_city(text_value: str, hits: list[CountryHit], region: str) -> str:
    if hits:
        before_country = text_value[: min(h.start for h in hits)]
    else:
        before_country = text_value
    segments = _split_segments(before_country)
    for segment in reversed(segments[-7:]):
        city = _clean_city_candidate(segment, region)
        if city:
            return city
    return ""


def structured_affiliations(aff_strings: list[str]) -> list[dict[str, Any]]:
    affiliations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for aff in aff_strings:
        hits = _country_hits(aff)
        country = hits[0].canonical if hits else ""
        region = _region_from_text(aff, country) if country else ""
        city = _extract_city(aff, hits, region)
        segments = _split_segments(aff)
        institution = _extract_institution(segments)
        item = {
            "institution": institution,
            "city": city,
            "region": region,
            "country": country,
            "city_source": "explicit" if city else "none",
            "method": METHOD,
            "source_hash": hashlib.sha256(aff.encode("utf-8")).hexdigest()[:16],
        }
        key = (
            item["institution"].casefold(),
            item["city"].casefold(),
            item["region"].casefold(),
            item["country"].casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        affiliations.append(item)
    return affiliations


def _dedup_geo(affiliations: list[dict[str, Any]]) -> dict[str, list[str]]:
    cities: dict[str, str] = {}
    countries: dict[str, str] = {}
    regions: dict[str, str] = {}
    for aff in affiliations:
        city = _norm(aff.get("city"))
        country = _norm(aff.get("country"))
        region = _norm(aff.get("region"))
        if city:
            cities.setdefault(city.casefold(), city)
        if country:
            countries.setdefault(country.casefold(), country)
        if region:
            regions.setdefault(region.casefold(), region)
    return {
        "cities": sorted(cities.values()),
        "countries": sorted(countries.values()),
        "regions": sorted(regions.values()),
    }


def _confidence(geo: dict[str, list[str]]) -> str:
    if geo["cities"]:
        return "high"
    if geo["countries"]:
        return "low"
    return "none"


def make_paper_geo(
    affiliations: list[dict[str, Any]],
    *,
    source: str,
    status: str,
    extracted_at: str,
) -> dict[str, Any]:
    geo = _dedup_geo(affiliations)
    return {
        "cities": geo["cities"],
        "countries": geo["countries"],
        "regions": geo["regions"],
        "n_affiliations": len(affiliations),
        "confidence": _confidence(geo),
        "source": source,
        "method": METHOD,
        "country_normalization": COUNTRY_NORMALIZATION,
        "status": status,
        "extracted_at": extracted_at,
    }


async def _select_papers(
    *,
    limit: int,
    year_from: int,
    year_to: int,
    force: bool,
    retry_failed: bool,
) -> list[PaperRow]:
    condition = "TRUE" if force else "paper_geo IS NULL"
    if retry_failed:
        condition = (
            "paper_geo IS NULL OR "
            "paper_geo->>'method' = :method AND "
            "paper_geo->>'status' IN ('error', 'no_source')"
        )

    sql = f"""
    WITH aps_papers AS (
      SELECT id, doi, paper_geo,
             COALESCE(
               EXTRACT(YEAR FROM date_published)::int,
               CASE WHEN publication_ref->>'published_date' ~ '^[0-9]{{4}}'
                    THEN substring(publication_ref->>'published_date' from 1 for 4)::int
               END
             ) AS paper_year
      FROM papers
      WHERE source='aps'
        AND doi IS NOT NULL
        AND status!='retracted'
        AND credibility_tier='T1'
    )
    SELECT id, doi, paper_year
    FROM aps_papers
    WHERE paper_year BETWEEN :year_from AND :year_to
      AND ({condition})
    ORDER BY paper_year, doi
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    async with _session_factory()() as db:
        rows = (await db.execute(text(sql), {
            "year_from": year_from,
            "year_to": year_to,
            "method": METHOD,
        })).all()
    return [PaperRow(r.id, r.doi, r.paper_year) for r in rows]


async def process_one(
    client: ApsClient,
    paper: PaperRow,
    *,
    dry_run: bool,
) -> str:
    audit = TdmAudit(doi=paper.doi, paper_id=paper.paper_id, harvested_at=_now())
    work: TempBagit | None = None
    extracted_at = _now().isoformat()
    status = "error"
    try:
        with TempBagit(paper.doi.replace("/", "_")) as work:
            zip_bytes = await client.download_bagit(paper.doi)
            work.extract(zip_bytes)
            xml_path = find_fulltext_xml(work.root)
            if xml_path is None:
                ocr_path = find_fulltext_ocr(work.root)
                if ocr_path is None:
                    affiliations: list[dict[str, Any]] = []
                    paper_geo = make_paper_geo(
                        affiliations,
                        source="aps_bagit_no_jats_or_ocr",
                        status="no_source",
                        extracted_at=extracted_at,
                    )
                    status = "no_source"
                else:
                    affiliations = structured_ocr_front_affiliations(ocr_path)
                    paper_geo = make_paper_geo(
                        affiliations,
                        source="aps_ocr_front_country_scan",
                        status="ok" if affiliations else "no_affiliations",
                        extracted_at=extracted_at,
                    )
                    status = paper_geo["status"]
            else:
                aff_strings = extract_jats_affiliation_strings(xml_path)
                affiliations = structured_affiliations(aff_strings)
                paper_geo = make_paper_geo(
                    affiliations,
                    source="aps_jats_aff",
                    status="ok" if affiliations else "no_affiliations",
                    extracted_at=extracted_at,
                )
                status = paper_geo["status"]
            audit.processed_at = _now()
            audit.ner_record_count = len(affiliations)

        if not dry_run:
            await upsert_paper_geo(paper.paper_id, affiliations, paper_geo)
        audit.status = "deleted"
        return status
    except Exception as e:  # noqa: BLE001
        audit.status = "error"
        audit.error = str(e)[:1000]
        log.warning("%s: APS geography backfill failed: %s", paper.doi, e)
        if not dry_run:
            paper_geo = make_paper_geo(
                [],
                source="aps_jats_aff",
                status="error",
                extracted_at=extracted_at,
            )
            await upsert_paper_geo(paper.paper_id, [], paper_geo)
        return "error"
    finally:
        if work is not None:
            audit.from_temp(work)
        if not dry_run:
            try:
                await write_audit_log(audit)
            except Exception as e:  # noqa: BLE001
                log.error("%s: failed to write TDM audit row: %s", paper.doi, e)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill APS paper geography from JATS affiliations")
    parser.add_argument("--limit", type=int, default=0, help="max papers to process (0 = all)")
    parser.add_argument("--concurrency", type=int, default=4, help="worker count; APS download throttle still applies")
    parser.add_argument("--year-from", type=int, default=1986)
    parser.add_argument("--year-to", type=int, default=2026)
    parser.add_argument("--force", action="store_true", help="overwrite existing APS paper_geo rows")
    parser.add_argument("--retry-failed", action="store_true", help="retry NULL/error/no_source rows from this method")
    parser.add_argument("--dry-run", action="store_true", help="download/parse/delete but do not update DB or audit")
    args = parser.parse_args()

    papers = await _select_papers(
        limit=args.limit,
        year_from=args.year_from,
        year_to=args.year_to,
        force=args.force,
        retry_failed=args.retry_failed,
    )
    total = len(papers)
    log.info(
        "APS geography backfill: %d papers (years=%d-%d, limit=%d, concurrency=%d, dry_run=%s)",
        total, args.year_from, args.year_to, args.limit, args.concurrency, args.dry_run,
    )
    if total == 0:
        await dispose()
        return

    queue: asyncio.Queue[PaperRow] = asyncio.Queue()
    for paper in papers:
        queue.put_nowait(paper)

    stats: Counter[str] = Counter()
    done = 0
    t0 = time.time()

    async with ApsClient() as client:
        async def worker(worker_id: int) -> None:
            nonlocal done
            while True:
                try:
                    paper = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                result = await process_one(client, paper, dry_run=args.dry_run)
                stats[result] += 1
                done += 1
                queue.task_done()
                if done % 25 == 0 or done == total:
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed else 0.0
                    eta = (total - done) / rate / 60 if rate else 0.0
                    log.info(
                        "progress %d/%d worker=%d rate=%.2f/min ETA=%.0f min stats=%s",
                        done, total, worker_id, rate * 60, eta, dict(sorted(stats.items())),
                    )

        await asyncio.gather(*(worker(i) for i in range(max(1, args.concurrency))))

    await dispose()
    elapsed = time.time() - t0
    log.info("=" * 72)
    log.info("APS geography backfill done: %d papers in %.1f min", total, elapsed / 60)
    for key in sorted(stats):
        log.info("  %-16s %7d  %.1f%%", key, stats[key], 100 * stats[key] / total)
    log.info("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
