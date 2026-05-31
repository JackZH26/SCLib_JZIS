#!/usr/bin/env python3
"""Audit: recover author / institution geography from a paper's own text.

papers.authors holds only author *name* strings, and papers.affiliations
is declared in the schema but never populated (always NULL) -- so author
and institution geography is absent from the database. This one-off
audit samples 50 ingested papers, pulls each paper's original full text
from GCS (LaTeX .tar.gz, else PDF; falling back to a live arXiv PDF
fetch), and asks Gemini 2.5 Flash to extract the *distinct* author
affiliations with city and country.

Per-paper de-duplication: a city or country shared by several authors of
one paper is counted once -- the audit reports the distinct set per paper.

READ-ONLY: never writes to Postgres, GCS, or Vector Search.

Run on VPS2 (Postgres binds 127.0.0.1, so this must run inside the
compose network):

    cd /opt/SCLib_JZIS
    docker compose run --rm ingestion \\
        python /app/scripts/audit_author_geo_50.py 2>&1

A human-readable report is printed first; a per-paper CSV (for the
manual ground-truth pass) follows between the ===AUDIT_CSV_BEGIN=== and
===AUDIT_CSV_END=== markers.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import logging
import re
import time
from collections import Counter
from functools import lru_cache
from typing import Any

import httpx
from google import genai
from google.genai import types as genai_types
from sqlalchemy import text

from ingestion import storage
from ingestion.config import get_settings
from ingestion.index.indexer import _session_factory, dispose

# latex_parser strips the preamble (where \author / \affiliation live),
# so we reuse only its tar-extraction internals and re-slice the region.
from ingestion.parse.latex_parser import (
    _BEGIN_DOC_RE,
    _extract_tex_files,
    _find_main,
    _inline_inputs,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("audit_geo")

DEFAULT_SEED = 0.4242
DEFAULT_SIZE = 50
MAX_TEX_CHARS = 14_000

_AUTHOR_RE = re.compile(r"\\author\b")
_AFFIL_HINT_RE = re.compile(r"affil|address|institut|\\thanks", re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------------------------

_SCHEMA = """\
Return JSON only, exactly this shape:
{
  "affiliations": [
    {
      "institution": "<university / lab / institute name, or ''>",
      "city": "<city, or '' if not determinable>",
      "region": "<state or province, or ''>",
      "country": "<country, or ''>",
      "city_source": "explicit" | "inferred" | "none"
    }
  ]
}

Rules:
- One entry per DISTINCT affiliation. If several authors share an
  affiliation, list it only once.
- Output PLAIN TEXT for every field -- strip LaTeX markup and resolve
  accent macros. Never emit a backslash character.
- city_source = "explicit" when the city name literally appears in the
  affiliation text; "inferred" when you derived it from a well-known
  institution whose city the text does not name; "none" when no city
  could be determined.
- Only infer a city when the institution unambiguously implies exactly
  one city. When unsure, leave city "" and city_source "none".
- Use common English names ("Munich" not "Muenchen", "China" not "PRC",
  "South Korea" not "Republic of Korea").
- Never invent affiliations. If there is no affiliation information at
  all, return {"affiliations": []}.
"""

_PROMPT_TEXT = (
    "Below is the raw LaTeX front matter (preamble + author block) of a "
    "physics research paper. Extract the distinct research affiliations "
    "of the authors. Strip LaTeX markup and resolve accent macros.\n\n"
    + _SCHEMA
    + "\nLaTeX front matter:\n---\n{{FRONT}}\n---\n"
)

_PROMPT_PDF = (
    "This is a physics research paper PDF. Look ONLY at the first page -- "
    "the title, author list, and affiliation block / footnotes. Extract "
    "the distinct research affiliations of the authors.\n\n" + _SCHEMA
)


# ---------------------------------------------------------------------------
# Evidence acquisition (LaTeX source / PDF) -- all sync, run via to_thread
# ---------------------------------------------------------------------------

def _yymm(arxiv_id: str) -> str:
    """GCS shard prefix: first 4 chars of the arxiv id, slashes stripped."""
    stripped = arxiv_id.replace("cond-mat/", "").replace("/", "")
    return stripped[:4]


def extract_author_region(tar_bytes: bytes) -> str | None:
    """Slice the author/affiliation region out of a LaTeX source archive.

    The pipeline's latex_parser discards the preamble, but that is exactly
    where \\author / \\affiliation / \\address live, so we re-extract here.
    Returns None when the archive yields nothing usable.
    """
    if tar_bytes[:5] == b"%PDF-":  # GCS src/ blob polluted with PDF bytes
        return None
    try:
        tex_files = _extract_tex_files(tar_bytes)
    except Exception:  # noqa: BLE001
        return None
    if not tex_files:
        return None
    main = _find_main(tex_files)
    body = _inline_inputs(main, tex_files)

    m = _AUTHOR_RE.search(body)
    if m:
        region = body[max(0, m.start() - 400): m.start() + 9000]
    else:
        bd = _BEGIN_DOC_RE.search(body)
        if not bd:
            return None
        region = body[max(0, bd.start() - 6000): bd.start() + 4000]
        if not _AFFIL_HINT_RE.search(region):
            return None
    region = region.strip()
    return region or None


def fetch_evidence(arxiv_id: str) -> tuple[str, str | None, Any]:
    """Return (source_used, kind, payload).

    kind is 'text' (LaTeX region str), 'pdf' (raw bytes), or None.
    Cascade: GCS LaTeX source -> GCS PDF -> live arXiv PDF.
    """
    yy = _yymm(arxiv_id)

    # Tier A -- GCS LaTeX source
    try:
        if storage.source_exists(arxiv_id, yy):
            region = extract_author_region(storage.download_source(arxiv_id, yy))
            if region:
                return ("latex", "text", region)
    except Exception as e:  # noqa: BLE001
        log.warning("%s: GCS LaTeX evidence failed: %s", arxiv_id, e)

    # Tier B -- GCS PDF
    try:
        if storage.pdf_exists(arxiv_id, yy):
            return ("gcs_pdf", "pdf", storage.download_pdf(arxiv_id, yy))
    except Exception as e:  # noqa: BLE001
        log.warning("%s: GCS PDF evidence failed: %s", arxiv_id, e)

    # Tier C -- live arXiv PDF
    try:
        ua = get_settings().arxiv_user_agent
        r = httpx.get(
            f"https://export.arxiv.org/pdf/{arxiv_id}",
            headers={"User-Agent": ua}, timeout=90.0, follow_redirects=True,
        )
        time.sleep(3.0)  # arXiv fair-use delay
        if r.status_code == 200 and r.content[:5] == b"%PDF-":
            return ("arxiv_pdf", "pdf", r.content)
        log.warning("%s: live arXiv PDF status=%s", arxiv_id, r.status_code)
    except Exception as e:  # noqa: BLE001
        log.warning("%s: live arXiv PDF failed: %s", arxiv_id, e)

    return ("none", None, None)


# ---------------------------------------------------------------------------
# Gemini extraction -- sync, run via to_thread
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _client() -> genai.Client:
    s = get_settings()
    return genai.Client(
        vertexai=True, project=s.gcp_project, location=s.gcp_region,
        http_options={"timeout": 120_000},
    )


def _finish_reason(resp: Any) -> str:
    try:
        return str(resp.candidates[0].finish_reason)
    except Exception:  # noqa: BLE001
        return "?"


def _repair_json_escapes(s: str) -> str:
    """Double any backslash that does not start a valid JSON escape.

    Gemini occasionally copies LaTeX accent macros (\\'e, \\"o, \\,) into
    string values; the lone backslash is an invalid JSON escape and
    json.loads then rejects the whole reply. Every backslash in
    well-formed JSON lives inside a string value, so doubling the
    invalid ones is safe.
    """
    valid = set('"\\/bfnrtu')
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n and s[i + 1] in valid:
            out.append(s[i:i + 2])
            i += 2
        elif s[i] == "\\":
            out.append("\\\\")
            i += 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _parse_affiliations(raw: str) -> list[dict[str, Any]] | None:
    """Parse Gemini's JSON reply. Returns None when the text is not
    valid/complete JSON. Retries once with stray LaTeX backslashes
    escaped, since that is the common cause of an unparseable reply."""
    if not raw:
        return None
    data = None
    for candidate in (raw, _repair_json_escapes(raw)):
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if data is None:
        return None
    affs = data.get("affiliations") if isinstance(data, dict) else None
    if not isinstance(affs, list):
        return None
    return [a for a in affs if isinstance(a, dict)]


def gemini_extract(kind: str, payload: Any) -> list[dict[str, Any]]:
    """Call Gemini; return the affiliations list ([] on any failure)."""
    if kind == "text":
        contents: Any = _PROMPT_TEXT.replace("{{FRONT}}", str(payload)[:MAX_TEX_CHARS])
    else:  # pdf
        contents = [
            genai_types.Part.from_bytes(data=payload, mime_type="application/pdf"),
            _PROMPT_PDF,
        ]
    cfg = genai_types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json",
        # Generous cap: gemini-2.5-flash's dynamic "thinking" tokens
        # share the output budget, so a small cap (8k) truncated the
        # JSON mid-object for papers the model thought hard about. 32k
        # clears the max thinking budget (~24k) plus the answer.
        # thinking_config also requests none, but is not always honored.
        max_output_tokens=32768,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
    )
    model = get_settings().gemini_model

    for attempt in range(4):
        try:
            resp = _client().models.generate_content(
                model=model, contents=contents, config=cfg,
            )
        except Exception as e:  # noqa: BLE001
            es = str(e)
            retryable = (
                any(t in es for t in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
                or "timeout" in es.lower()
            )
            if retryable and attempt < 3:
                wait = 2 ** attempt * 3
                log.info("Gemini %s -- retry %d/4 in %ds", es[:80], attempt + 1, wait)
                time.sleep(wait)
                continue
            log.warning("Gemini call failed: %s", es[:160])
            return []

        raw = _FENCE_RE.sub("", (resp.text or "").strip()).strip()
        affs = _parse_affiliations(raw)
        if affs is not None:
            return affs
        # Unparseable (usually a truncated reply) -- diagnose and retry.
        log.warning("Gemini non-JSON attempt %d/4 (finish=%s, len=%d): tail=%r",
                    attempt + 1, _finish_reason(resp), len(raw), raw[-260:])
        if attempt < 3:
            time.sleep(2)
            continue
        return []
    return []


# ---------------------------------------------------------------------------
# Per-paper de-duplication + scoring
# ---------------------------------------------------------------------------

def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def dedup_geo(affs: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Collapse affiliations into the paper's distinct city / country sets.

    A city or country shared by multiple authors counts once. Cities are
    split into explicit (named in the text) vs inferred-only.
    """
    explicit: dict[str, str] = {}
    inferred: dict[str, str] = {}
    countries: dict[str, str] = {}
    for a in affs:
        city = _norm(a.get("city"))
        country = _norm(a.get("country"))
        src = str(a.get("city_source") or "none").strip().lower()
        if city:
            bucket = explicit if src == "explicit" else inferred
            bucket.setdefault(city.casefold(), city)
        if country:
            countries.setdefault(country.casefold(), country)
    expl = sorted(explicit.values())
    infr = sorted(v for k, v in inferred.items() if k not in explicit)
    return {
        "cities_explicit": expl,
        "cities_inferred": infr,
        "cities_all": sorted(set(expl) | set(infr)),
        "countries": sorted(countries.values()),
    }


def confidence_of(geo: dict[str, list[str]]) -> str:
    if geo["cities_explicit"]:
        return "high"
    if geo["cities_inferred"]:
        return "medium"
    if geo["countries"]:
        return "low"
    return "none"


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

async def sample_papers(seed: float, size: int) -> list[Any]:
    """Reproducible random sample. setseed + random() share one connection."""
    Session = _session_factory()
    async with Session() as db:
        await db.execute(text("SELECT setseed(:s)"), {"s": seed})
        rows = (await db.execute(text(
            """
            SELECT id, arxiv_id, doi, title,
                   jsonb_array_length(authors) AS n_authors
            FROM papers
            WHERE source = 'arxiv' AND chunk_count > 0
            ORDER BY random()
            LIMIT :lim
            """
        ), {"lim": size})).all()
    return list(rows)


async def fetch_papers_by_ids(ids: list[str]) -> list[Any]:
    """Fetch specific papers by id (used to re-audit a known subset)."""
    Session = _session_factory()
    async with Session() as db:
        rows = (await db.execute(text(
            """
            SELECT id, arxiv_id, doi, title,
                   jsonb_array_length(authors) AS n_authors
            FROM papers
            WHERE id = ANY(:ids)
            """
        ), {"ids": ids})).all()
    return list(rows)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _hist(values: list[int]) -> str:
    c = Counter(min(v, 4) for v in values)
    return "  ".join(f"{'4+' if k == 4 else k}:{c.get(k, 0)}" for k in range(5))


def _top(counter: Counter, n: int = 12) -> str:
    return "  ".join(f"{name}({cnt})" for name, cnt in counter.most_common(n)) or "(none)"


def print_report(results: list[dict[str, Any]]) -> None:
    n = len(results)
    src = Counter(r["source_used"] for r in results)
    status = Counter(r["extract_status"] for r in results)
    conf = Counter(r["confidence"] for r in results)

    city_ok = sum(1 for r in results if r["city_obtained"])
    city_high = sum(1 for r in results if r["confidence"] == "high")
    city_inferred_only = sum(1 for r in results if r["confidence"] == "medium")
    country_ok = sum(1 for r in results if r["country_obtained"])
    both = sum(1 for r in results if r["city_obtained"] and r["country_obtained"])
    neither = sum(1 for r in results if not r["city_obtained"] and not r["country_obtained"])

    city_counter: Counter = Counter()
    country_counter: Counter = Counter()
    for r in results:
        for c in r["geo"]["cities_all"]:
            city_counter[c] += 1
        for c in r["geo"]["countries"]:
            country_counter[c] += 1

    def pct(x: int) -> str:
        return f"{100 * x / n:.0f}%" if n else "-"

    L = []
    L.append("=" * 72)
    L.append("AUTHOR / INSTITUTION GEOGRAPHY AUDIT")
    L.append("=" * 72)
    L.append(f"Sample: {n} papers  |  population = papers(source=arxiv, chunk_count>0)")
    L.append("")
    L.append("Evidence source used:")
    L.append(f"  latex     (GCS LaTeX source) : {src.get('latex', 0)}")
    L.append(f"  gcs_pdf   (GCS PDF)          : {src.get('gcs_pdf', 0)}")
    L.append(f"  arxiv_pdf (live arXiv PDF)   : {src.get('arxiv_pdf', 0)}")
    L.append(f"  none      (no source found)  : {src.get('none', 0)}")
    L.append("")
    L.append("Extraction outcome:")
    L.append(f"  ok        (>=1 affiliation)     : {status.get('ok', 0)}")
    L.append(f"  empty     (source, 0 affil)     : {status.get('empty', 0)}")
    L.append(f"  no_source                       : {status.get('no_source', 0)}")
    L.append(f"  error                           : {status.get('error', 0)}")
    L.append("")
    L.append("-" * 72)
    L.append("HEADLINE -- per-paper geography recovered (within-paper de-duped):")
    L.append("-" * 72)
    L.append(f"  >=1 CITY obtained        : {city_ok} / {n}   ({pct(city_ok)})")
    L.append(f"      - city explicit in text (high conf) : {city_high}")
    L.append(f"      - city only via inference (medium)  : {city_inferred_only}")
    L.append(f"  >=1 COUNTRY obtained     : {country_ok} / {n}   ({pct(country_ok)})")
    L.append(f"  both city AND country    : {both} / {n}")
    L.append(f"  neither                  : {neither} / {n}")
    L.append("")
    L.append("Confidence tiers:")
    L.append(f"  high   (>=1 explicit city)    : {conf.get('high', 0)}")
    L.append(f"  medium (city inferred only)   : {conf.get('medium', 0)}")
    L.append(f"  low    (country only, no city): {conf.get('low', 0)}")
    L.append(f"  none   (nothing recovered)    : {conf.get('none', 0)}")
    L.append("")
    L.append("Distinct cities per paper:    " + _hist([len(r["geo"]["cities_all"]) for r in results]))
    L.append("Distinct countries per paper: " + _hist([len(r["geo"]["countries"]) for r in results]))
    L.append("")
    L.append(f"Top cities (papers mentioning): {_top(city_counter)}")
    L.append(f"Top countries:                 {_top(country_counter)}")
    L.append("")
    no_city = [r["paper_id"] for r in results if not r["city_obtained"]]
    L.append(f"Papers with NO city recovered ({len(no_city)}): {', '.join(no_city) or '(none)'}")
    L.append("")
    L.append("NOTE: the counts above are AUTOMATED extraction. The final")
    L.append("'accurately obtained' numbers require the manual verification pass --")
    L.append("fill the manual_* columns in the CSV below against each arXiv page.")
    L.append("=" * 72)
    print("\n".join(L))


CSV_COLUMNS = [
    "paper_id", "arxiv_id", "arxiv_url", "title", "n_authors",
    "source_used", "extract_status", "n_affiliations", "n_cities", "n_countries",
    "cities", "cities_inferred_only", "countries",
    "city_obtained", "country_obtained", "confidence",
    "affiliations_detail", "evidence_excerpt",
    "manual_city_correct", "manual_country_correct", "manual_notes",
]


def print_csv(results: list[dict[str, Any]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in results:
        geo = r["geo"]
        detail = "; ".join(
            f"{_norm(a.get('institution'))} | {_norm(a.get('city'))} | "
            f"{_norm(a.get('country'))} | {str(a.get('city_source') or 'none')}"
            for a in r["affiliations"]
        )
        w.writerow({
            "paper_id": r["paper_id"],
            "arxiv_id": r["arxiv_id"],
            "arxiv_url": f"https://arxiv.org/abs/{r['arxiv_id']}",
            "title": r["title"],
            "n_authors": r["n_authors"],
            "source_used": r["source_used"],
            "extract_status": r["extract_status"],
            "n_affiliations": len(r["affiliations"]),
            "n_cities": len(geo["cities_all"]),
            "n_countries": len(geo["countries"]),
            "cities": "; ".join(geo["cities_all"]),
            "cities_inferred_only": "; ".join(geo["cities_inferred"]),
            "countries": "; ".join(geo["countries"]),
            "city_obtained": int(r["city_obtained"]),
            "country_obtained": int(r["country_obtained"]),
            "confidence": r["confidence"],
            "affiliations_detail": detail,
            "evidence_excerpt": r["evidence_excerpt"],
            "manual_city_correct": "",
            "manual_country_correct": "",
            "manual_notes": "",
        })
    print("===AUDIT_CSV_BEGIN===")
    print(buf.getvalue().rstrip("\n"))
    print("===AUDIT_CSV_END===")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    ap = argparse.ArgumentParser(description="Author/institution geography audit")
    ap.add_argument("--limit", type=int, default=DEFAULT_SIZE,
                    help="number of papers to sample (default 50)")
    ap.add_argument("--seed", type=float, default=DEFAULT_SEED,
                    help="setseed() value for a reproducible sample")
    ap.add_argument("--ids", type=str, default="",
                    help="comma-separated paper ids to audit instead of sampling")
    args = ap.parse_args()

    if args.ids:
        rows = await fetch_papers_by_ids(
            [s.strip() for s in args.ids.split(",") if s.strip()]
        )
        log.info("Auditing %d explicitly-listed papers", len(rows))
    else:
        rows = await sample_papers(args.seed, args.limit)
        log.info("Sampled %d papers (seed=%s)", len(rows), args.seed)

    results: list[dict[str, Any]] = []
    for i, row in enumerate(rows, 1):
        arxiv_id = row.arxiv_id or row.id.replace("arxiv:", "")
        rec: dict[str, Any] = {
            "paper_id": row.id,
            "arxiv_id": arxiv_id,
            "title": _norm(row.title),
            "n_authors": row.n_authors or 0,
            "source_used": "none",
            "extract_status": "no_source",
            "affiliations": [],
            "evidence_excerpt": "",
            "geo": {"cities_explicit": [], "cities_inferred": [],
                    "cities_all": [], "countries": []},
            "city_obtained": False,
            "country_obtained": False,
            "confidence": "none",
        }
        try:
            source_used, kind, payload = await asyncio.to_thread(fetch_evidence, arxiv_id)
            rec["source_used"] = source_used
            if kind is None:
                rec["extract_status"] = "no_source"
            else:
                if kind == "text":
                    rec["evidence_excerpt"] = _norm(payload)[:1000]
                else:
                    rec["evidence_excerpt"] = f"[PDF via {source_used}]"
                affs = await asyncio.to_thread(gemini_extract, kind, payload)
                rec["affiliations"] = affs
                rec["extract_status"] = "ok" if affs else "empty"
                geo = dedup_geo(affs)
                rec["geo"] = geo
                rec["city_obtained"] = bool(geo["cities_all"])
                rec["country_obtained"] = bool(geo["countries"])
                rec["confidence"] = confidence_of(geo)
        except Exception as e:  # noqa: BLE001
            rec["extract_status"] = "error"
            log.error("%s: audit failed: %s", row.id, e)

        results.append(rec)
        if i % 5 == 0 or i == len(rows):
            log.info("Progress: %d/%d  (last=%s src=%s status=%s cities=%d)",
                     i, len(rows), rec["paper_id"], rec["source_used"],
                     rec["extract_status"], len(rec["geo"]["cities_all"]))

    await dispose()

    print()
    print_report(results)
    print()
    print_csv(results)


if __name__ == "__main__":
    asyncio.run(main())
