"""Source-limited catalogue reads; not approval or source reinstatement.

The frozen v1 policy remains the fallback. Only a complete private partition can
expose v2 reported records from explicitly active sources while preserving every
material/ancestral hold and the raw Archive. Callers must use the same partition
for properties, predicates and occurrences; a v2 visibility alone is not evidence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from services.material_anomalies import material_review, record_assessment, review_context
from services.material_visibility import (
    _REASONS,
    _WARNINGS,
    MATERIAL_VISIBILITY_VERSION,
    _get,
    _record_governance,
    normalize_source_status,
    visibility_allows_view,
    visibility_for_material,
)
from services.source_lifecycle_status import (
    lifecycle_review_required,
    lifecycle_revision,
    lifecycle_status,
)

VISIBILITY_VERSION = "material-visibility/2.0.0"
SOURCE_SCOPE_VERSION = "material-source-scope/1.0.0"
MAX_RECORDS = 5000
MAX_BYTES = 4 * 1024 * 1024
MAX_NODES = 100_000
MAX_DEPTH = 32
_SEAL_KEY = secrets.token_bytes(32)  # In-process integrity only, not durable authority.
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_VISIBILITY_KEYS = frozenset({
    "version", "state", "public_catalogue_eligible", "archive_available", "scientific_acceptance",
    "reason_codes", "warning_codes", "reason_messages", "warning_messages", "review_revision", "source_status",
})
_SCOPE_KEYS = frozenset({
    "version", "status", "total_records", "eligible_records", "excluded_records",
    "eligible_source_count", "fingerprint", "independent_support_count",
})
_SCOPED_WARNINGS = {
    "source_scoped_reported_records_only": "Only eligible reported records from explicitly active sources are displayed; this is not scientific acceptance.",
    "excluded_records_retained_in_archive": "Other retained records do not contribute to the current selection and remain subject to Archive access rules.",
}
_SOURCE_HOLDS = frozenset({"source_retracted", "source_corrected", "source_disputed", "source_lifecycle_review_required"})
_MATERIAL_FIELDS = ("id", "status", "needs_review", "retracted", "disputed", "review_reason",
                    "parent_material_id", "updated_at", "family", "anomaly_context")


class SourceScopeError(ValueError):
    """Static partition-integrity failure, never source text or private notes."""


def _canonical(value: Any) -> bytes:
    pending, count, text_bytes = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count + len(pending) > MAX_NODES or depth > MAX_DEPTH:
            raise SourceScopeError("source_scope_input_limit")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise SourceScopeError("source_scope_input_invalid")
            if count + len(pending) + 2 * len(item) > MAX_NODES:
                raise SourceScopeError("source_scope_input_limit")
            pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) is list:
            if count + len(pending) + len(item) > MAX_NODES:
                raise SourceScopeError("source_scope_input_limit")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            try:
                text_bytes += len(item.encode("utf-8"))
            except UnicodeError:
                raise SourceScopeError("source_scope_input_invalid") from None
            if text_bytes > MAX_BYTES:
                raise SourceScopeError("source_scope_input_limit")
        elif item is not None and (type(item) not in {bool, int, float}
                                  or type(item) is float and not math.isfinite(item)):
            raise SourceScopeError("source_scope_input_invalid")
    try:
        result = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise SourceScopeError("source_scope_input_invalid") from None
    if len(result) > MAX_BYTES:
        raise SourceScopeError("source_scope_input_limit")
    return result


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identifier(value: Any) -> bool:
    return type(value) is str and 0 < len(value) <= 100 and value == value.strip() and not any(ord(char) < 32 for char in value)


def _hash(value: Any) -> bool:
    return type(value) is str and _HASH.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class SourceScope:
    """Private, position-preserving partition. This object grants no authority."""

    version: str
    material_id: str
    indices: tuple[int, ...]
    eligible_indices: tuple[int, ...]
    paper_ids: tuple[str | None, ...]
    reason_codes: tuple[tuple[str, ...], ...]
    record_sha256: tuple[str, ...]
    fingerprint: str
    _seal: str = field(default="", repr=False, compare=False)
    _validated_state: tuple | None = field(default=None, init=False, repr=False, compare=False)
    _eligible_papers: tuple[str, ...] = field(default=(), init=False, repr=False, compare=False)

    def _signature(self) -> str:
        return hmac.new(_SEAL_KEY, _canonical({
            "version": self.version, "material_id": self.material_id,
            "indices": list(self.indices), "eligible_indices": list(self.eligible_indices),
            "paper_ids": list(self.paper_ids), "reason_codes": [list(row) for row in self.reason_codes],
            "record_sha256": list(self.record_sha256), "fingerprint": self.fingerprint,
        }), hashlib.sha256).hexdigest()

    def validate(self, records: Any = None) -> SourceScope:
        """Reject field replacement and, when supplied, changed raw inventories."""
        fields = (self.indices, self.eligible_indices, self.paper_ids, self.reason_codes, self.record_sha256)
        state = (self.version, self.material_id, *fields, self.fingerprint, self._seal)
        changed = (self._validated_state is None
                   or any(left is not right for left, right in zip(state, self._validated_state, strict=True)))
        # All validated fields are immutable tuples/scalars. A replacement has
        # no cache; even an in-process field replacement changes its identity.
        if changed and (self.version != SOURCE_SCOPE_VERSION or not _identifier(self.material_id)
                or any(type(value) is not tuple for value in fields)
                or not 2 <= len(self.indices) <= MAX_RECORDS
                or any(type(index) is not int for index in self.indices + self.eligible_indices)
                or self.indices != tuple(range(len(self.indices)))
                or not 0 < len(self.eligible_indices) < len(self.indices)
                or self.eligible_indices != tuple(sorted(set(self.eligible_indices)))
                or any(not 0 <= index < len(self.indices) for index in self.eligible_indices)
                or any(len(value) != len(self.indices) for value in (self.paper_ids, self.reason_codes, self.record_sha256))
                or any(paper is not None and not _identifier(paper) for paper in self.paper_ids)
                or any(type(row) is not tuple or any(type(code) is not str for code in row)
                       or row != tuple(sorted(set(row))) for row in self.reason_codes)
                or self.eligible_indices != tuple(index for index, reasons in enumerate(self.reason_codes) if not reasons)
                or any(self.paper_ids[index] is None for index in self.eligible_indices)
                or any(not _hash(value) for value in self.record_sha256)
                or not _hash(self.fingerprint) or not _hash(self._seal)
                or not hmac.compare_digest(self._seal, self._signature())):
            raise SourceScopeError("source_scope_integrity_invalid")
        if changed:
            object.__setattr__(self, "_eligible_papers", tuple(sorted({self.paper_ids[index] for index in self.eligible_indices})))
            object.__setattr__(self, "_validated_state", state)
        if records is not None:
            if type(records) is not list or len(records) != len(self.indices):
                raise SourceScopeError("source_scope_record_inventory_changed")
            _canonical(records)
            papers = tuple(record.get("paper_id") if type(record) is dict and _identifier(record.get("paper_id"))
                           else None for record in records)
            if papers != self.paper_ids or tuple(_digest(record) for record in records) != self.record_sha256:
                raise SourceScopeError("source_scope_record_inventory_changed")
        return self

    @property
    def eligible_paper_ids(self) -> tuple[str, ...]:
        self.validate()
        return self._eligible_papers

    def eligible_records(self, records: Any) -> list[dict[str, Any]]:
        if type(records) is not list:
            raise SourceScopeError("source_scope_record_inventory_changed")
        self.validate(records)
        return [deepcopy(records[index]) for index in self.eligible_indices]

    def reason_for(self, index: int) -> tuple[str, ...]:
        self.validate()
        if type(index) is not int or not 0 <= index < len(self.indices):
            raise SourceScopeError("source_scope_index_invalid")
        return self.reason_codes[index]

    def paper_for(self, index: int) -> str | None:
        self.validate()
        if type(index) is not int or not 0 <= index < len(self.indices):
            raise SourceScopeError("source_scope_index_invalid")
        return self.paper_ids[index]


def _valid_visibility_shape(value: Any) -> bool:
    if type(value) is not dict or value.get("version") not in {MATERIAL_VISIBILITY_VERSION, VISIBILITY_VERSION}:
        return False
    scoped = value["version"] == VISIBILITY_VERSION
    if set(value) != _VISIBILITY_KEYS | ({"source_scope"} if scoped else set()):
        return False
    if (value["scientific_acceptance"] is not False or type(value["public_catalogue_eligible"]) is not bool
            or type(value["archive_available"]) is not bool or not _hash(value["review_revision"])
            or value["state"] not in {"catalogue", "pending", "disputed", "corrected", "retracted", "quarantined", "unknown"}
            or value["source_status"] not in {"active", "mixed", "unknown", "retracted", "corrected"}):
        return False
    for key in ("reason_codes", "warning_codes", "reason_messages", "warning_messages"):
        if type(value[key]) is not list or len(value[key]) > 100 or any(type(item) is not str for item in value[key]):
            return False
    reasons, warnings = value["reason_codes"], value["warning_codes"]
    known_warnings = {**_WARNINGS, **(_SCOPED_WARNINGS if scoped else {})}
    if (reasons != sorted(set(reasons)) or warnings != sorted(set(warnings))
            or any(code not in _REASONS for code in reasons) or any(code not in known_warnings for code in warnings)
            or value["reason_messages"] != [_REASONS[code] for code in reasons]
            or value["warning_messages"] != [known_warnings[code] for code in warnings]
            or value["public_catalogue_eligible"] != (value["state"] == "catalogue")
            or value["state"] == "catalogue" and (reasons or not value["archive_available"])):
        return False
    if not scoped:
        return True
    scope = value["source_scope"]
    if (type(scope) is not dict or set(scope) != _SCOPE_KEYS or scope["version"] != SOURCE_SCOPE_VERSION
            or scope["status"] != "eligible_records_only" or scope["independent_support_count"] is not None
            or not _hash(scope["fingerprint"]) or value["state"] != "catalogue"
            or not (set(_SCOPED_WARNINGS) | {"catalogue_is_not_scientific_acceptance"}) <= set(warnings)):
        return False
    for key in ("total_records", "eligible_records", "excluded_records", "eligible_source_count"):
        if type(scope[key]) is not int or not 1 <= scope[key] <= MAX_RECORDS:
            return False
    return (scope["eligible_records"] + scope["excluded_records"] == scope["total_records"]
            and scope["eligible_source_count"] <= scope["eligible_records"])


def _valid_visibility(value: Any) -> bool:
    try:
        return _valid_visibility_shape(value)
    except (TypeError, ValueError, KeyError):
        return False


def validate_scoped_visibility(value: Any) -> dict:
    """Validate only the closed public v2 shape; this does not validate a scope."""
    if not _valid_visibility(value) or value["version"] != VISIBILITY_VERSION:
        raise SourceScopeError("source_scope_visibility_invalid")
    return deepcopy(value)


def current_visibility_allows_view(value: Any, *, include_archive: bool = False) -> bool:
    """Preserve the original v1 predicate; require a closed envelope for v2."""
    if not isinstance(value, Mapping):
        return False
    if value.get("version") == VISIBILITY_VERSION:
        return type(include_archive) is bool and _valid_visibility(value)
    try:
        return visibility_allows_view(value, include_archive=include_archive)
    except (TypeError, ValueError):
        return False


def legacy_parent_visibility(value: Any) -> Any:
    """Bridge an actual validated v2 parent into the unchanged v1 parent gate."""
    if type(value) is not dict or value.get("version") != VISIBILITY_VERSION:
        return value
    if not _valid_visibility(value):
        return {}  # Preserve an explicit malformed parent as a v1 hold.
    # v1 sees only the accepted parent gate. Preserve the actual parent's hash;
    # changing the version is not recapture, approval or a new parent identity.
    return {key: (MATERIAL_VISIBILITY_VERSION if key == "version" else deepcopy(item))
            for key, item in value.items() if key != "source_scope"}


def _negative_source(value: Any) -> bool:
    status = lifecycle_status(value)
    token = status.strip().lower() if type(status) is str else None
    return token in {"retracted", "withdrawn", "corrected", "disputed"} or lifecycle_revision(value) is not None


def _partition_reason(record: Any, source_statuses: Mapping, *, identity: str, context: dict) -> tuple[str | None, tuple[str, ...]]:
    if type(record) is not dict:
        return None, ("record_format_invalid",)
    paper_id = record.get("paper_id")
    if not _identifier(paper_id):
        return None, ("record_source_unresolved",)
    reasons = set(_record_governance([record]))
    if any(record.get(key) is not None and type(record[key]) is not str for key in
           ("review_status", "validity_status", "provenance_status", "review_reason", "source_status", "status")):
        reasons.add("record_review_metadata_invalid")
    status = source_statuses.get(paper_id)
    if lifecycle_review_required(status):
        reasons.add("source_lifecycle_review_required" if lifecycle_revision(status) is not None else "source_metadata_invalid")
    if normalize_source_status(status) != "active":
        token = lifecycle_status(status)
        token = token.strip().lower() if type(token) is str else None
        reasons.add({"withdrawn": "source_retracted", "retracted": "source_retracted", "corrected": "source_corrected",
                     "disputed": "source_disputed"}.get(token, "source_status_unknown"))
    assessment = record_assessment(record, scope_id=identity, context=context)
    if assessment["status"] != "no_findings":
        reasons.add("record_anomaly_review_required")
    return paper_id, tuple(sorted(reasons))


def scoped_material_visibility(material: Any, *, source_statuses: Any,
                               parent_visibility: Any = None, ancestry_error: str | None = None,
                               fallback_source_statuses: Any = None) -> tuple[dict, SourceScope | None]:
    """Upgrade only an exact, complete separable source hold; otherwise use v1."""
    records, identity = _get(material, "records"), _get(material, "id")
    # The adapter keeps malformed legacy source identities out of SQL. Their
    # original v1 invalid-metadata hold must nevertheless survive the fallback;
    # the exact valid-ID map alone is used to construct a private v2 partition.
    legacy_sources = source_statuses if fallback_source_statuses is None else fallback_source_statuses
    parent = legacy_parent_visibility(parent_visibility)
    context = review_context(material)
    try:
        if type(records) is list and len(records) > MAX_RECORDS:
            raise SourceScopeError("source_scope_input_limit")
        _canonical(records)
        anomaly = material_review(records, scope_id=identity if _identifier(identity) else "unknown-material", context=context, compact=True)
    except (SourceScopeError, ValueError, TypeError, RecursionError, OverflowError):
        # No partial assessment may turn an over-budget input into a grant:
        # v1 treats a missing current assessment as an explicit non-catalogue hold.
        return visibility_for_material(material, anomaly_review=None, source_statuses=legacy_sources,
            parent_visibility=parent, ancestry_error=ancestry_error), None
    original = visibility_for_material(material, anomaly_review=anomaly, source_statuses=legacy_sources,
        parent_visibility=parent, ancestry_error=ancestry_error)
    if (type(records) is not list or not _identifier(identity) or type(source_statuses) is not dict or len(source_statuses) > MAX_RECORDS
            or any(not _identifier(key) for key in source_statuses)
            or not (_SOURCE_HOLDS & set(original["reason_codes"]))
            or "record_provenance_quarantined" in original["reason_codes"]):
        return original, None
    # Assess immutable/global governance separately without erasing or changing
    # any raw record. Empty-record evaluation cannot clear persisted flags.
    shell = {key: _get(material, key) for key in _MATERIAL_FIELDS}
    shell["records"] = []
    global_gate = visibility_for_material(shell, anomaly_review=material_review([], scope_id=identity, context=context, compact=True),
        source_statuses={}, parent_visibility=parent, ancestry_error=ancestry_error)
    if not current_visibility_allows_view(global_gate):
        return original, None
    try:
        _canonical(source_statuses)
        partition = tuple(_partition_reason(record, source_statuses, identity=identity, context=context) for record in records)
        papers = tuple(item[0] for item in partition)
        reasons = tuple(item[1] for item in partition)
        eligible = tuple(index for index, codes in enumerate(reasons) if not codes)
        if (not eligible or not any(paper is not None and _negative_source(source_statuses.get(paper)) for paper in papers)):
            return original, None
        selected_anomaly = material_review([records[index] for index in eligible], scope_id=identity, context=context, compact=True)
        if selected_anomaly["needs_review"] is not False:
            return original, None
        hashes = tuple(_digest(record) for record in records)
        fingerprint = _digest({"version": SOURCE_SCOPE_VERSION, "material_id": identity, "original_visibility": original["review_revision"],
            "records": list(hashes), "papers": list(papers), "reasons": [list(row) for row in reasons],
            "eligible_indices": list(eligible), "source_statuses": source_statuses, "eligible_anomaly": selected_anomaly})
        scope = SourceScope(SOURCE_SCOPE_VERSION, identity, tuple(range(len(records))), eligible, papers, reasons, hashes, fingerprint)
        object.__setattr__(scope, "_seal", scope._signature())
        scope.validate(records)
        warnings = sorted(set(global_gate["warning_codes"]) - {"source_status_unknown", "archive_only"} | set(_SCOPED_WARNINGS))
        public_scope = {"version": SOURCE_SCOPE_VERSION, "status": "eligible_records_only", "total_records": len(records),
            "eligible_records": len(eligible), "excluded_records": len(records) - len(eligible),
            "eligible_source_count": len({papers[index] for index in eligible}), "fingerprint": fingerprint,
            "independent_support_count": None}
        visibility = {**global_gate, "version": VISIBILITY_VERSION, "source_status": original["source_status"],
            "warning_codes": warnings, "warning_messages": [{**_WARNINGS, **_SCOPED_WARNINGS}[code] for code in warnings],
            "source_scope": public_scope, "review_revision": _digest({"version": VISIBILITY_VERSION, "original": original["review_revision"],
                "scope": fingerprint, "parent": parent.get("review_revision") if isinstance(parent, Mapping) else None})}
        if not current_visibility_allows_view(visibility):
            raise SourceScopeError("source_scope_output_invalid")
        return visibility, scope
    except (SourceScopeError, ValueError, TypeError, RecursionError, OverflowError):
        return original, None
