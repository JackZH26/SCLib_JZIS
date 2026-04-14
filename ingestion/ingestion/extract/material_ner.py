"""Material NER via Gemini 2.5 Flash.

Returns a list of superconductor records extracted from the full text of
a paper. The prompt is lifted verbatim from PROJECT_SPEC.md §9 and
asks for JSON output only — we still defensively parse to tolerate
Gemini's occasional markdown-fencing habit.

This module calls the ``google-genai`` SDK synchronously; the pipeline
wraps calls in ``asyncio.to_thread`` to keep the orchestration loop async.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from google import genai
from google.genai import types as genai_types

from ingestion.config import get_settings
from ingestion.models import ParsedPaper

log = logging.getLogger(__name__)


# NOTE: we interpolate this with plain `str.replace("{{BODY}}", ...)` — not
# str.format — because the prompt itself contains literal `{field, field}`
# JSON-schema hints that would otherwise be interpreted as format fields.
NER_PROMPT = """\
Extract superconducting materials from this text. Return JSON array only.
For each material: {formula, tc_kelvin, tc_type, pressure_gpa, measurement, confidence}
Only extract materials explicitly measured for superconductivity.
Do not invent data not in the text. Flag Tc > 300K with confidence < 0.3.

Text:
---
{{BODY}}
---
"""

# Truncate the text we hand to Gemini so one enormous paper cannot blow the
# context window. Abstract + first ~8k chars of body is plenty for NER.
_MAX_CHARS = 16_000


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    settings = get_settings()
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_region,
    )


def extract_materials(parsed: ParsedPaper) -> list[dict[str, Any]]:
    """Call Gemini and parse the JSON response. Returns [] on failure."""
    settings = get_settings()
    body = _assemble_text(parsed)
    if not body.strip():
        return []

    prompt = NER_PROMPT.replace("{{BODY}}", body[:_MAX_CHARS])

    try:
        resp = _client().models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini NER call failed for %s: %s", parsed.meta.paper_id, e)
        return []

    text = (resp.text or "").strip()
    if not text:
        return []

    records = _parse_json(text)
    if records is None:
        log.warning("Gemini NER returned non-JSON for %s: %r",
                    parsed.meta.paper_id, text[:200])
        return []

    # Defensive filter: enforce the spec's confidence-downgrade for
    # implausibly high Tc values, and coerce numeric fields.
    cleaned: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict) or "formula" not in r:
            continue
        tc = _coerce_float(r.get("tc_kelvin"))
        conf = _coerce_float(r.get("confidence")) or 0.0
        if tc is not None and tc > 300 and conf >= 0.3:
            conf = 0.3
        cleaned.append({
            "formula": str(r["formula"]).strip(),
            "tc_kelvin": tc,
            "tc_type": r.get("tc_type"),
            "pressure_gpa": _coerce_float(r.get("pressure_gpa")),
            "measurement": r.get("measurement"),
            "confidence": conf,
        })
    return cleaned


def _assemble_text(parsed: ParsedPaper) -> str:
    parts = [f"Title: {parsed.meta.title}", f"Abstract: {parsed.meta.abstract}"]
    for s in parsed.sections[:6]:  # first few sections are enough
        parts.append(f"\n## {s.name}\n{s.text}")
    return "\n\n".join(parts)


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json(text: str) -> list[Any] | None:
    text = _JSON_FENCE_RE.sub("", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "materials" in data:
        inner = data["materials"]
        return inner if isinstance(inner, list) else None
    return None


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
