"""Lossless private review/capsule projection, not database authentication.

0067 defines recursive SQL canonical JSON; 0054 defines Python canonical JSON.
Their hashes are distinct. Decimal comparison removes notation differences,
never measurement differences. PostgreSQL jsonb::text (notably 0056 lifecycle
snapshots) is NOT reconstructed here: retain and hash its original text.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from services.research_release_manifest import LIMITS as CAPSULE_LIMITS
from services.research_release_manifest import canonical, digest
from services.research_release_spec import FKS, SPEC

VERSION = "ml-review-projection/1.0.0"
SUBJECT_VERSION = "scientific-result-subject/1.0.0"
MAX_BYTES = 8 * 1024 * 1024
MAX_NODES = 200000
MAX_DEPTH = 48
MAX_NUMBER_CHARS = 131100
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_AUDIT_TABLES = {"scientific_result_subjects", "scientific_adjudication_requests",
    "scientific_result_decisions", "research_role_grants", "research_role_revocations",
    "source_lifecycle_events", "users", "ml_feature_source_bindings"}
_MATERIAL = ("id", "formula", "formula_normalized", "composition_status", "composition_data", "parent_material_id",
    "formula_substrate", "formula_overlayer", "layer_thickness_nm")
_PAPER = ("id", "source", "arxiv_id", "doi", "external_id", "id_scheme", "related_paper_id", "title", "authors",
    "date_submitted", "date_published")
_WORK = ("id", "canonical_title", "canonical_doi", "canonical_arxiv_id", "identity_metadata")
_EVENT_EXCLUDED = {"review_status", "validity_status", "decision_artifact_id", "record_sha256", "updated_at"}
_RECORD_EXCLUDED = {"created_at", "record_sha256", "basis_json", "request_json", "assembly_xid"}


class MLReviewProjectionError(ValueError):
    """Static private error: no raw source or identity is included."""


def _require(value, code="ml_review_projection_invalid"):
    if not value:
        raise MLReviewProjectionError(code)


def _uuid(value):
    _require(type(value) is str, "ml_review_projection_identity")
    try:
        _require(str(UUID(value)) == value, "ml_review_projection_identity")
    except (ValueError, AttributeError):
        raise MLReviewProjectionError("ml_review_projection_identity") from None
    return value


def _raw(text, max_bytes):
    _require(type(max_bytes) is int and 0 < max_bytes <= MAX_BYTES, "ml_review_projection_limit")
    _require(type(text) is str and 0 < len(text) <= max_bytes, "ml_review_projection_byte_limit")
    try:
        raw = text.encode("utf-8")
    except UnicodeError:
        raise MLReviewProjectionError("ml_review_projection_unicode") from None
    _require(len(raw) <= max_bytes, "ml_review_projection_byte_limit")
    return raw


def raw_text_sha256(text):
    """SHA of exact retained UTF-8 text, without JSON parse or reserialization."""
    return hashlib.sha256(_raw(text, MAX_BYTES)).hexdigest()


def _number_length(value):
    _require(value.is_finite(), "ml_review_projection_nonfinite")
    digits, exponent = len(value.as_tuple().digits), value.as_tuple().exponent
    size = max(digits + max(exponent, 0), 2 + max(-exponent, 0)) + 2
    _require(size <= MAX_NUMBER_CHARS, "ml_review_projection_numeric_limit")
    return size


def _tree(value):
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, "ml_review_projection_json_limit")
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "ml_review_projection_object_keys")
            _require(count + len(pending) + 2 * len(item) <= MAX_NODES, "ml_review_projection_json_limit")
            pending.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif type(item) is list:
            _require(count + len(pending) + len(item) <= MAX_NODES, "ml_review_projection_json_limit")
            pending.extend((part, depth + 1) for part in item)
        elif type(item) is str:
            try:
                _require("\x00" not in item, "ml_review_projection_unicode")
                item.encode("utf-8")
            except UnicodeError:
                raise MLReviewProjectionError("ml_review_projection_unicode") from None
        elif type(item) is Decimal:
            _number_length(item)
        elif type(item) is int:
            _require(item.bit_length() <= MAX_NUMBER_CHARS * 4, "ml_review_projection_numeric_limit")
        else:
            _require(item is None or type(item) is bool, "ml_review_projection_scalar_type")


def parse_sql_json(text, *, max_bytes=MAX_BYTES):
    """Strict bounded JSON with Decimal decimals; never an intermediate float."""
    _raw(text, max_bytes)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "ml_review_projection_duplicate_key")
            result[key] = value
        return result
    def invalid(_):
        raise MLReviewProjectionError("ml_review_projection_nonfinite")
    try:
        result = json.loads(text, object_pairs_hook=unique, parse_float=Decimal, parse_constant=invalid)
        _tree(result)
        return result
    except MLReviewProjectionError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise MLReviewProjectionError("ml_review_projection_invalid_json") from None


def sql_canonical(value):
    """0067 recursive SQL convention only. Floating Python values are refused."""
    _tree(value)
    parts, size = [], 0
    def append(part):
        nonlocal size
        size += len(part.encode("utf-8"))
        _require(size <= MAX_BYTES, "ml_review_projection_byte_limit")
        parts.append(part)
    def emit(item):
        if type(item) is dict:
            append("{")
            for index, key in enumerate(sorted(item)):
                if index: append(",")
                append(json.dumps(key, ensure_ascii=False)); append(":"); emit(item[key])
            append("}")
        elif type(item) is list:
            append("[")
            for index, part in enumerate(item):
                if index: append(",")
                emit(part)
            append("]")
        elif type(item) is Decimal:
            _require(size + _number_length(item) <= MAX_BYTES, "ml_review_projection_byte_limit")
            append(format(item.copy_abs() if item.is_zero() else item, "f"))
        else:
            append(json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    try:
        emit(value)
    except MLReviewProjectionError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise MLReviewProjectionError("ml_review_projection_canonical_unavailable") from None
    return "".join(parts)


def adjudication_record_sha256(row_text):
    row = parse_sql_json(row_text)
    _require(type(row) is dict, "ml_review_projection_record_shape")
    return raw_text_sha256(sql_canonical({key: value for key, value in row.items() if key not in _RECORD_EXCLUDED}))


def publication_role_record_sha256(row_text):
    """0055 grants/revocations have only scalar fields; no generic jsonb claim."""
    row = parse_sql_json(row_text)
    common = {"id", "created_at", "record_sha256", "reason_code"}
    _require(type(row) is dict and set(row) in (common | {"user_id", "role", "granted_by"},
        common | {"grant_id", "revoked_by"}), "ml_review_projection_role_shape")
    _require(all(type(value) is str for value in row.values()), "ml_review_projection_role_shape")
    return raw_text_sha256(sql_canonical({key: value for key, value in row.items()
        if key not in {"id", "created_at", "record_sha256"}}))


def validate_row_wire(value):
    """Parse a private raw-row envelope. Hash means raw text, not 0054 row SHA."""
    _require(type(value) is dict and set(value) == {"table", "row_id", "row_text", "row_sha256"},
        "ml_review_projection_wire_shape")
    _require(type(value["table"]) is str and value["table"] in set(SPEC) | _AUDIT_TABLES,
        "ml_review_projection_wire_table")
    _require(type(value["row_id"]) is str and 0 < len(value["row_id"]) <= 200,
        "ml_review_projection_identity")
    _require(type(value["row_sha256"]) is str and _HASH.fullmatch(value["row_sha256"])
        and raw_text_sha256(value["row_text"]) == value["row_sha256"], "ml_review_projection_wire_hash")
    row = parse_sql_json(value["row_text"])
    key = "paper_id" if value["table"] == "paper_work_map" else "id"
    _require(type(row) is dict and row.get(key) == value["row_id"], "ml_review_projection_wire_identity")
    _require(sql_canonical(row) == value["row_text"], "ml_review_projection_wire_noncanonical")
    return row


def projection_fields(table):
    _require(table in SPEC, "ml_review_projection_table")
    if table == "materials": return frozenset(_MATERIAL)
    if table == "papers": return frozenset(_PAPER)
    if table == "works": return frozenset(_WORK)
    fields = set(SPEC[table]["fields"])
    if table == "research_events": fields -= _EVENT_EXCLUDED
    if table == "evidence_artifacts": fields -= {"access", "license"}
    return frozenset(fields)


def _date(value, kind):
    _require(type(value) is str, "ml_review_projection_timestamp")
    try:
        if kind == "DATE": return date.fromisoformat(value).isoformat()
        parsed = datetime.fromisoformat(value)
        _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "ml_review_projection_timestamp")
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, TypeError, OverflowError):
        raise MLReviewProjectionError("ml_review_projection_timestamp") from None


def _field(value, declaration):
    if value is None: return declaration["nullable"]
    kind = declaration["type"]
    if kind == "JSONB": return True
    if kind == "BOOLEAN": return type(value) is bool
    if kind in {"INTEGER", "SMALLINT", "BIGINT"}: return type(value) is int
    if kind in {"FLOAT", "DOUBLE PRECISION"}: return type(value) in {int, Decimal}
    if kind.startswith("ARRAY"): return type(value) is list
    if kind == "UUID": return _uuid(value) == value
    if kind in {"DATETIME", "DATE"}: _date(value, kind); return True
    if kind.startswith("VARCHAR("): return type(value) is str and len(value) <= int(kind[8:-1])
    return type(value) is str


def _row(table, identifier, value):
    fields = projection_fields(table)
    _require(type(value) is dict and set(value) == fields
        and all(_field(value[key], SPEC[table]["fields"][key]) for key in fields),
        "ml_review_projection_projected_row_shape")
    _require(value["paper_id" if table == "paper_work_map" else "id"] == identifier,
        "ml_review_projection_projected_identity")
    return value


def _closure(index, roots):
    seen, pending = set(), set(roots)
    while pending:
        key = pending.pop()
        if key in seen: continue
        _require(key in index, "ml_review_projection_forward_row_missing")
        seen.add(key)
        table, identifier = key
        row = index[key]
        for fields, target, columns in FKS[table]:
            if not set(fields) <= projection_fields(table): continue
            if all(row[field] is not None for field in fields):
                ref = target, row[fields[0]]
                _require(ref in index and all(row[field] == index[ref][column]
                    for field, column in zip(fields, columns)), "ml_review_projection_forward_binding")
                pending.add(ref)
        if table == "research_events":
            pending.update(ref for ref, child in index.items()
                if ref[0] in {"event_evidence", "snapshot_event_memberships"} and child["event_id"] == identifier)
        elif table == "material_claims":
            pending.update(ref for ref, child in index.items() if ref[0] == "claim_source_occurrences" and child["claim_id"] == identifier)
        elif table == "papers" and ("paper_work_map", identifier) in index:
            pending.add(("paper_work_map", identifier))
    return seen


def parse_subject(text, *, expected_sha256=None):
    if expected_sha256 is not None:
        _require(type(expected_sha256) is str and _HASH.fullmatch(expected_sha256)
            and raw_text_sha256(text) == expected_sha256, "ml_review_projection_subject_hash")
    body = parse_sql_json(text)
    _require(type(body) is dict and set(body) == {"version", "target", "rows", "artifacts", "support_artifact_ids", "native_import"}
        and body["version"] == SUBJECT_VERSION, "ml_review_projection_subject_shape")
    target = body["target"]
    required = {"property_id", "event_id", "event_revision", "material_id", "state_id", "sample_id", "structure_id", "producer_run_id", "native_outcome_id"}
    _require(type(target) is dict and set(target) == required and type(target["event_revision"]) is int
        and target["event_revision"] > 0 and type(target["material_id"]) is str and 0 < len(target["material_id"]) <= 100,
        "ml_review_projection_target_shape")
    for key in required - {"event_revision", "material_id"}:
        if target[key] is not None or key in {"property_id", "event_id", "state_id"}: _uuid(target[key])
    _require(type(body["rows"]) is list and 1 <= len(body["rows"]) <= 1000, "ml_review_projection_row_limit")
    index, keys = {}, []
    for row in body["rows"]:
        _require(type(row) is dict and set(row) == {"table", "row_id", "snapshot"}
            and type(row["table"]) is str and type(row["row_id"]) is str and 0 < len(row["row_id"]) <= 200,
            "ml_review_projection_row_shape")
        key = row["table"], row["row_id"]
        index[key] = _row(*key, row["snapshot"]); keys.append(key)
    _require(keys == sorted(set(keys)), "ml_review_projection_row_inventory")
    prop = index.get(("event_properties", target["property_id"]))
    event = index.get(("research_events", target["event_id"]))
    state = index.get(("material_states", target["state_id"]))
    _require(prop is not None and event is not None and state is not None
        and prop["event_id"] == target["event_id"] and event["revision"] == target["event_revision"]
        and all(event[key] == target[key] for key in ("material_id", "state_id", "structure_id", "producer_run_id"))
        and state["material_id"] == target["material_id"] and state["sample_id"] == target["sample_id"],
        "ml_review_projection_target_binding")
    _require(prop["property_key"] not in {"tc", "tc_kelvin"} and not prop["property_key"].startswith("rps_")
        and event["event_type"] != "priority_assessment", "ml_review_projection_unsupported_subject")
    expected_artifacts = [{"artifact_id": identifier, "bytes_sha256": row["bytes_sha256"], "hash_status": row["hash_status"]}
        for (table, identifier), row in sorted(index.items()) if table == "evidence_artifacts"]
    _require(len(expected_artifacts) <= 200 and body["artifacts"] == expected_artifacts,
        "ml_review_projection_artifact_inventory")
    for artifact in expected_artifacts:
        sha, status = artifact["bytes_sha256"], artifact["hash_status"]
        _require((status == "verified" and type(sha) is str and _HASH.fullmatch(sha))
            or (status in {"unavailable", "not_applicable"} and sha is None), "ml_review_projection_artifact_hash")
    run = index.get(("research_runs", target["producer_run_id"]), {})
    support = {row["artifact_id"] for (table, _), row in index.items()
        if table == "event_evidence" and row["event_id"] == target["event_id"]}
    support.update((state["source_artifact_id"], run.get("input_manifest_id"), run.get("output_manifest_id")))
    support.discard(None)
    _require(body["support_artifact_ids"] == sorted(support), "ml_review_projection_support_inventory")
    roots = {("event_properties", target["property_id"])}
    native = body["native_import"]
    if native is None:
        _require(target["native_outcome_id"] is None, "ml_review_projection_native_binding")
    else:
        _require(type(native) is dict and set(native) == {"outcome_id", "outcome_sha256", "package_id", "package_sha256", "source_files"}
            and native["outcome_id"] == target["native_outcome_id"], "ml_review_projection_native_shape")
        _uuid(native["outcome_id"]); _uuid(native["package_id"])
        _require(all(type(native[key]) is str and _HASH.fullmatch(native[key]) for key in ("outcome_sha256", "package_sha256"))
            and type(native["source_files"]) is list and 1 <= len(native["source_files"]) <= 19,
            "ml_review_projection_native_inventory")
        files = []
        for source in native["source_files"]:
            _require(type(source) is dict and set(source) == {"file_id", "artifact_id", "sha256", "size_bytes"}
                and type(source["sha256"]) is str and _HASH.fullmatch(source["sha256"])
                and type(source["size_bytes"]) is int and 0 <= source["size_bytes"] <= MAX_BYTES,
                "ml_review_projection_native_file")
            _uuid(source["file_id"]); _uuid(source["artifact_id"])
            artifact = index.get(("evidence_artifacts", source["artifact_id"]))
            _require(artifact is not None and artifact["hash_status"] == "verified"
                and artifact["bytes_sha256"] == source["sha256"], "ml_review_projection_native_file_binding")
            roots.add(("evidence_artifacts", source["artifact_id"])); files.append(source["file_id"])
        _require(files == sorted(set(files)), "ml_review_projection_native_file_inventory")
    _require(_closure(index, roots) == set(index), "ml_review_projection_unrelated_subject_row")
    _require(sql_canonical(body) == text, "ml_review_projection_subject_noncanonical")
    return body


def _normalize_row(table, row):
    result = dict(row)
    for key, value in row.items():
        kind = SPEC[table]["fields"][key]["type"]
        if value is not None and kind in {"DATETIME", "DATE"}: result[key] = _date(value, kind)
    return result


def _compare(left, right, *, json_field=False):
    if type(left) in {int, Decimal} and type(right) in {int, Decimal}:
        if left == right: return "matched"
        # A legacy JSONB decimal may already have rounded when 0054 decoded it.
        # There is no safe way to reconstruct it or call a near value equivalent.
        if json_field and type(right) is Decimal and len("".join(map(str, right.as_tuple().digits)).rstrip("0")) > 15:
            return "unresolved"
        return "mismatch"
    if type(left) is not type(right): return "mismatch"
    if type(left) is dict:
        if set(left) != set(right): return "mismatch"
        values = [_compare(left[key], right[key], json_field=json_field) for key in left]
    elif type(left) is list:
        if len(left) != len(right): return "mismatch"
        values = [_compare(a, b, json_field=json_field) for a, b in zip(left, right)]
    else: return "matched" if left == right else "mismatch"
    return "mismatch" if "mismatch" in values else "unresolved" if "unresolved" in values else "matched"


def bridge_frozen_subject(rows_index, *, property_id, subject_text, expected_subject_sha256):
    """Compare verified 0054 row envelopes to a independently hashed SQL subject.

    This validates declared closure, not absence of rows in an external database.
    It cannot recover high-precision JSONB already rounded in a legacy capsule.
    """
    property_id = _uuid(property_id)
    _require(type(rows_index) is dict and 0 < len(rows_index) <= CAPSULE_LIMITS["rows"], "ml_review_projection_frozen_inventory")
    body = parse_subject(subject_text, expected_sha256=expected_subject_sha256)
    _require(body["target"]["property_id"] == property_id, "ml_review_projection_wrong_property")
    frozen, hashes = {}, {}
    for key, envelope in rows_index.items():
        _require(type(key) is tuple and len(key) == 2 and type(envelope) is dict
            and set(envelope) == {"table", "row_id", "data", "row_sha256"}
            and key == (envelope["table"], envelope["row_id"]) and key[0] in SPEC,
            "ml_review_projection_frozen_row")
        data = envelope["data"]
        _require(type(data) is dict and set(data) == set(SPEC[key[0]]["fields"])
            and digest(data) == envelope["row_sha256"], "ml_review_projection_frozen_row_hash")
        parsed = parse_sql_json(canonical(data).decode("utf-8"))
        frozen[key] = _row(*key, {field: parsed[field] for field in projection_fields(key[0])})
        hashes[key] = envelope["row_sha256"]
    roots = {("event_properties", property_id)}
    if body["native_import"]:
        roots.update(("evidence_artifacts", item["artifact_id"]) for item in body["native_import"]["source_files"]
            if ("evidence_artifacts", item["artifact_id"]) in frozen)
    expected = _closure(frozen, roots)
    actual = {(row["table"], row["row_id"]): row["snapshot"] for row in body["rows"]}
    rows = []
    for key in sorted(expected | set(actual)):
        table, identifier = key
        if key not in expected: status, reasons = "mismatch", ["current_forward_row_not_frozen"]
        elif key not in actual: status, reasons = "mismatch", ["frozen_forward_row_not_current"]
        else:
            left, right = _normalize_row(table, frozen[key]), _normalize_row(table, actual[key])
            values = [_compare(left[field], right[field], json_field=SPEC[table]["fields"][field]["type"] == "JSONB") for field in left]
            status = "mismatch" if "mismatch" in values else "unresolved" if "unresolved" in values else "matched"
            reasons = [] if status == "matched" else ["legacy_numeric_precision_unresolved" if status == "unresolved" else "frozen_scientific_projection_changed"]
        rows.append({"table": table, "row_id": identifier, "frozen_row_sha256": hashes.get(key), "status": status, "reason_codes": reasons})
    statuses = {row["status"] for row in rows}
    status = "mismatch" if "mismatch" in statuses else "unresolved" if "unresolved" in statuses else "matched"
    return {"version": VERSION, "property_id": property_id, "subject_sha256": expected_subject_sha256,
        "status": status, "reason_codes": sorted({reason for row in rows for reason in row["reason_codes"]}), "rows": rows}
