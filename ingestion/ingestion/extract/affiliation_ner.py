"""Author / institution geography NER — independent of material NER.

``material_ner.py`` extracts superconductor data; this module is a
*separate* NER flow that extracts the geography of a paper's authors —
city, country, region — from the paper's own front matter. It does not
import or modify material_ner.py.

Approach (validated by ``scripts/audit_author_geo_50.py`` on a 50-paper
sample: 100% source hit-rate, ~96-98% per-paper accuracy):

  1. Fetch the paper's own text — GCS LaTeX source -> GCS PDF -> live
     arXiv PDF. The pipeline's latex_parser discards the preamble where
     ``\\author`` / ``\\affiliation`` live, so we re-extract that region.
  2. Gemini Flash extracts the distinct author affiliations with
     city + country. Thinking is disabled (its tokens otherwise starve
     the JSON answer); stray LaTeX backslashes are escape-repaired.
  3. De-duplicate within the paper — a city or country shared by
     several authors counts once.

Public entry point: ``extract_paper_geo(arxiv_id)``. It never raises;
failures surface via the returned ``paper_geo['status']`` field.

Used by:
  * ingestion.pipeline  — per-paper, for newly ingested papers
  * scripts/backfill_paper_geo.py — bulk backfill of existing papers
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from google import genai
from google.genai import types as genai_types

from ingestion import storage
from ingestion.config import get_settings
from ingestion.genai_client import make_genai_client

# latex_parser strips the preamble (where \author / \affiliation live),
# so we reuse only its tar-extraction internals and re-slice the region.
from ingestion.parse.latex_parser import (
    _BEGIN_DOC_RE,
    _extract_tex_files,
    _find_main,
    _inline_inputs,
)

log = logging.getLogger(__name__)

#: Bump when the extraction logic / prompt changes materially so a
#: future re-run can target rows whose paper_geo.method is stale.
METHOD = "geo_ner_v1"

#: Cap on the LaTeX front-matter text handed to Gemini.
_MAX_TEX_CHARS = 14_000

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
- Always fill country when it is determinable, even if the text never
  names it: derive it from an unambiguous regional signal -- a US/
  Canadian state or ZIP ("Murray Hill, NJ 07974" -> USA), a postal-code
  prefix ("D-01171" -> Germany, "CH-8093" -> Switzerland, "F-33405" ->
  France), or a well-known institution.
- Use canonical short English country names: "USA", "UK", "China",
  "Japan", "Germany", "France", "Russia", "Italy", "South Korea",
  "Switzerland", "Spain", "Canada", "Australia", "India", "Brazil", etc.
- Use common English city names ("Munich" not "Muenchen").
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
# Evidence acquisition (LaTeX source / PDF)
# ---------------------------------------------------------------------------

def _yymm(arxiv_id: str) -> str:
    """GCS shard prefix: first 4 chars of the arxiv id, slashes stripped."""
    stripped = arxiv_id.replace("cond-mat/", "").replace("/", "")
    return stripped[:4]


def _extract_author_region(tar_bytes: bytes) -> str | None:
    """Slice the author / affiliation region out of a LaTeX source archive.

    Returns None when the archive yields nothing usable (caller then
    falls through to the PDF path).
    """
    if tar_bytes[:5] == b"%PDF-":  # src/ blob polluted with PDF bytes
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


def _fetch_evidence(arxiv_id: str) -> tuple[str, str | None, Any]:
    """Return (source_used, kind, payload).

    kind is 'text' (LaTeX region str), 'pdf' (raw bytes), or None.
    Cascade: GCS LaTeX source -> GCS PDF -> live arXiv PDF.
    """
    yy = _yymm(arxiv_id)

    # Tier A -- GCS LaTeX source
    try:
        if storage.source_exists(arxiv_id, yy):
            region = _extract_author_region(storage.download_source(arxiv_id, yy))
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

    # Tier C -- live arXiv PDF (rare: every ingested paper has GCS bytes)
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
# Gemini extraction
# ---------------------------------------------------------------------------

_tls = threading.local()


def _client() -> genai.Client:
    """Return a per-thread genai client.

    The backfill runs extract_paper_geo across many worker threads. A
    single shared google-genai client races on its underlying httpx
    connection ("Cannot send a request, as the client has been
    closed"), so each thread gets and reuses its own.
    """
    c = getattr(_tls, "geo_client", None)
    if c is None:
        c = make_genai_client()
        _tls.geo_client = c
    return c


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
    escaped, the common cause of an unparseable reply."""
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


def _gemini_extract(kind: str, payload: Any) -> list[dict[str, Any]]:
    """Call Gemini; return the affiliations list. Raises on hard failure
    (exhausted retries) so the caller can mark the paper status=error."""
    if kind == "text":
        contents: Any = _PROMPT_TEXT.replace("{{FRONT}}", str(payload)[:_MAX_TEX_CHARS])
    else:  # pdf
        contents = [
            genai_types.Part.from_bytes(data=payload, mime_type="application/pdf"),
            _PROMPT_PDF,
        ]
    cfg = genai_types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json",
        # Gemini Flash thinking tokens share the output
        # budget; a small cap truncated the JSON for papers it thought
        # hard about. 32k clears max thinking (~24k) plus the answer.
        max_output_tokens=32768,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
    )
    model = get_settings().gemini_model

    last_err = "unknown"
    for attempt in range(4):
        try:
            resp = _client().models.generate_content(
                model=model, contents=contents, config=cfg,
            )
        except Exception as e:  # noqa: BLE001
            es = str(e)
            last_err = es[:160]
            retryable = (
                any(t in es for t in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
                or "timeout" in es.lower()
            )
            if retryable and attempt < 3:
                wait = 2 ** attempt * 3
                log.info("Gemini %s -- retry %d/4 in %ds", es[:80], attempt + 1, wait)
                time.sleep(wait)
                continue
            raise RuntimeError(f"Gemini call failed: {last_err}") from e

        raw = _FENCE_RE.sub("", (resp.text or "").strip()).strip()
        affs = _parse_affiliations(raw)
        if affs is not None:
            return affs
        last_err = f"non-JSON (finish={_finish_reason(resp)}, len={len(raw)})"
        log.warning("Gemini %s attempt %d/4: tail=%r", last_err, attempt + 1, raw[-200:])
        if attempt < 3:
            time.sleep(2)
            continue
    raise RuntimeError(f"Gemini extraction failed: {last_err}")


# ---------------------------------------------------------------------------
# Per-paper de-duplication
# ---------------------------------------------------------------------------

def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _dedup_geo(affs: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Collapse affiliations into the paper's distinct geography sets.

    A city / country / region shared by multiple authors counts once.
    Cities split into explicit (named in the text) vs inferred-only.
    """
    explicit: dict[str, str] = {}
    inferred: dict[str, str] = {}
    countries: dict[str, str] = {}
    regions: dict[str, str] = {}
    for a in affs:
        city = _norm(a.get("city"))
        country = _norm(a.get("country"))
        region = _norm(a.get("region"))
        src = str(a.get("city_source") or "none").strip().lower()
        if city:
            bucket = explicit if src == "explicit" else inferred
            bucket.setdefault(city.casefold(), city)
        if country:
            countries.setdefault(country.casefold(), country)
        if region:
            regions.setdefault(region.casefold(), region)
    expl = sorted(explicit.values())
    infr = sorted(v for k, v in inferred.items() if k not in explicit)
    return {
        "cities_explicit": expl,
        "cities_inferred": infr,
        "cities_all": sorted(set(expl) | set(infr)),
        "countries": sorted(countries.values()),
        "regions": sorted(regions.values()),
    }


def _confidence_of(geo: dict[str, list[str]]) -> str:
    if geo["cities_explicit"]:
        return "high"
    if geo["cities_inferred"]:
        return "medium"
    if geo["countries"]:
        return "low"
    return "none"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_paper_geo(arxiv_id: str) -> dict[str, Any]:
    """Extract a paper's author geography. NEVER raises.

    Returns ``{"affiliations": [...], "paper_geo": {...}}``:

    * ``affiliations`` -- raw per-institution list for papers.affiliations,
      each ``{institution, city, region, country, city_source}``.
    * ``paper_geo`` -- de-duped summary for papers.paper_geo, with a
      ``status`` field: ``ok`` | ``no_affiliations`` | ``no_source`` |
      ``error``.
    """
    extracted_at = datetime.now(timezone.utc).isoformat()
    base = {
        "cities": [], "countries": [], "regions": [],
        "n_affiliations": 0, "confidence": "none",
        "source": None, "method": METHOD,
        "status": "error", "extracted_at": extracted_at,
    }

    try:
        source_used, kind, payload = _fetch_evidence(arxiv_id)
    except Exception as e:  # noqa: BLE001
        log.warning("%s: geo evidence fetch failed: %s", arxiv_id, e)
        return {"affiliations": [], "paper_geo": {**base, "status": "error"}}

    if kind is None:
        return {"affiliations": [],
                "paper_geo": {**base, "source": "none", "status": "no_source"}}

    try:
        raw_affs = _gemini_extract(kind, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("%s: geo extraction failed: %s", arxiv_id, e)
        return {"affiliations": [],
                "paper_geo": {**base, "source": source_used, "status": "error"}}

    affiliations = [
        {
            "institution": _norm(a.get("institution")),
            "city": _norm(a.get("city")),
            "region": _norm(a.get("region")),
            "country": _norm(a.get("country")),
            "city_source": str(a.get("city_source") or "none").strip().lower(),
        }
        for a in raw_affs
    ]
    geo = _dedup_geo(affiliations)
    paper_geo = {
        "cities": geo["cities_all"],
        "countries": geo["countries"],
        "regions": geo["regions"],
        "n_affiliations": len(affiliations),
        "confidence": _confidence_of(geo),
        "source": source_used,
        "method": METHOD,
        "status": "ok" if affiliations else "no_affiliations",
        "extracted_at": extracted_at,
    }
    return {"affiliations": affiliations, "paper_geo": paper_geo}
