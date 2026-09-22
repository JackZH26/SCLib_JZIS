"""Bounded text-free extraction projection shared with ingestion.

Input hashes identify supplied records, not reviewed canonical results. Never
persist raw quantity strings, source contexts, quotations, or arbitrary NER
metadata in this lineage projection. Permission is not inferred here.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from uuid import UUID, uuid5

if __package__ == "ingestion":
    from .claims.outcomes import outcome_conflicts_with_positive
    from .extract.scientific_values import FIELD_UNITS, record_quantity
else:
    from .claim_outcomes import outcome_conflicts_with_positive
    from .scientific_values import FIELD_UNITS, record_quantity
from .result_semantics import classify_result

VERSION = "rag-evidence/1.0.0"
PROJECTION_VERSION = "rag-result-projection/1.0.0"
MAX_INPUT_BYTES = 1024 * 1024
MAX_PROJECTION_BYTES = 16384
QUANTITY_FIELDS = ("status", "relation", "value_kind", "value", "lower", "upper", "uncertainty",
                   "approximate", "unit", "unit_basis")
NAMESPACE = UUID("52bd30c8-0b5b-485b-9586-d28b931795e9")
KINDS = {"original_passage", "abstract", "derived_fact", "retained_legacy_snapshot"}
REASONS = {"legacy_unresolved", "original_binding_unreviewed", "missing_original_source", "secondary_origin_unresolved"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LOCATOR_TEXT = {"section", "table", "figure", "equation", "xml_xpath", "section_path"}
_LOCATOR_INT = {"page", "page_start", "page_end", "row", "column", "char_start", "char_end", "span_start", "span_end"}


def canonical(value):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 20000 or depth > 20:
            raise ValueError("Evidence input JSON resource limit")
        if isinstance(item, Mapping):
            if any(type(key) is not str for key in item):
                raise ValueError("Evidence input object keys must be strings")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) > MAX_INPUT_BYTES:
        raise ValueError("Evidence input byte limit")
    return body


def input_record_sha256(record):
    if not isinstance(record, Mapping):
        raise ValueError("An extraction record object is required")
    return hashlib.sha256(canonical(record)).hexdigest()


def extraction_projection(record):
    input_record_sha256(record)
    raw = record.get("raw_extraction")
    inputs = (record, raw) if isinstance(raw, Mapping) else (record,)
    quantities = {}
    for field in FIELD_UNITS:
        proposal = record_quantity(record, field)
        if isinstance(raw, Mapping) and field in raw:
            original = record_quantity(raw, field)
            typed = record.get("scientific_values")
            if isinstance(typed, Mapping) and field in typed:
                if any(proposal[key] != original[key] for key in QUANTITY_FIELDS):
                    proposal = {**proposal, "status": "invalid", "relation": "unreported", "value_kind": "unreported",
                                "value": None, "lower": None, "upper": None, "uncertainty": None}
            else:
                proposal = original
        if proposal["status"] != "unreported":
            quantities[field] = {key: proposal[key] for key in QUANTITY_FIELDS}
    classifications = [classify_result(item) for item in inputs]
    origins = {item.knowledge_origin for item in classifications} - {"Unknown"}
    roles = {item.source_role for item in classifications} - {"unknown"}
    origin_fields = ("knowledge_origin", "result_origin", "evidence_role", "evidence_type", "claim_kind",
                     "source_role", "measurement", "measurement_method", "method")
    conflicted = len(origins) > 1 or any(item.classification_status == "conflicted" for item in classifications) or any(
        item.get(key) is not None and type(item[key]) is not str for item in inputs for key in origin_fields)
    conflicted |= any(type(flag) is str and flag.split(":", 1)[0] in origin_fields
        for item in inputs for flag in (item.get("validation_flags") if type(item.get("validation_flags")) is list else []))
    outcome_fields = ("result_status", "outcome_state", "outcome")
    bool_fields = ("no_transition", "not_detected", "superconductivity_observed", "transition_observed", "is_superconducting")
    malformed_outcome = any(item.get(key) is not None and type(item[key]) is not str
        for item in inputs for key in outcome_fields) or any(item.get(key) is not None and type(item[key]) is not bool
        for item in inputs for key in bool_fields)
    malformed_outcome |= any(type(flag) is str and flag.split(":", 1)[0] in outcome_fields + bool_fields
        for item in inputs for flag in (item.get("validation_flags") if type(item.get("validation_flags")) is list else []))
    result = {"version": PROJECTION_VERSION, "quantities": quantities,
              "knowledge_origin": next(iter(origins)) if len(origins) == 1 and not conflicted else "Unknown",
              "source_role": next(iter(roles)) if len(roles) == 1 else "conflicted" if roles else "unknown",
              "classification_status": "conflicted" if conflicted else "resolved" if origins else "unknown",
              "positive_interpretation_blocked": malformed_outcome or any(outcome_conflicts_with_positive(item) for item in inputs)}
    if len(canonical(result)) > MAX_PROJECTION_BYTES:
        raise ValueError("Evidence projection byte limit")
    return result


def _version(value):
    if type(value) is not str or not value.strip() or len(value) > 160 or any(ord(c) < 32 for c in value):
        raise ValueError("A bounded producer version is required")
    return value


def validate_locator(value):
    if type(value) is not dict or set(value) - _LOCATOR_TEXT - _LOCATOR_INT or len(canonical(value)) > 4096:
        raise ValueError("Only bounded source coordinates are allowed")
    for key, item in value.items():
        if key in _LOCATOR_TEXT:
            if type(item) is not str or not item.strip() or len(item) > 300 or any(ord(c) < 32 for c in item):
                raise ValueError("Invalid text source coordinate")
        elif type(item) is not int or not 0 <= item <= 1_000_000_000:
            raise ValueError("Invalid numeric source coordinate")
    for lower, upper in (("page_start", "page_end"), ("char_start", "char_end"), ("span_start", "span_end")):
        if (lower in value) != (upper in value) or lower in value and (value[lower] > value[upper]
                or lower != "page_start" and value[lower] == value[upper]):
            raise ValueError("Incomplete or invalid source span")
    return dict(value)


def validate_candidate(value):
    fields = {"version", "chunk_kind", "parent_record", "extraction_version", "rendering_version",
              "source_capture_id", "source_locator", "unresolved_reason", "permission_status"}
    if type(value) is not dict or set(value) - fields or value.get("version") != VERSION or type(value.get("chunk_kind")) is not str or value.get("chunk_kind") not in KINDS:
        raise ValueError("Invalid evidence candidate version or kind")
    result = {"parent_record": None, "extraction_version": None, "rendering_version": None,
              "source_capture_id": None, "source_locator": {}, "unresolved_reason": "missing_original_source",
              "permission_status": "unresolved", **json.loads(canonical(value))}
    if result["chunk_kind"] == "derived_fact":
        input_record_sha256(result["parent_record"])
        _version(result["extraction_version"])
        _version(result["rendering_version"])
    elif result["parent_record"] is not None or result["extraction_version"] is not None:
        raise ValueError("Original evidence cannot claim a derived parent")
    if result["rendering_version"] is not None:
        _version(result["rendering_version"])
    if result["source_capture_id"] is not None:
        result["source_capture_id"] = str(UUID(str(result["source_capture_id"])))
    result["source_locator"] = validate_locator(result["source_locator"])
    if type(result["unresolved_reason"]) is not str or type(result["permission_status"]) is not str or result["unresolved_reason"] not in REASONS or result["permission_status"] not in {"unresolved", "restricted"}:
        raise ValueError("Evidence candidates cannot grant roots or permission")
    if result["chunk_kind"] == "retained_legacy_snapshot":
        if (result["rendering_version"] != "sclib-legacy-input-pack/1.0.0"
                or result["source_capture_id"] is not None or result["unresolved_reason"] != "legacy_unresolved"
                or set(result["source_locator"]) != {"char_start", "char_end"}):
            raise ValueError("Retained legacy snapshots require exact new windows and unresolved original lineage")
    return result


def build_revision_rows(*, paper_id, chunk_id, chunk_text, chunk_binding_sha256, source_snapshot_sha256, candidate):
    """Pure insert rows; hashes/snapshots of actual SQL rows come from writer.

    The candidate is never itself authority. The writer obtains paper/chunk
    bindings under the shared 540 integrity fence and SQL triggers recheck.
    """
    selected = validate_candidate(candidate)
    if type(chunk_id) is not str or not 1 <= len(chunk_id) <= 200:
        raise ValueError("An actual chunk identity is required")
    if type(chunk_text) is not str or len(chunk_text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Bounded actual chunk text required")
    if any(type(value) is not str or not _SHA.fullmatch(value) for value in (chunk_binding_sha256, source_snapshot_sha256)):
        raise ValueError("Actual SQL snapshot hashes required")
    parent = None
    if selected["chunk_kind"] == "derived_fact":
        parent = {"paper_id": paper_id, "input_record_sha256": input_record_sha256(selected["parent_record"]),
                  "extractor_version": selected["extraction_version"], "projection_version": PROJECTION_VERSION,
                  "projection_json": extraction_projection(selected["parent_record"]),
                  "source_snapshot_sha256": source_snapshot_sha256, "scientific_acceptance": False}
        parent["id"] = str(uuid5(NAMESPACE, "extraction:" + hashlib.sha256(canonical(parent)).hexdigest()))
    evidence = {"paper_id": paper_id, "chunk_key": chunk_id, "version": VERSION, "chunk_kind": selected["chunk_kind"],
                "content_sha256": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                "chunk_binding_sha256": chunk_binding_sha256, "source_snapshot_sha256": source_snapshot_sha256,
                "parent_extraction_revision_id": parent["id"] if parent else None,
                **{key: selected[key] for key in ("source_capture_id", "source_locator", "extraction_version",
                    "rendering_version", "unresolved_reason", "permission_status")}, "root_status": "unresolved"}
    evidence["id"] = str(uuid5(NAMESPACE, "evidence:" + hashlib.sha256(canonical(evidence)).hexdigest()))
    return {"extraction": parent, "evidence": evidence}


def validate_evidence_descriptor(value):
    """Closed wire contract; all positive authority flags must remain false."""
    fields = {"version", "chunk_kind", "evidence_revision_id", "evidence_record_sha256", "content_sha256",
              "parent_result_revision_id", "parent_result_sha256", "extraction_version", "rendering_version",
              "source_capture_id", "source_locator", "root_status", "permission_status", "currentness",
              "warning_codes", "support_eligible", "independent_evidence", "scientific_acceptance"}
    if type(value) is not dict or set(value) != fields or value.get("version") != VERSION:
        raise ValueError("Malformed evidence descriptor")
    if type(value["chunk_kind"]) is not str or value["chunk_kind"] not in KINDS | {"legacy_unknown"} or value["root_status"] != "unresolved":
        raise ValueError("Unrecognized evidence provenance")
    if type(value["permission_status"]) is not str or type(value["currentness"]) is not str or value["permission_status"] not in {"unresolved", "restricted"} or value["currentness"] not in {"current", "stale", "unresolved"}:
        raise ValueError("Unrecognized evidence admission state")
    for key in ("support_eligible", "independent_evidence", "scientific_acceptance"):
        if value[key] is not False:
            raise ValueError("Evidence lineage cannot assert scientific authority")
    for key in ("evidence_revision_id", "parent_result_revision_id", "source_capture_id"):
        if value[key] is not None and (type(value[key]) is not str or str(UUID(value[key])) != value[key]):
            raise ValueError("Invalid evidence identifier")
    for key in ("content_sha256", "evidence_record_sha256", "parent_result_sha256"):
        if value[key] is None and key != "content_sha256":
            continue
        if type(value[key]) is not str or not _SHA.fullmatch(value[key]):
            raise ValueError("Invalid evidence digest")
    for key in ("extraction_version", "rendering_version"):
        if value[key] is not None:
            _version(value[key])
    if value["chunk_kind"] == "legacy_unknown":
        if any(value[key] is not None for key in ("evidence_revision_id", "evidence_record_sha256", "parent_result_revision_id",
                "parent_result_sha256", "source_capture_id", "extraction_version", "rendering_version")) or value["currentness"] == "current":
            raise ValueError("Legacy lineage cannot fabricate retained revisions")
    else:
        if value["evidence_revision_id"] is None or value["evidence_record_sha256"] is None:
            raise ValueError("Typed evidence requires an exact retained revision")
        parent_keys = ("parent_result_revision_id", "parent_result_sha256", "extraction_version")
        if value["chunk_kind"] == "derived_fact":
            if any(value[key] is None for key in (*parent_keys, "rendering_version")):
                raise ValueError("Derived evidence requires an exact retained parent")
        elif any(value[key] is not None for key in parent_keys):
            raise ValueError("Original evidence cannot fabricate a derived parent")
    if value["chunk_kind"] == "retained_legacy_snapshot":
        if (value["rendering_version"] != "sclib-legacy-input-pack/1.0.0" or value["source_capture_id"] is not None
                or set(value["source_locator"]) != {"char_start", "char_end"}):
            raise ValueError("Retained legacy lineage requires exact replay coordinates")
    validate_locator(value["source_locator"])
    if type(value["warning_codes"]) is not list or len(value["warning_codes"]) > 12 or any(
            type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) for code in value["warning_codes"]):
        raise ValueError("Invalid evidence warnings")
    return json.loads(canonical(value))
