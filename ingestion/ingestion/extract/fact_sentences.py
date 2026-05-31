"""NER structured facts → natural-language sentences → vector chunks.

APS papers never persist full text, so unlike arXiv there is no body to
chunk for semantic search. Instead we turn the *extracted structured
data* (the authorized TDM output in ``materials_extracted``) into short
natural-language "fact sentences" and vectorise those alongside the
authorized abstract. This keeps Ask/RAG recall high ("which materials
superconduct above 30 K under pressure?") without storing any APS prose.

Every sentence here is derived solely from (a) the authorized abstract
and (b) our own extracted facts — both within the agreement's persistent
scope. No APS full-text wording is reproduced.

A fact sentence reads like:

    "MgB2 has a critical temperature Tc = 39 K (experimental,
     resistivity) at ambient pressure. [iron-based]"

These become ``Chunk`` objects with ``section="Facts"`` so they're
visually distinct from the abstract chunk and carry
``materials_mentioned`` for the same per-chunk material metadata the
arXiv chunks have.
"""
from __future__ import annotations

import logging
from typing import Any

from ingestion.chunk.chunker import chunk_paper
from ingestion.models import ApsArticleMeta, Chunk, ParsedPaper

log = logging.getLogger(__name__)

#: Cap on fact-sentence chunks per paper — a defensive bound so a paper
#: with a huge cited-materials table can't blow up the index. Primary
#: (the paper's own) records are kept ahead of cited ones.
_MAX_FACT_CHUNKS = 40


def fact_sentence(record: dict[str, Any]) -> str | None:
    """Render one NER record as a natural-language fact sentence.

    Returns None for a record with no usable signal (no formula, or a
    bare formula with nothing to say about it — the abstract chunk
    already covers mere mentions).
    """
    formula = (record.get("formula") or "").strip()
    if not formula:
        return None

    tc = record.get("tc_kelvin")
    pressure = record.get("pressure_gpa")
    cond = record.get("pressure_condition_normalized") or record.get(
        "pressure_condition"
    )
    # tc_regime is the always-present pressure-context signal
    # (bulk_equilibrium | high_pressure | interface).
    regime = record.get("tc_regime")
    method = record.get("method")
    measurement = record.get("measurement")
    family = record.get("family")
    doping = _doping_phrase(record)
    structure = record.get("crystal_structure")
    sample = record.get("sample_form")
    comment = record.get("comment")

    has_tc = isinstance(tc, (int, float))

    # Skip records that carry nothing beyond the formula — they add noise,
    # not recall (the abstract already mentions the compound).
    # Note: tc_regime is intentionally NOT a "has context" signal — it
    # defaults to bulk_equilibrium on almost every record, so a bare
    # formula + regime is still noise (the abstract already mentions the
    # compound). It only colours the sentence when other signal exists.
    if not has_tc and not any(
        (pressure, family, doping, structure, sample, comment)
    ):
        return None

    parts: list[str] = []
    if has_tc:
        # Trim trailing .0 for readability ("39 K" not "39.0 K").
        tc_str = f"{tc:g}"
        sentence = f"{formula} has a critical temperature Tc = {tc_str} K"
        quals = [q for q in (method, measurement) if q]
        if quals:
            sentence += f" ({', '.join(quals)})"
    else:
        sentence = f"{formula} is reported"
        if method or measurement:
            quals = [q for q in (method, measurement) if q]
            sentence += f" ({', '.join(quals)})"

    # Pressure clause: explicit GPa wins, else fall back to the
    # pressure_condition / tc_regime category.
    if isinstance(pressure, (int, float)) and pressure > 0:
        sentence += f" at {pressure:g} GPa"
    elif cond == "ambient" or regime == "bulk_equilibrium":
        sentence += " at ambient pressure"
    elif cond == "high_pressure" or regime == "high_pressure":
        sentence += " under high pressure"

    parts.append(sentence + ".")

    tags: list[str] = []
    if family:
        tags.append(str(family))
    if structure:
        tags.append(str(structure))
    if sample:
        tags.append(str(sample))
    if doping:
        tags.append(doping)
    if tags:
        parts.append(f"[{'; '.join(tags)}]")
    if comment:
        parts.append(f"Note: {comment}.")

    return " ".join(parts)


def _doping_phrase(record: dict[str, Any]) -> str | None:
    """Render doping_type + doping_level into a short tag, or None."""
    dtype = record.get("doping_type")
    level = record.get("doping_level")
    if dtype in (None, "", "none") and level is None:
        return None
    if isinstance(level, (int, float)) and dtype not in (None, "", "none"):
        return f"doping: {dtype} x={level:g}"
    if isinstance(level, (int, float)):
        return f"doping: x={level:g}"
    return f"doping: {dtype}"


def _ordered_records(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Primary (the paper's own) records first, then cited, so the
    truncation cap keeps the most relevant facts."""
    primary = [r for r in materials if r.get("evidence_type") != "cited"]
    cited = [r for r in materials if r.get("evidence_type") == "cited"]
    return primary + cited


def build_fact_chunks(
    meta: ApsArticleMeta,
    materials: list[dict[str, Any]],
    *,
    start_index: int,
) -> list[Chunk]:
    """Build vectorisable fact-sentence chunks from NER output.

    Each chunk carries one fact sentence (prefixed with the title +
    "Section: Facts" so it reads coherently in RAG context) and the
    originating record under ``materials_mentioned``. ``start_index``
    continues the chunk numbering after the abstract chunk(s) so ids stay
    unique within the paper.
    """
    title = meta.title
    out: list[Chunk] = []
    idx = start_index
    for record in _ordered_records(materials):
        if len(out) >= _MAX_FACT_CHUNKS:
            log.info("%s: fact-chunk cap (%d) reached; %d records dropped",
                     meta.paper_id, _MAX_FACT_CHUNKS,
                     len(materials) - _MAX_FACT_CHUNKS)
            break
        sentence = fact_sentence(record)
        if not sentence:
            continue
        text = f"Title: {title}\nSection: Facts\n\n{sentence}"
        out.append(Chunk(
            id=f"{meta.paper_id}_fact_{idx:03d}",
            paper_id=meta.paper_id,
            chunk_index=idx,
            section="Facts",
            text=text,
            token_count=len(text) // 4,  # rough; exact count not needed here
            materials_mentioned=[record],
        ))
        idx += 1
    return out


def build_authorized_chunks(
    meta: ApsArticleMeta,
    materials: list[dict[str, Any]],
) -> list[Chunk]:
    """The full set of chunks an APS paper may persist / vectorise:
    the authorized abstract chunk(s) + NER fact-sentence chunks.

    NEVER includes APS full-text body. This is what aps_pipeline stores
    and upserts to Vertex VS.
    """
    abstract_only = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
    abstract_chunks = chunk_paper(abstract_only)
    facts = build_fact_chunks(meta, materials, start_index=len(abstract_chunks))
    return abstract_chunks + facts
