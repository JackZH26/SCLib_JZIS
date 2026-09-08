"""Truth-preserving, explicitly derived retrieval text from extracted records.

Rendering does not establish source truth, scientific review, independent
confirmation or permission to redistribute a source. The APS path does not
pass its full-text body here. Free-form comments/evidence quotes are not copied
into generated Facts; original records remain unchanged in their own store.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ingestion.chunk.chunker import (
    build_bounded_prefix,
    chunk_paper,
    require_token_budget,
    validate_chunk_settings,
)
from ingestion.claims.outcomes import outcome_conflicts_with_positive
from ingestion.config import get_settings
from ingestion.extract.scientific_values import record_quantity
from ingestion.models import ApsArticleMeta, Chunk, ParsedPaper
from ingestion.pressure_semantics import classify_pressure
from ingestion.result_semantics import classify_result

log = logging.getLogger(__name__)

#: Cap on fact-sentence chunks per paper — a defensive bound so a paper
#: with a huge cited-materials table can't blow up the index. Primary
#: (the paper's own) records are kept ahead of cited ones.
_MAX_FACT_CHUNKS = 40
FACT_RENDERER_VERSION = "sclib-fact-renderer/2.1.0"
_OUTCOME_KEYS = ("result_status", "outcome_state", "outcome")
_BOOL_OUTCOMES = ("no_transition", "not_detected", "superconductivity_observed", "transition_observed", "is_superconducting")
_ORIGIN_KEYS = ("knowledge_origin", "result_origin", "evidence_role", "evidence_type", "claim_kind", "source_role", "measurement", "measurement_method", "method")
_NEGATIVE = {"not_detected", "not_observed", "notdetected", "no_transition", "no_superconductivity", "non_transition_observed"}
_POSITIVE = {"observed", "detected", "transition_observed", "superconducting", "positive"}


def _inputs(record):
    raw = record.get("raw_extraction")
    return (record, raw) if isinstance(raw, Mapping) else (record,)


def _text(value, limit=160):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        return None
    return " ".join(value.split()) if not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value) else None


def _field(record, key):
    values = {_text(item.get(key)) for item in _inputs(record)} - {None}
    return next(iter(values)) if len(values) == 1 else None


def _quantity(record, field):
    """Original extraction outranks legacy scalars; conflicting raw copies veto."""
    proposal = record_quantity(record, field)
    raw = record.get("raw_extraction")
    if isinstance(raw, Mapping) and field in raw:
        original = record_quantity(raw, field)
        typed = record.get("scientific_values")
        if isinstance(typed, Mapping) and field in typed:
            keys = ("status", "relation", "value", "lower", "upper", "uncertainty", "approximate", "unit")
            if any(proposal[key] != original[key] for key in keys):
                return {**proposal, "status": "invalid"}
        else:
            return original
    return proposal


def _quantity_text(proposal, name):
    if proposal["status"] != "parsed":
        return None
    relation, unit = proposal["relation"], proposal["unit"]
    prefix = "approximately " if proposal["approximate"] else ""
    if relation == "exact":
        value = f"{proposal['value']:g}"
        if proposal["uncertainty"] is not None:
            value += f" ± {proposal['uncertainty']:g}"
        return f"{name} = {prefix}{value} {unit}".rstrip()
    if relation == "interval":
        return f"{name} in {prefix}[{proposal['lower']:g}, {proposal['upper']:g}] {unit}"
    if relation in {"lt", "le", "gt", "ge"}:
        operator = {"lt": "<", "le": "≤", "gt": ">", "ge": "≥"}[relation]
        value = proposal["upper"] if relation in {"lt", "le"} else proposal["lower"]
        return f"{name} {operator} {prefix}{value:g} {unit}"
    return None


def _classification(record):
    classifications = [classify_result(item) for item in _inputs(record)]
    origins = {item.knowledge_origin for item in classifications} - {"Unknown"}
    roles = {item.source_role for item in classifications} - {"unknown"}
    malformed = any(item.get(key) is not None and not isinstance(item[key], str)
                    for item in _inputs(record) for key in _ORIGIN_KEYS)
    malformed |= any(isinstance(flag, str) and flag.split(":", 1)[0] in _ORIGIN_KEYS
                     for item in _inputs(record) for flag in
                     (item.get("validation_flags") if isinstance(item.get("validation_flags"), list) else []))
    conflicted = malformed or len(origins) > 1 or any(item.classification_status == "conflicted" for item in classifications)
    origin = next(iter(origins)) if len(origins) == 1 and not conflicted else "Unknown"
    role = next(iter(roles)) if len(roles) == 1 else "conflicted" if roles else "unknown"
    return origin, "conflicted" if conflicted else "resolved" if origins else "unknown", role


def _outcome(record):
    statuses, positive, negative, invalid = set(), False, False, False
    for item in _inputs(record):
        flags = item.get("validation_flags")
        if isinstance(flags, list):
            invalid |= any(isinstance(flag, str) and flag.split(":", 1)[0] in _OUTCOME_KEYS + _BOOL_OUTCOMES for flag in flags)
        for key in _OUTCOME_KEYS:
            value = item.get(key)
            if value is not None:
                if not isinstance(value, str):
                    invalid = True
                elif value.strip():
                    statuses.add(re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_"))
        for key in _BOOL_OUTCOMES:
            if item.get(key) is not None and type(item[key]) is not bool:
                invalid = True
        negative |= any(item.get(key) is True for key in ("no_transition", "not_detected"))
        negative |= any(item.get(key) is False for key in _BOOL_OUTCOMES[2:])
        positive |= any(item.get(key) is True for key in _BOOL_OUTCOMES[2:])
    positive |= bool(statuses & _POSITIVE)
    negative |= bool(statuses & _NEGATIVE)
    if positive and negative:
        return "conflicted"
    if invalid or statuses - (_POSITIVE | _NEGATIVE):
        return "unresolved"
    if negative:
        return "not_detected"
    if any(outcome_conflicts_with_positive(item) for item in _inputs(record)):
        return "unresolved"
    return "positive_reported" if positive else "unspecified"


def _pressure(record):
    current = classify_pressure(record)
    raw = record.get("raw_extraction")
    if isinstance(raw, Mapping):
        original = classify_pressure(raw)
        if current.pressure_state == "not_reported":
            return original
        if original.pressure_state != "not_reported":
            keys = ("pressure_state", "pressure_gpa", "relation", "value_lower_gpa", "value_upper_gpa", "uncertainty_gpa", "approximate")
            if any(getattr(current, key) != getattr(original, key) for key in keys):
                return replace(current, pressure_state="ambiguous")
    return current


def fact_sentence(record: dict[str, Any]) -> str | None:
    """Render one NER record as a natural-language fact sentence.

    Returns None for a record with no usable signal (no formula, or a
    bare formula with nothing to say about it — the abstract chunk
    already covers mere mentions).
    """
    if not isinstance(record, Mapping):
        return None
    formula = _text(record.get("formula"), 200)
    if not formula:
        return None

    tc = _quantity(record, "tc_kelvin")
    pressure = _pressure(record)
    method = _field(record, "method")
    measurement = _field(record, "measurement_method") or _field(record, "measurement")
    family = _field(record, "family")
    doping = _doping_phrase(record)
    structure = _field(record, "crystal_structure")
    sample = _field(record, "sample_form")
    origin, classification_status, role = _classification(record)
    outcome = _outcome(record)
    tc_text = _quantity_text(tc, "Tc")

    # Skip records that carry nothing beyond the formula — they add noise,
    # not recall (the abstract already mentions the compound).
    # Note: tc_regime is intentionally NOT a "has context" signal — it
    # defaults to bulk_equilibrium on almost every record, so a bare
    # formula + regime is still noise (the abstract already mentions the
    # compound). It only colours the sentence when other signal exists.
    if not tc_text and outcome == "unspecified" and not any(
        (pressure.pressure_state in {"explicit_ambient", "reported"}, family, doping, structure, sample)
    ):
        return None

    parts: list[str] = []
    if outcome == "not_detected":
        sentence = f"For {formula}, the extraction records superconductivity not detected; no positive Tc is inferred"
        minimum = _quantity_text(_quantity(record, "minimum_temperature_k"), "minimum test temperature")
        sentence += f" ({minimum or 'minimum test temperature not reported'})"
    elif outcome in {"conflicted", "unresolved"}:
        sentence = f"For {formula}, the extracted superconductivity outcome is {outcome}; no positive Tc is inferred"
    elif tc_text:
        verb = "cites a prior" if role == "cited" else "reports a" if role == "primary" else "lists a"
        qualifier = {"Observed": "reported observation", "Computed": "computed result", "Inferred": "inferred result",
                     "AI-Proposed": "AI-proposed hypothesis", "Unknown": "result of unresolved origin"}[origin]
        sentence = f"For {formula}, the source {verb} {qualifier}: {tc_text}"
    else:
        sentence = f"{formula} is reported without a usable Tc quantity"

    quals = list(dict.fromkeys(q for q in (method, measurement) if q))
    if quals:
        sentence += f" (reported method: {', '.join(quals)})"

    # Pressure evidence is result-bound. Neither bulk nor a qualitative
    # regime label can manufacture an ambient/numeric pressure assertion.
    if pressure.pressure_state == "explicit_ambient":
        sentence += " at ambient pressure"
    elif pressure.pressure_state == "reported":
        if pressure.pressure_gpa is not None:
            value = f"{pressure.pressure_gpa:g}"
            if pressure.uncertainty_gpa is not None:
                value += f" ± {pressure.uncertainty_gpa:g}"
            prefix = "approximately " if pressure.approximate else ""
            sentence += f" at {prefix}{value} GPa"
        elif pressure.relation == "interval":
            sentence += f" at pressure in [{pressure.value_lower_gpa:g}, {pressure.value_upper_gpa:g}] GPa"
        elif pressure.relation in {"lt", "le", "gt", "ge"}:
            operator = {"lt": "<", "le": "≤", "gt": ">", "ge": "≥"}[pressure.relation]
            value = pressure.value_upper_gpa if pressure.relation in {"lt", "le"} else pressure.value_lower_gpa
            sentence += f" at pressure {operator} {value:g} GPa"
    elif pressure.pressure_state == "ambiguous":
        sentence += " (pressure unresolved)"
    else:
        sentence += " (pressure not reported)"

    parts.append(sentence + ".")

    tags: list[str] = [f"origin: {origin}", f"origin status: {classification_status}", f"source role: {role}"]
    if family:
        tags.append(str(family))
    if structure:
        tags.append(str(structure))
    if sample:
        tags.append(str(sample))
    if doping:
        tags.append(doping)
    for key, label in (("tc_criterion", "Tc criterion"), ("tc_type", "Tc type"), ("substrate", "substrate"),
                       ("tc_regime", "reported regime")):
        if value := _field(record, key):
            tags.append(f"{label}: {value}")
    if field := _quantity_text(_quantity(record, "magnetic_field_t"), "magnetic field"):
        tags.append(field)
    if tc.get("unit_basis") == "field_schema_assumption" and tc_text and outcome not in {"not_detected", "unresolved", "conflicted"}:
        tags.append("Tc unit follows the legacy field schema")
    if tags:
        parts.append(f"[{'; '.join(tags)}]")
    return " ".join(parts)


def _doping_phrase(record: dict[str, Any]) -> str | None:
    """Render doping_type + doping_level into a short tag, or None."""
    dtype = _field(record, "doping_type")
    quantity = _quantity(record, "doping_level")
    level = _quantity_text(quantity, "x")
    if dtype in (None, "none") and level is None:
        return None
    if level:
        # Dimensionless one is the unit, not an extra measured value.
        level = level.removesuffix(" 1").replace("x = ", "x=")
        return f"doping: {dtype + ' ' if dtype not in (None, 'none') else ''}{level}"
    return f"doping: {dtype}"


def _ordered_records(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Primary (the paper's own) records first, then cited, so the
    truncation cap keeps the most relevant facts."""
    records = [record for record in materials if isinstance(record, Mapping)]
    return sorted(records, key=lambda record: {"primary": 0, "unknown": 1, "conflicted": 2, "cited": 3}[_classification(record)[2]])


class FactChunkLimitError(ValueError):
    """An atomic fact cannot fit; no partial fact or successful paper is emitted."""

    reason_code = "atomic_fact_exceeds_complete_text_limit"


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
    settings = get_settings()
    validate_chunk_settings(settings.chunk_size_tokens, settings.chunk_overlap_tokens)
    if type(start_index) is not int or not 0 <= start_index <= 32767:
        raise ValueError("Invalid Facts starting index")
    prefix = build_bounded_prefix(meta.title, "Facts", max_tokens=settings.chunk_size_tokens)
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
        text = prefix + sentence
        try:
            token_count = require_token_budget(text, max_tokens=settings.chunk_size_tokens)
        except ValueError:
            # Do not split away a negation, pressure, or origin qualifier, and
            # do not expose original/result text in operational error output.
            raise FactChunkLimitError(FactChunkLimitError.reason_code) from None
        if idx > 32767:
            raise ValueError("Facts chunk index exceeds storage limit")
        out.append(Chunk(
            id=f"{meta.paper_id}_fact_{idx:03d}",
            paper_id=meta.paper_id,
            chunk_index=idx,
            section="Facts",
            text=text,
            token_count=token_count,
            materials_mentioned=[record],
            parser_version="sclib-structured-fact-projection/1.0.0",
            evidence_candidate={
                "version": "rag-evidence/1.0.0", "chunk_kind": "derived_fact",
                "parent_record": record,
                "extraction_version": _text(record.get("extractor_version"), 80) or "legacy_unknown",
                "rendering_version": FACT_RENDERER_VERSION,
                "source_capture_id": None, "source_locator": {},
                "unresolved_reason": "secondary_origin_unresolved" if _classification(record)[2] == "cited" else "missing_original_source",
                "permission_status": "unresolved",
            },
        ))
        idx += 1
    return out


def build_authorized_chunks(
    meta: ApsArticleMeta,
    materials: list[dict[str, Any]],
) -> list[Chunk]:
    """Existing APS pipeline output: abstract + derived extraction sentences.

    NEVER includes APS full-text body. The legacy function name does not
    establish text-use permission: the typed lineage remains unreviewed and
    cannot grant reproduction, model-input, or redistribution rights.
    """
    abstract_only = ParsedPaper(meta=meta, sections=[], has_latex_source=False)
    abstract_chunks = chunk_paper(abstract_only)
    facts = build_fact_chunks(meta, materials, start_index=len(abstract_chunks))
    return abstract_chunks + facts
