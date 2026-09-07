"""SC07 read-only material visibility; catalogue eligibility is not approval.

Only governing flags, a freshly computed anomaly assessment, and caller-resolved
source/parent states are inputs. Stored visibility and private reviewer decisions
are deliberately ignored. This module does not read a database or change science.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from services.anomaly_review import ANOMALY_POLICY_VERSION

MATERIAL_VISIBILITY_VERSION = "material-visibility/1.0.0"
_SOURCE_LIMIT = 20_000
_ACTIVE_MATERIAL_STATUSES = {"active", "active_research"}
_PRIVATE_REVIEW_KEYS = frozenset({
    "admindecision", "reviewreason", "reviewnote", "reviewnotes", "reviewmetadata",
    "reviewermetadata", "privatereview", "internalreview", "reviewedby", "approvedby",
    "email", "name",
})
_REASONS = {
    "provenance_quarantined": "This material is unavailable under the provenance policy.",
    "parent_provenance_quarantined": "The parent material is unavailable under the provenance policy.",
    "material_retracted": "This material is marked as retracted.",
    "material_disputed": "This material is marked as disputed and requires review.",
    "material_corrected": "A correction is recorded; the resulting scientific claims require review.",
    "material_review_required": "This material is awaiting review.",
    "scientific_anomaly_review_required": "Retained scientific values require anomaly review.",
    "source_retracted": "At least one linked source is retracted or withdrawn; source-dependent claims require review.",
    "source_corrected": "At least one linked source is corrected; source-dependent claims require review.",
    "source_disputed": "At least one linked source is marked as disputed and requires review.",
    "review_status_unknown": "The material has an unrecognized review status.",
    "review_metadata_invalid": "Review metadata is invalid or incomplete and requires review.",
    "anomaly_assessment_unavailable": "A current anomaly assessment is unavailable.",
    "anomaly_assessment_invalid": "The anomaly assessment is invalid or uses an unsupported policy version.",
    "source_metadata_invalid": "Source-status metadata could not be evaluated safely.",
    "parent_review_hold": "The parent material is not eligible for the public catalogue.",
    "parent_visibility_unavailable": "The parent material's current visibility could not be established.",
    "ancestry_provenance_unresolved": "Ancestral provenance restrictions could not be resolved; public Archive access is unavailable.",
    "ancestry_missing_parent": "An ancestor material could not be resolved.",
    "ancestry_cycle_detected": "The material ancestry contains a cycle and requires repair.",
    "ancestry_depth_exceeded": "The material ancestry exceeds the bounded review depth.",
    "record_provenance_quarantined": "A retained record is unavailable under the provenance policy.",
    "record_review_required": "At least one retained record explicitly requires review.",
    "record_disputed": "A retained record is marked as disputed; source-dependent claims require review.",
    "record_retracted": "A retained record is marked as retracted or withdrawn; source-dependent claims require review.",
    "record_corrected": "A retained record is marked as corrected; source-dependent claims require review.",
    "record_review_metadata_invalid": "A retained record has malformed review metadata and requires review.",
    "record_governance_unresolved": "The retained-record governance input exceeds the bounded policy; public Archive access is unavailable.",
}
_WARNINGS = {
    "catalogue_is_not_scientific_acceptance": "Catalogue eligibility does not establish scientific acceptance or ML-training eligibility.",
    "source_status_unknown": "Current source status is unknown; active publication status has not been established.",
    "source_status_incomplete": "Current status is unknown for one or more linked sources.",
    "legacy_status_unspecified": "The legacy material status is unspecified; no approval is inferred.",
    "archive_only": "Archive material is retained for traceability and is excluded from the default public catalogue.",
    "parent_review_hold": "This material inherits a visibility hold from its parent.",
    "archive_access_unresolved": "Public Archive access is unavailable until provenance restrictions can be resolved.",
}


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _token(value: Any) -> str | None:
    return value.strip().lower() if isinstance(value, str) and len(value) <= 200 else None


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalize_source_status(value: Any) -> str:
    """Normalize authoritative source lifecycle status, never raw record flags.

    A withdrawn source is held like a retracted source for read eligibility; this
    does not assert that withdrawal and retraction are bibliographically equal.
    """
    token = _token(value)
    if token in {"active", "published"}:
        return "active"
    if token in {"retracted", "withdrawn"}:
        return "retracted"
    return "corrected" if token == "corrected" else "unknown"


def _source_state(source_statuses: Any) -> tuple[str, set[str], list[Any], bool]:
    if source_statuses is None:
        return "unknown", {"unknown"}, [], False
    if isinstance(source_statuses, Mapping):
        if len(source_statuses) > _SOURCE_LIMIT:
            return "unknown", {"unknown"}, [], True
        values = list(source_statuses.values())
        # Identifiers affect the fingerprint, never the public reason strings.
        identities = [
            (_digest(key) if isinstance(key, str) and len(key) <= 500 else "invalid-id",
             normalize_source_status(value), _token(value) == "disputed")
            for key, value in source_statuses.items()
        ]
        malformed = any(not isinstance(key, str) or not key or len(key) > 500 for key in source_statuses)
    elif isinstance(source_statuses, Sequence) and not isinstance(source_statuses, (str, bytes)):
        if len(source_statuses) > _SOURCE_LIMIT:
            return "unknown", {"unknown"}, [], True
        values = list(source_statuses)
        identities = [(normalize_source_status(value), _token(value) == "disputed") for value in values]
        malformed = False
    else:
        return "unknown", {"unknown"}, [], True
    malformed |= any(value is not None and not isinstance(value, str) for value in values)
    normalized = {normalize_source_status(value) for value in values} or {"unknown"}
    # "disputed" has no independent lifecycle enum, but still imposes a hold.
    states = normalized | ({"disputed"} if any(_token(value) == "disputed" for value in values) else set())
    aggregate = next(iter(normalized)) if len(normalized) == 1 else "mixed"
    return aggregate, states, sorted(identities), malformed


def _anomaly_state(value: Any) -> tuple[str, dict[str, Any]]:
    if value is None:
        return "unavailable", {}
    if not isinstance(value, Mapping) or value.get("version") != ANOMALY_POLICY_VERSION or not isinstance(value.get("needs_review"), bool):
        return "invalid", {}
    counts = value.get("counts", {})
    if not isinstance(counts, Mapping):
        return "invalid", {}
    public_counts = {}
    for key in ("no_findings", "review_required", "format_invalid", "total_records"):
        count = counts.get(key, 0)
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 10**9:
            return "invalid", {}
        public_counts[key] = count
    flagged = public_counts["review_required"] + public_counts["format_invalid"]
    if flagged and not value["needs_review"]:
        return "invalid", {}
    rules = value.get("rule_counts", {})
    if not isinstance(rules, Mapping) or len(rules) > 200:
        return "invalid", {}
    rule_snapshot = {}
    for rule, count in rules.items():
        if not isinstance(rule, str) or len(rule) > 100 or isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 10**9:
            return "invalid", {}
        # Hash rule names so even malformed/private caller metadata is not copied.
        rule_snapshot[_digest(rule)] = count
    year = value.get("evaluation_year")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999):
        return "invalid", {}
    return ("pending" if value["needs_review"] else "clear"), {
        "version": ANOMALY_POLICY_VERSION, "evaluation_year": year,
        "needs_review": value["needs_review"], "counts": public_counts,
        "rule_counts": rule_snapshot,
    }


def _record_governance(records: Any) -> set[str]:
    """Raw negative governance adds holds; raw positive approval never grants one.

    These are conservative material-wide review holds, not an assertion that an
    entire material is scientifically retracted, disputed, or corrected. SC08
    must resolve which claims actually depend on each flagged record.
    """
    if not isinstance(records, (list, tuple)):
        return set()
    if len(records) > _SOURCE_LIMIT:
        return {"record_governance_unresolved"}
    reasons = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        statuses = {_token(record.get(key)) for key in ("status", "review_status", "source_status", "validity_status")}
        provenance = _token(record.get("provenance_status"))
        reason = record.get("review_reason")
        if ((isinstance(reason, str) and reason.lstrip()[:200].lower().startswith("provenance_quarantine"))
                or provenance in {"quarantined", "quarantine"}
                or statuses & {"quarantined", "provenance_quarantined"}):
            reasons.add("record_provenance_quarantined")
        if record.get("retracted") is True or statuses & {"retracted", "withdrawn"}:
            reasons.add("record_retracted")
        if record.get("disputed") is True or statuses & {"disputed", "refuted"}:
            reasons.add("record_disputed")
        if record.get("corrected") is True or "corrected" in statuses:
            reasons.add("record_corrected")
        if record.get("needs_review") is True or statuses & {"pending", "needs_review", "under_review", "unreviewed", "excluded", "rejected"}:
            reasons.add("record_review_required")
        if any(record.get(key) is not None and not isinstance(record[key], bool)
               for key in ("needs_review", "disputed", "retracted", "corrected")):
            reasons.add("record_review_metadata_invalid")
    return reasons


def visibility_for_material(
    material: Any,
    *,
    anomaly_review: Mapping[str, Any] | None = None,
    source_statuses: Mapping[str, str | None] | Sequence[str | None] | None = None,
    parent_visibility: Mapping[str, Any] | None = None,
    ancestry_error: str | None = None,
) -> dict[str, Any]:
    """Build an English, private-note-free DTO for one current material revision.

    ``anomaly_review`` must be freshly computed by the resolver, not copied from
    an incoming/stored envelope. ``source_statuses`` must represent all relevant
    current source lookups (use None for missing lookups), not NER-inferred status.
    A parent DTO, when required, must be resolved independently by the caller.
    ``ancestry_error`` is an internal resolver signal, never a stored raw flag.
    """
    reasons: set[str] = set()
    warnings = {"catalogue_is_not_scientific_acceptance"}
    status_raw = _get(material, "status")
    status = _token(status_raw)
    raw_reason = _get(material, "review_reason")
    # Prefix quarantine remains effective even if malformed upstream notes are
    # over the database's nominal length limit. The rest is never copied.
    review_reason = raw_reason.lstrip()[:200].lower() if isinstance(raw_reason, str) else None
    needs_review = _get(material, "needs_review")
    disputed = _get(material, "disputed")
    retracted = _get(material, "retracted")

    quarantine = bool(review_reason and review_reason.startswith("provenance_quarantine")) or status in {"quarantined", "provenance_quarantined"}
    if quarantine:
        reasons.add("provenance_quarantined")
    record_reasons = _record_governance(_get(material, "records"))
    reasons.update(record_reasons)
    if "record_provenance_quarantined" in reasons:
        quarantine = True
    if retracted is True or status in {"retracted", "withdrawn"}:
        reasons.add("material_retracted")
    if disputed is True or status in {"disputed", "refuted"}:
        reasons.add("material_disputed")
    if status == "corrected":
        reasons.add("material_corrected")
    if needs_review is True or status in {"pending", "needs_review", "under_review"}:
        reasons.add("material_review_required")
    if any(value is not None and not isinstance(value, bool) for value in (needs_review, disputed, retracted)):
        reasons.add("review_metadata_invalid")
    known_statuses = _ACTIVE_MATERIAL_STATUSES | {"retracted", "withdrawn", "disputed", "refuted", "corrected", "pending", "needs_review", "under_review", "quarantined", "provenance_quarantined"}
    if status_raw is None or status_raw == "":
        warnings.add("legacy_status_unspecified")
    elif status not in known_statuses:
        reasons.add("review_status_unknown")

    anomaly_state, anomaly_snapshot = _anomaly_state(anomaly_review)
    if anomaly_state == "pending":
        reasons.add("scientific_anomaly_review_required")
    elif anomaly_state != "clear":
        reasons.add("anomaly_assessment_" + anomaly_state)

    source_status, source_states, source_snapshot, source_invalid = _source_state(source_statuses)
    if source_invalid:
        reasons.add("source_metadata_invalid")
    if "retracted" in source_states:
        reasons.add("source_retracted")
    if "corrected" in source_states:
        reasons.add("source_corrected")
    if "disputed" in source_states:
        reasons.add("source_disputed")
    if "unknown" in source_states:
        warnings.add("source_status_unknown" if source_status == "unknown" else "source_status_incomplete")

    parent_snapshot: dict[str, Any] | None = None
    parent_required = bool(_get(material, "parent_material_id"))
    ancestry_unresolved = ancestry_error is not None
    if ancestry_unresolved:
        reasons.add("ancestry_provenance_unresolved")
        ancestry_code = {"missing_parent": "ancestry_missing_parent", "cyclic_parent": "ancestry_cycle_detected",
                         "depth_exceeded": "ancestry_depth_exceeded"}.get(ancestry_error if isinstance(ancestry_error, str) else "unknown")
        if ancestry_code:
            reasons.add(ancestry_code)
    if parent_visibility is not None:
        valid_parent = (
            isinstance(parent_visibility, Mapping)
            and parent_visibility.get("version") == MATERIAL_VISIBILITY_VERSION
            and isinstance(parent_visibility.get("public_catalogue_eligible"), bool)
            and isinstance(parent_visibility.get("archive_available"), bool)
            and parent_visibility.get("state") in {"catalogue", "pending", "disputed", "corrected", "retracted", "quarantined", "unknown"}
            and parent_visibility["public_catalogue_eligible"] == (parent_visibility["state"] == "catalogue")
            and (parent_visibility["archive_available"] == (parent_visibility["state"] != "quarantined")
                 or parent_visibility["archive_available"] is False and isinstance(parent_visibility.get("reason_codes"), list)
                 and any(code in {"ancestry_provenance_unresolved", "record_governance_unresolved"}
                         for code in parent_visibility["reason_codes"] if isinstance(code, str)))
            and isinstance(parent_visibility.get("review_revision"), str)
            and len(parent_visibility["review_revision"]) <= 100
        )
        if not valid_parent:
            reasons.add("parent_visibility_unavailable")
            ancestry_unresolved = True
        else:
            parent_snapshot = {key: parent_visibility[key] for key in (
                "version", "state", "public_catalogue_eligible", "archive_available", "review_revision",
            )}
            if parent_visibility["state"] == "quarantined":
                quarantine = True
                reasons.add("parent_provenance_quarantined")
            elif not parent_visibility["archive_available"]:
                ancestry_unresolved = True
            elif not parent_visibility["public_catalogue_eligible"]:
                reasons.add("parent_review_hold")
                warnings.add("parent_review_hold")
    elif parent_required and not ancestry_unresolved:
        reasons.add("parent_visibility_unavailable")
        ancestry_unresolved = True

    if ancestry_unresolved:
        reasons.add("ancestry_provenance_unresolved")

    if quarantine:
        state = "quarantined"
    elif "material_retracted" in reasons or source_states == {"retracted"}:
        state = "retracted"
    elif {"material_disputed", "source_disputed"} & reasons:
        state = "disputed"
    elif {"material_corrected", "source_corrected"} & reasons:
        state = "corrected"
    elif ({"material_review_required", "scientific_anomaly_review_required", "source_retracted", "parent_review_hold"} & reasons
          or record_reasons - {"record_governance_unresolved", "record_provenance_quarantined"}):
        state = "pending"
    elif reasons:
        state = "unknown"
    else:
        state = "catalogue"
    eligible = state == "catalogue"
    archive_available = state != "quarantined" and not ancestry_unresolved and "record_governance_unresolved" not in reasons
    if archive_available and not eligible:
        warnings.add("archive_only")
    elif not archive_available and state != "quarantined":
        warnings.add("archive_access_unresolved")
    reasons_list, warnings_list = sorted(reasons), sorted(warnings)
    snapshot = {
        "version": MATERIAL_VISIBILITY_VERSION, "state": state,
        "material_identity": _digest(str(_get(material, "id", "unknown-material"))[:500]),
        "material_updated_at": (
            _get(material, "updated_at").isoformat()
            if isinstance(_get(material, "updated_at"), (date, datetime))
            else _get(material, "updated_at")[:100]
            if isinstance(_get(material, "updated_at"), str) else None
        ),
        "governance": {"status": status if status in known_statuses else "unspecified" if status_raw is None or status_raw == "" else "unknown",
                       "needs_review": needs_review if isinstance(needs_review, bool) else None,
                       "disputed": disputed if isinstance(disputed, bool) else None,
                       "retracted": retracted if isinstance(retracted, bool) else None},
        "reason_codes": reasons_list, "warning_codes": warnings_list,
        "anomaly": anomaly_snapshot, "sources": source_snapshot,
        "parent": parent_snapshot,
    }
    return {
        "version": MATERIAL_VISIBILITY_VERSION, "state": state,
        "public_catalogue_eligible": eligible, "archive_available": archive_available,
        "scientific_acceptance": False, "reason_codes": reasons_list,
        "warning_codes": warnings_list,
        "reason_messages": [_REASONS[code] for code in reasons_list],
        "warning_messages": [_WARNINGS[code] for code in warnings_list],
        "review_revision": _digest(snapshot), "source_status": source_status,
    }


def visibility_allows_view(visibility: Mapping[str, Any], *, include_archive: bool = False) -> bool:
    """Archive opt-in never bypasses a provenance quarantine or old policy DTO."""
    if visibility.get("version") != MATERIAL_VISIBILITY_VERSION:
        return False
    if visibility.get("state") not in {"catalogue", "pending", "disputed", "corrected", "retracted", "unknown"} or visibility.get("archive_available") is not True:
        return False
    return include_archive is True or (visibility.get("state") == "catalogue" and visibility.get("public_catalogue_eligible") is True)


def safe_public_review_reason(visibility: Mapping[str, Any]) -> str | None:
    """Compatibility prose reconstructed from known codes, never arbitrary text."""
    codes = visibility.get("reason_codes", [])
    if not isinstance(codes, list):
        return None
    messages = [_REASONS[code] for code in sorted({code for code in codes if isinstance(code, str) and code in _REASONS})]
    return " ".join(messages)[:1000] or None


def sanitize_review_metadata(value: Any) -> Any:
    """Copy public scientific payloads while removing known private review keys.

    This is not a general PII/text/license sanitizer. Original free text may still
    contain private information and needs its own source disclosure policy. Keys
    used for reviewer/profile identity (including bare name/email) are removed.
    Result identity must be derived from raw records *before* this projection.
    """
    budget = 20_000
    active_containers: set[int] = set()

    def private_key(key: str) -> bool:
        normalized = "".join(char for char in key.lower() if char.isalnum())
        return normalized in _PRIVATE_REVIEW_KEYS or normalized.startswith((
            "reviewer", "curator", "privatereview", "internalreview",
        ))

    def visit(item: Any, depth: int) -> Any:
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 12:
            return {"redacted": "review_metadata_projection_limit"}
        if item is None or isinstance(item, (bool, int, float, str)):
            return item
        if not isinstance(item, (Mapping, list, tuple)):
            return {"redacted": "unsupported_metadata_type"}
        identity = id(item)
        if identity in active_containers:
            return {"redacted": "cyclic_metadata"}
        active_containers.add(identity)
        try:
            if isinstance(item, Mapping):
                output = {}
                for key, child in item.items():
                    if budget <= 0:
                        output["_projection_warning"] = "review_metadata_projection_limit"
                        break
                    if not isinstance(key, str) or private_key(key):
                        budget -= 1
                        continue
                    output[key] = visit(child, depth + 1)
                return output
            output = []
            for child in item:
                if budget <= 0:
                    output.append({"redacted": "review_metadata_projection_limit"})
                    break
                output.append(visit(child, depth + 1))
            return output
        finally:
            active_containers.remove(identity)

    return visit(value, 0)
