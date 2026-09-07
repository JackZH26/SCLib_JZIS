"""Bounded text-structure proposals, never scientific approval or coordinates.

Vendored byte-for-byte by API and ingestion. Exact text checks at extraction
are not authoritative source-revision or material/state adjudication.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from .pressure_semantics import classify_pressure
from .result_semantics import classify_result

if __package__ == "ingestion":
    from .extract.scientific_values import record_quantity
else:
    from .scientific_values import record_quantity

STRUCTURE_EVIDENCE_VERSION = "structure-evidence/1.0.0"
STRUCTURE_EVIDENCE_FIELDS = ("structure_phase", "crystal_structure", "space_group")
MAX_RECORDS = 1000
MAX_PROPOSALS = 30
MAX_MENTIONS = 20
MAX_TEXT_CHARS = 800
MAX_SOURCE_CHARS = 16000
MAX_CLAIMS_PER_RECORD = 12
_SUBJECT_KEYS = ("formula_raw", "formula", "sample_id", "sample_label", "state_id", "structure_id", "run_id", "doping_type")
_LOCATOR_KEYS = ("section", "page", "table", "figure", "row", "column")
_CAUTION = re.compile(r"\b(?:not|no|neither|unconfirmed|uncertain|possibly|possible|candidate|suggested|proposed|previously|cited|reference|references|reported by|et al)\b|\[\s*\d|未|不|可能|此前|文献|引用", re.IGNORECASE)
_MULTI = re.compile(r"\b(?:respectively|whereas|versus|compared with|transition between)\b|分别|相比|而", re.IGNORECASE)
_PRESSURE = re.compile(r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*(GPa|kbar|MPa)\b", re.IGNORECASE)
_DOPING = re.compile(r"\bx\s*=\s*([+-]?\d+(?:\.\d+)?)\b")
_MENTION_PATTERNS = (
    (re.compile(r"\b(?:1212|2222|1313)\s+phase\b", re.IGNORECASE), "phase_label"),
    (re.compile(r"\binfinite[- ]layer\b", re.IGNORECASE), "phase_label"),
    (re.compile(r"\bRuddlesden[- ]Popper\s*n\s*=\s*[123]\b", re.IGNORECASE), "phase_label"),
    (re.compile(r"\b(?:YBCO|LSCO|La214|Bi[- ]?2212|Bi[- ]?2223|Hg12(?:01|12|23))\b", re.IGNORECASE), "family_alias_not_structure"),
)


def _text(value: Any, limit: int = 200) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= limit else None


def _scalar(value: Any, limit: int = 200) -> Any:
    if isinstance(value, str):
        return _text(value, limit)
    if type(value) in (int, float):
        try:
            return value if math.isfinite(value) else None
        except OverflowError:
            return None
    return None


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _selected(raw: Any, keys: tuple, limit: int = 200) -> dict:
    return {key: item for key in keys if (item := _scalar(raw.get(key), limit)) is not None} if isinstance(raw, Mapping) else {}


def _raw(record: Mapping) -> Mapping:
    # Original extractor output takes precedence over its normalized display.
    value = record.get("raw_extraction")
    return value if isinstance(value, Mapping) else record


def _subject(record: Mapping) -> dict:
    raw = _raw(record)
    result = _selected(raw, _SUBJECT_KEYS)
    pressure = classify_pressure(raw)
    result["pressure"] = {"state": pressure.pressure_state, "relation": pressure.relation,
                          "value": pressure.pressure_gpa, "lower": pressure.value_lower_gpa,
                          "upper": pressure.value_upper_gpa, "uncertainty": pressure.uncertainty_gpa,
                          "approximate": pressure.approximate}
    doping = record_quantity(raw, "doping_level")
    result["doping"] = {key: doping.get(key) for key in ("status", "relation", "value", "lower", "upper", "uncertainty", "unit")}
    result["identity_status"] = "source_asserted_not_adjudicated"
    return result


def _source(record: Mapping, paper_id: Any = None, *, content_hash: Any = None, source_revision: Any = None) -> dict:
    raw = _raw(record)
    valid_hash = content_hash if isinstance(content_hash, str) and re.fullmatch(r"[0-9a-f]{64}", content_hash) else None
    return {"paper_id": _text(paper_id) or _text(record.get("paper_id")) or _text(raw.get("paper_id")),
            "content_sha256": valid_hash,
            "content_identity_basis": "assembled_ner_input_utf8" if valid_hash else "unavailable",
            "publication_revision": _text(source_revision, 100),
            "publication_revision_status": "source_asserted_not_verified" if _text(source_revision, 100) else "unknown",
            "source_verification": "not_rechecked_against_source"}


def _base_proposal(record: Mapping, field: str, value: Any, claim: Mapping | None = None) -> dict:
    raw = _raw(record)
    candidate = claim if isinstance(claim, Mapping) else raw
    reasons = ["text_claim_pending_review", "coordinates_not_validated"]
    text = _text(candidate.get("evidence_text"), MAX_TEXT_CHARS) or _text(candidate.get("source_quote"), MAX_TEXT_CHARS)
    if text is None:
        reasons.append("local_evidence_missing_or_oversized")
    safe_value = _text(value, 160)
    if safe_value is None:
        reasons.append("structure_value_missing_invalid_or_oversized")
    origin = classify_result(raw)
    if origin.source_role == "cited":
        reasons.append("cited_structure_requires_review")
    if origin.source_role == "conflicted" or origin.classification_status == "conflicted":
        reasons.append("result_classification_conflict")
    return {"field": field, "value": safe_value, "status": "pending", "association": "unassigned",
            "subject": _subject(record), "source": _source(record),
            "record_origin": origin.knowledge_origin, "source_role": origin.source_role,
            "evidence": {"text": text, "locator": None,
                         "source_reported_locator": _selected(candidate.get("source_locator"), _LOCATOR_KEYS, 120),
                         "verification": "not_rechecked_against_source"},
            "reason_codes": reasons, "representation": "text_claim", "coordinate_artifact_id": None,
            "scientific_acceptance": False}


def _proposal_id(proposal: dict) -> str:
    return "structure-proposal:" + _digest({key: value for key, value in proposal.items() if key not in {"proposal_id", "reason_codes", "occurrence_count"}})


def _candidate_proposals(record: Mapping) -> tuple[list[dict], bool]:
    raw = _raw(record)
    proposals = []
    claims = raw.get("structure_claims", [])
    valid_claims = isinstance(claims, list)
    complete = valid_claims and len(claims) <= MAX_CLAIMS_PER_RECORD
    for claim in claims[:MAX_CLAIMS_PER_RECORD] if valid_claims else []:
        if not isinstance(claim, Mapping) or claim.get("field") not in STRUCTURE_EVIDENCE_FIELDS:
            complete = False
            continue
        proposals.append(_base_proposal(record, claim["field"], claim.get("value"), claim))
    for field in STRUCTURE_EVIDENCE_FIELDS:
        # Do not discard incompatible top-level and typed extraction channels.
        if raw.get(field) is not None:
            value = raw[field]
            matching = [p for p in proposals if p["field"] == field and p["value"] == value]
            if not matching:
                proposals.append(_base_proposal(record, field, value))
        if record is not raw and record.get(field) is not None and record.get(field) != raw.get(field):
            proposal = _base_proposal(record, field, record[field])
            proposal["reason_codes"].append("legacy_normalized_channel_unlinked_to_original_extraction")
            proposals.append(proposal)
    for field in STRUCTURE_EVIDENCE_FIELDS:
        alternatives = {p["value"] for p in proposals if p["field"] == field and p["value"] is not None}
        if len(alternatives) > 1:
            for proposal in proposals:
                if proposal["field"] == field:
                    proposal["association"] = "conflicted"
                    proposal["reason_codes"].append("conflicting_extraction_channels")
    return proposals, complete


def _literal(text: str, value: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text) is not None


def _check_local(proposal: dict, body: str, formulas: set[str]) -> None:
    quote, value = proposal["evidence"]["text"], proposal["value"]
    reasons = proposal["reason_codes"]
    if quote is None or value is None:
        return
    start = body.find(quote)
    if start < 0:
        reasons.append("quotation_not_found_in_extraction_input")
        return
    if body.find(quote, start + 1) >= 0:
        reasons.append("quotation_occurs_multiple_times")
        proposal["association"] = "ambiguous"
        return
    proposal["evidence"]["locator"] = {"kind": "assembled_text_char_span", "start": start, "end": start + len(quote)}
    proposal["evidence"]["verification"] = "exact_span_at_extraction_not_scientific_review"
    subject = proposal["subject"]
    formula = subject.get("formula_raw") or subject.get("formula")
    if not formula or not _literal(quote, formula) or not _literal(quote, value):
        reasons.append("material_and_structure_not_both_literal_in_local_span")
        return
    if any(other != formula and _literal(quote, other) for other in formulas):
        reasons.append("multiple_materials_in_local_span")
    if _CAUTION.search(quote) or proposal["source_role"] in {"cited", "conflicted"}:
        reasons.append("cited_negative_or_tentative_local_context")
    if _MULTI.search(quote) or "\n" in quote or re.search(r"[.!?。！？]\s+[A-Za-z\u4e00-\u9fff]", quote):
        reasons.append("compound_local_statement_requires_review")
    for key in ("sample_id", "sample_label", "state_id", "structure_id", "run_id"):
        if subject.get(key) and not _literal(quote, str(subject[key])):
            reasons.append("sample_or_state_not_literal_in_local_span")
    pressures = [(float(number) * {"gpa": 1, "kbar": .1, "mpa": .001}[unit.lower()]) for number, unit in _PRESSURE.findall(quote)]
    pressure = subject["pressure"]
    ambient = re.search(r"\b(?:ambient|atmospheric|zero) pressure\b|常压", quote, re.IGNORECASE)
    if ambient:
        pressures.append(0.0)
    if (pressures or pressure["state"] in {"reported", "explicit_ambient"}) and (
        len(pressures) != 1 or pressure["value"] is None or pressures[0] != pressure["value"]
        or pressure["relation"] not in {"exact", None} or pressure["uncertainty"] is not None or pressure["approximate"]
    ):
        reasons.append("pressure_context_unresolved_or_conflicting")
    dopings = [float(value) for value in _DOPING.findall(quote)]
    doping = subject["doping"]
    if (dopings or doping.get("status") == "parsed") and (
        len(dopings) != 1 or doping.get("value") is None or dopings[0] != doping["value"]
        or doping.get("relation") != "exact" or doping.get("uncertainty") is not None
    ):
        reasons.append("doping_context_unresolved_or_conflicting")
    baseline = {"text_claim_pending_review", "coordinates_not_validated"}
    if set(reasons) <= baseline:
        proposal["association"] = "literal_local"
        reasons.append("literal_cooccurrence_not_relation_adjudication")
    elif proposal["association"] != "conflicted":
        proposal["association"] = "ambiguous"


def _mentions(body: str, source: dict) -> tuple[list[dict], bool]:
    found = {}
    complete = True
    for pattern, basis in _MENTION_PATTERNS:
        for match in pattern.finditer(body):
            if len(found) >= MAX_MENTIONS:
                complete = False
                break
            start, end = match.span()
            # Coordinates refer to the captured assembled input, not PDF pages.
            left = max(body.rfind(mark, 0, start) for mark in ("\n", ".", "!", "?", "。")) + 1
            right_candidates = [position + 1 for mark in ("\n", ".", "!", "?", "。")
                                if (position := body.find(mark, end)) >= 0]
            right = min(right_candidates) if right_candidates else len(body)
            context_complete = right - left <= MAX_TEXT_CHARS
            if not context_complete:
                left = max(left, start - 200)
                right = min(right, left + MAX_TEXT_CHARS)
            item = {"value": match.group(), "field": "structure_phase", "status": "pending", "association": "unassigned",
                    "basis": basis, "source": source,
                    "evidence": {"text": body[left:right], "locator": {"kind": "assembled_text_char_span", "start": left, "end": right},
                                 "mention_locator": {"kind": "assembled_text_char_span", "start": start, "end": end},
                                 "context_complete": context_complete,
                                 "verification": "exact_span_at_extraction_not_scientific_review"},
                    "reason_codes": ["unassigned_document_mention", "not_material_structure_evidence"],
                    "representation": "text_claim", "coordinate_artifact_id": None, "scientific_acceptance": False}
            item["proposal_id"] = _proposal_id(item)
            found[item["proposal_id"]] = item
    return [found[key] for key in sorted(found)], complete


def annotate_structure_records(records: Any, *, body: str, paper_id: str, source_revision: str | None = None) -> list:
    """Keep originals; attach bounded pending proposals, without filling fields."""
    if not isinstance(records, (list, tuple)):
        return []
    valid_body = isinstance(body, str)
    bounded_body = body[:MAX_SOURCE_CHARS] if valid_body else ""
    content_hash = hashlib.sha256(bounded_body.encode()).hexdigest() if bounded_body else None
    source = _source({}, paper_id, content_hash=content_hash, source_revision=source_revision)
    mentions, mention_complete = _mentions(bounded_body, source)
    complete = valid_body and len(body) <= MAX_SOURCE_CHARS and len(records) <= MAX_RECORDS and mention_complete
    formulas = {value for record in records[:MAX_RECORDS] if isinstance(record, Mapping)
                for key in ("formula_raw", "formula") if (value := _text(_raw(record).get(key))) is not None}
    result = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            result.append(record)
            continue
        copied = dict(record)
        proposals, record_complete = _candidate_proposals(record) if index < MAX_RECORDS else ([], False)
        for proposal in proposals:
            proposal["source"] = source
            _check_local(proposal, bounded_body, formulas)
            if not complete:
                proposal["reason_codes"].append("extraction_input_coverage_incomplete")
                proposal["association"] = "unassigned"
            proposal["reason_codes"] = sorted(set(proposal["reason_codes"]))
            proposal["proposal_id"] = _proposal_id(proposal)
        copied["structure_evidence"] = {"version": STRUCTURE_EVIDENCE_VERSION, "proposals": proposals,
                                        "unassigned_mentions": mentions, "assessment_complete": complete and record_complete,
                                        "scientific_acceptance": False, "coordinate_status": "not_validated"}
        result.append(copied)
    return result


def _public_annotation(item: Any, *, field: str | None = None) -> dict | None:
    """Stored annotations are untrusted proposals, not source authentication."""
    if not isinstance(item, Mapping) or item.get("field") not in STRUCTURE_EVIDENCE_FIELDS:
        return None
    value = _text(item.get("value"), 160)
    source = item.get("source") if isinstance(item.get("source"), Mapping) else {}
    evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
    proposal = _base_proposal({}, field or item["field"], value)
    proposal["source"] = _source({}, source.get("paper_id"), content_hash=source.get("content_sha256"), source_revision=source.get("publication_revision"))
    declared_subject = item.get("subject")
    proposal["subject"] = _selected(declared_subject, _SUBJECT_KEYS)
    if isinstance(declared_subject, Mapping):
        for key in ("pressure", "doping"):
            proposal["subject"][key] = _selected(declared_subject.get(key), ("state", "status", "relation", "value", "lower", "upper", "uncertainty", "unit"), 40)
    proposal["subject"]["identity_status"] = "source_asserted_not_adjudicated"
    association = item.get("association")
    proposal["source_declared_association"] = association if association in ("literal_local", "ambiguous", "conflicted", "unassigned") else "unknown"
    proposal["evidence"]["text"] = _text(evidence.get("text"), MAX_TEXT_CHARS)
    span = evidence.get("locator")
    if (isinstance(span, Mapping) and span.get("kind") == "assembled_text_char_span"
            and type(span.get("start")) is int and type(span.get("end")) is int
            and 0 <= span["start"] < span["end"] <= MAX_SOURCE_CHARS
            and proposal["evidence"]["text"] is not None and span["end"] - span["start"] == len(proposal["evidence"]["text"])):
        proposal["evidence"]["locator"] = {"kind": "assembled_text_char_span", "start": span["start"], "end": span["end"]}
    proposal["reason_codes"] = ["stored_annotation_not_source_reverified", "text_claim_pending_review", "coordinates_not_validated"]
    if span is not None and proposal["evidence"]["locator"] is None:
        proposal["reason_codes"].append("stored_source_locator_invalid")
    if source.get("content_sha256") is not None and proposal["source"]["content_sha256"] is None:
        proposal["reason_codes"].append("stored_source_content_hash_invalid")
    mention_span = evidence.get("mention_locator")
    if isinstance(mention_span, Mapping) and proposal["evidence"]["locator"]:
        context = proposal["evidence"]["locator"]
        if (type(mention_span.get("start")) is int and type(mention_span.get("end")) is int
                and context["start"] <= mention_span["start"] < mention_span["end"] <= context["end"]):
            proposal["evidence"]["mention_locator"] = {"kind": "assembled_text_char_span", "start": mention_span["start"], "end": mention_span["end"]}
    if type(evidence.get("context_complete")) is bool:
        proposal["evidence"]["context_complete"] = evidence["context_complete"]
    return proposal


def build_structure_evidence(records: Any, *, scope_id: str, source_statuses: Mapping | None = None) -> dict:
    """Public fail-closed projection. Never emits an accepted structural value."""
    valid = isinstance(records, (list, tuple))
    rows = records if valid else []
    complete = valid and len(rows) <= MAX_RECORDS
    if _text(scope_id) is None:
        scope_id = "unresolved_scope"
        complete = False
    warnings = {"structure_relations_pending_review", "source_content_not_reverified", "text_is_not_coordinate_structure"}
    proposals, mentions = {}, {}
    for record in rows[:MAX_RECORDS]:
        if not isinstance(record, Mapping):
            complete = False
            warnings.add("invalid_record_skipped")
            continue
        candidates, local_complete = _candidate_proposals(record)
        complete &= local_complete
        annotation = record.get("structure_evidence")
        if isinstance(annotation, Mapping) and annotation.get("version") == STRUCTURE_EVIDENCE_VERSION:
            for key, target, limit in (("proposals", candidates, MAX_CLAIMS_PER_RECORD + 3), ("unassigned_mentions", None, MAX_MENTIONS)):
                items = annotation.get(key, [])
                if not isinstance(items, list):
                    complete = False
                    continue
                if len(items) > limit:
                    complete = False
                for item in items[:limit]:
                    safe = _public_annotation(item)
                    if safe is None:
                        complete = False
                        continue
                    if key == "proposals":
                        expected = _subject(record)
                        declared = safe["subject"]
                        expected_paper = _source(record)["paper_id"]
                        if expected_paper and safe["source"]["paper_id"] not in (None, expected_paper):
                            safe["reason_codes"].append("stored_annotation_source_mismatch")
                        if any(expected.get(name) is not None and declared.get(name) is not None and expected[name] != declared[name] for name in _SUBJECT_KEYS):
                            safe["reason_codes"].append("stored_annotation_subject_mismatch")
                        raw_value = _raw(record).get(safe["field"])
                        if raw_value is not None and raw_value != safe["value"]:
                            safe["reason_codes"].append("stored_annotation_value_mismatch")
                        # A stored proposal stays bound only to its declared
                        # subject, never silently rebound to this record.
                    else:
                        safe["subject"] = {"identity_status": "unassigned"}
                    if target is not None:
                        target.append(safe)
                    else:
                        safe["reason_codes"].append("unassigned_document_mention")
                        safe["proposal_id"] = "structure-proposal:" + _digest([scope_id, _proposal_id(safe)])
                        mentions[safe["proposal_id"]] = safe
            if annotation.get("assessment_complete") is not True:
                complete = False
        elif annotation is not None:
            warnings.add("stored_structure_annotation_invalid_or_unknown_version")
            complete = False
        for candidate in candidates:
            paper_id = candidate["source"]["paper_id"]
            if source_statuses is None:
                candidate["reason_codes"].append("current_source_status_not_checked")
            elif not isinstance(source_statuses, Mapping) or source_statuses.get(paper_id) not in ("active", "active_research", "published", "preprint", "indexed", "processed"):
                candidate["reason_codes"].append("current_source_status_unresolved_or_held")
                warnings.add("current_source_status_unresolved_or_held")
            if any(record.get(key) is True for key in ("needs_review", "retracted", "corrected", "disputed")):
                candidate["reason_codes"].append("record_governance_hold")
            candidate["reason_codes"] = sorted(set(candidate["reason_codes"]))
            candidate["proposal_id"] = "structure-proposal:" + _digest([scope_id, _proposal_id(candidate)])
            identity = candidate["proposal_id"]
            if identity in proposals:
                proposals[identity]["occurrence_count"] += 1
                proposals[identity]["reason_codes"] = sorted(set(proposals[identity]["reason_codes"]) | set(candidate["reason_codes"]))
            else:
                candidate["occurrence_count"] = 1
                proposals[identity] = candidate
    ordered = [proposals[key] for key in sorted(proposals)]
    ordered_mentions = [mentions[key] for key in sorted(mentions)]
    if not complete:
        warnings.add("structure_assessment_incomplete")
    display_truncated = len(ordered) > MAX_PROPOSALS or len(ordered_mentions) > MAX_MENTIONS
    if display_truncated:
        warnings.add("structure_evidence_display_truncated")
    # Lifecycle eligibility is not a source-text redistribution permission.
    # No public opt-in exists until a separately reviewed permission contract.
    for proposal in ordered + ordered_mentions:
        evidence = proposal["evidence"]
        quote = evidence.get("text")
        evidence["text_sha256"] = hashlib.sha256(quote.encode()).hexdigest() if isinstance(quote, str) else None
        evidence["text_char_count"] = len(quote) if isinstance(quote, str) else None
        evidence["text"] = None
        evidence["excerpt_status"] = "withheld_pending_source_permission" if quote else "unavailable"
    warnings.add("source_excerpt_permission_not_established")
    properties = {field: {"status": "pending" if any(p["field"] == field for p in ordered) else "unknown", "value": None,
                           "proposal_count": sum(p["field"] == field for p in ordered)} for field in STRUCTURE_EVIDENCE_FIELDS}
    return {"version": STRUCTURE_EVIDENCE_VERSION, "scientific_acceptance": False, "coordinate_status": "not_validated",
            "properties": properties, "proposals": ordered[:MAX_PROPOSALS], "unassigned_mentions": ordered_mentions[:MAX_MENTIONS],
            "coverage": {"record_count": len(rows), "proposal_count": len(ordered), "unassigned_mention_count": len(ordered_mentions),
                         "assessment_complete": bool(complete), "display_truncated": display_truncated}, "warnings": sorted(warnings)}
