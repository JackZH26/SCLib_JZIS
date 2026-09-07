"""Result-known-by provenance, not discovery dates or scientific approval.

Byte-identical in API and ingestion. This module performs no I/O. Only an
explicit trusted resolver may supply SourceAvailabilityWitness instances;
source text, cached/public envelopes and legacy dates are not such a resolver.
The dataclass is an internal interface, not authentication of a human or source.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

TEMPORAL_PROVENANCE_VERSION = "temporal-provenance/1.0.0"
MAX_WITNESSES = 100
REPRESENTATIONS = frozenset({"arxiv_source", "pdf", "xml", "html", "source_text", "abstract"})
_TEXT_LOCATORS = {"section", "table", "figure", "equation", "xml_xpath", "section_path"}
_INT_LOCATORS = {"page", "page_start", "page_end", "row", "column", "char_start", "char_end", "span_start", "span_end"}


@dataclass(frozen=True)
class SourceAvailabilityWitness:
    claim_id: str
    paper_id: str
    work_id: str
    source_revision_id: str
    source_version: str
    capture_id: str
    source_version_public_at: datetime | None
    captured_at: datetime | None
    bytes_sha256: str
    representation: str
    locator: Mapping[str, Any]
    review_reference: str
    version_resolved: bool = False
    binding_verified: bool = False
    public_time_verified: bool = False


def utc_datetime(value: Any) -> datetime | None:
    """Require an exact timezone-aware instant; date-only is not midnight UTC."""
    if isinstance(value, str):
        if len(value) > 64:
            return None
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        return value.astimezone(UTC) if value.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _text(value: Any, maximum=200) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= maximum else None


def _date_hint(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = utc_datetime(value)
        return _iso(parsed)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        if len(value) > 64:
            return None
        instant = utc_datetime(value)
        if instant is not None:
            return _iso(instant)
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return None
    return None


def public_locator(value: Any) -> dict:
    """Coordinates only; no quotation, review notes, URI or credentials."""
    if not isinstance(value, Mapping):
        return {}
    safe = {key: value[key] for key in sorted(_TEXT_LOCATORS) if _text(value.get(key), 300)}
    safe.update({key: value[key] for key in sorted(_INT_LOCATORS)
                 if type(value.get(key)) is int and 0 <= value[key] <= 1_000_000_000})
    for lower, upper in (("page_start", "page_end"), ("char_start", "char_end"), ("span_start", "span_end")):
        if (lower in safe) != (upper in safe) or lower in safe and safe[lower] > safe[upper]:
            return {}
        if lower in {"char_start", "span_start"} and lower in safe and safe[lower] == safe[upper]:
            return {}
    return safe


def _witness(value: Any, claim_id: str) -> tuple[dict | None, str | None]:
    if not isinstance(value, SourceAvailabilityWitness):
        return None, "untrusted_witness_type"
    if value.claim_id != claim_id:
        return None, "source_witness_claim_mismatch"
    if any(_text(getattr(value, key)) is None for key in (
        "claim_id", "paper_id", "work_id", "source_revision_id", "source_version", "capture_id", "review_reference",
    )):
        return None, "source_witness_identity_incomplete"
    if not (value.version_resolved is True and value.binding_verified is True and value.public_time_verified is True):
        return None, "source_witness_not_reviewed_and_version_bound"
    if not isinstance(value.bytes_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", value.bytes_sha256):
        return None, "source_witness_bytes_hash_invalid"
    if not isinstance(value.representation, str) or value.representation not in REPRESENTATIONS:
        return None, "source_witness_representation_unqualified"
    locator = public_locator(value.locator)
    if not locator:
        return None, "source_witness_locator_unresolved"
    public_at, captured_at = utc_datetime(value.source_version_public_at), utc_datetime(value.captured_at)
    if public_at is None or captured_at is None:
        return None, "source_witness_exact_time_unresolved"
    if captured_at < public_at:
        return None, "source_witness_capture_precedes_publication_requires_review"
    return {
        "source_revision_id": value.source_revision_id, "capture_id": value.capture_id,
        "paper_id": value.paper_id, "work_id": value.work_id, "source_version": value.source_version,
        "source_version_public_at": _iso(public_at), "captured_at": _iso(captured_at),
        "bytes_sha256": value.bytes_sha256, "representation": value.representation, "locator": locator,
    }, None


def result_temporal_provenance(
    *, claim_id: str, record: Mapping | None = None, paper: Mapping | None = None,
    witnesses: Sequence[SourceAvailabilityWitness] | None = None,
) -> dict:
    """Build from server-resolved witnesses, never from dates inside extraction.

    Earliest witnessed version date is a conservative *known-by* bound, not
    proof of first appearance. Capture time is kept from the chosen witness;
    it does not delay retrospective public-knowledge availability by itself.
    """
    raw, bibliographic = record if isinstance(record, Mapping) else {}, paper if isinstance(paper, Mapping) else {}
    work_dates = [_date_hint(bibliographic.get(key)) for key in ("work_first_public_at", "date_submitted", "date_published", "available_at")]
    work_hint = next((item for item in work_dates if item is not None), None)
    result = {
        "version": TEMPORAL_PROVENANCE_VERSION, "status": "unknown", "result_available_at": None,
        "source_version_public_at": None, "captured_at": None, "availability_basis": "unknown",
        "work_first_public_at": work_hint, "work_first_public_basis": "bibliographic_hint_not_result_availability" if work_hint else "unknown",
        "legacy_result_available_at": _date_hint(raw.get("available_at")),
        "first_appearance_established": False, "scientific_acceptance": False,
        "llm_pretraining_contamination_assessed": False, "witnesses": [],
        "assessment_complete": True, "warnings": [],
    }
    warnings = {"result_time_is_not_work_first_public_time", "temporal_evidence_is_not_scientific_approval"}
    if raw.get("available_at") is not None:
        warnings.add("legacy_result_date_not_revision_verified")
    if any(key in raw for key in ("temporal_provenance", "result_available_at", "source_version_public_at")):
        warnings.add("stored_temporal_assertion_not_authoritative")
    if witnesses is None or isinstance(witnesses, (list, tuple)) and not witnesses:
        warnings.add("no_reviewed_source_version_witness")
    elif not isinstance(witnesses, (list, tuple)) or len(witnesses) > MAX_WITNESSES or _text(claim_id) is None:
        result.update(status="uncertain", assessment_complete=False, availability_basis="unresolved_source_evidence")
        warnings.add("source_witness_assessment_invalid_or_bounded")
    else:
        valid, failures, captures, occurrences = [], [], {}, {}
        for witness in witnesses:
            safe, failure = _witness(witness, claim_id)
            if failure:
                failures.append(failure)
                continue
            identity = safe["capture_id"]
            # One capture may contain several legitimate locations for the
            # same result. Only invariant capture/version attributes conflict;
            # coordinates identify occurrences, not different captured bytes.
            capture_context = {key: value for key, value in safe.items() if key != "locator"}
            if identity in captures and captures[identity] != capture_context:
                failures.append("source_capture_identity_conflict")
            captures[identity] = capture_context
            locator_key = json.dumps(safe["locator"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            occurrences[(identity, locator_key)] = safe
        valid = sorted(occurrences.values(), key=lambda item: (
            utc_datetime(item["source_version_public_at"]), utc_datetime(item["captured_at"]),
            item["capture_id"], json.dumps(item["locator"], sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        ))
        if len({item["work_id"] for item in valid}) > 1:
            failures.append("source_witness_work_identity_conflict")
        if failures:
            result.update(status="uncertain", availability_basis="unresolved_source_evidence")
            warnings.update(failures)
        elif valid:
            chosen = valid[0]
            result.update(status="known_by", result_available_at=chosen["source_version_public_at"],
                          source_version_public_at=chosen["source_version_public_at"], captured_at=chosen["captured_at"],
                          availability_basis="source_version_witness", witnesses=valid)
            warnings.add("known_by_version_date_not_first_discovery")
    result["warnings"] = sorted(warnings)
    return result
