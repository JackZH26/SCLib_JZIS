"""Private, forward-only scientific subject snapshots, never access approval.

PostgreSQL defines the versioned representation. Hash its returned UTF-8 text,
not a Python JSON reserialization (which can change numeric representations).
The caller owns its stable transaction; this module neither writes nor commits.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from services.research_release_spec import TABLE_FIELDS

VERSION = "scientific-result-subject/1.0.0"
MAX_SUBJECT_BYTES = 8 * 1024 * 1024
MAX_ROWS = 1000
MAX_ARTIFACTS = 200
MAX_SECONDS = 10
TARGET_FIELDS = {
    "property_id",
    "event_id",
    "event_revision",
    "material_id",
    "state_id",
    "sample_id",
    "structure_id",
    "producer_run_id",
    "native_outcome_id",
}


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class ScientificSubjectError(ValueError):
    """A static subject identity or representation failure."""


class ScientificSubjectUnavailable(ScientificSubjectError):
    """Database or deadline failure; never an unreviewed result."""


def require(condition, code):
    if not condition:
        raise ScientificSubjectError(code)


def identifier(value):
    require(type(value) is str or isinstance(value, UUID), "scientific_subject_invalid_identity")
    try:
        result = UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ScientificSubjectError("scientific_subject_invalid_identity") from None
    require(str(result) == str(value), "scientific_subject_canonical_identity_required")
    return result


def _json(text):
    require(type(text) is str, "scientific_subject_byte_limit")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        raise ScientificSubjectError("scientific_subject_invalid_json") from None
    require(0 < size <= MAX_SUBJECT_BYTES, "scientific_subject_byte_limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "scientific_subject_duplicate_key")
            result[key] = value
        return result

    try:
        result = json.loads(
            text,
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ScientificSubjectError("scientific_subject_nonfinite_json")
            ),
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ScientificSubjectError("scientific_subject_invalid_json") from None
    pending, nodes = [(result, 0)], 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        require(nodes <= 100000 and depth <= 32, "scientific_subject_json_limit")
        if type(value) is dict:
            require(nodes + len(pending) + len(value) <= 100000, "scientific_subject_json_limit")
            pending.extend((item, depth + 1) for item in value.values())
        elif type(value) is list:
            require(nodes + len(pending) + len(value) <= 100000, "scientific_subject_json_limit")
            pending.extend((item, depth + 1) for item in value)
        elif type(value) is float:
            require(math.isfinite(value), "scientific_subject_nonfinite_json")
    require(
        type(result) is dict
        and set(result)
        == {"version", "target", "rows", "artifacts", "support_artifact_ids", "native_import"}
        and result.get("version") == VERSION
        and type(result.get("target")) is dict
        and type(result.get("rows")) is list
        and 1 <= len(result["rows"]) <= MAX_ROWS
        and type(result.get("artifacts")) is list
        and len(result["artifacts"]) <= MAX_ARTIFACTS,
        "scientific_subject_shape",
    )
    target = result["target"]
    require(
        set(target) == TARGET_FIELDS
        and type(target["event_revision"]) is int
        and target["event_revision"] >= 1
        and type(target["material_id"]) is str
        and 1 <= len(target["material_id"]) <= 100,
        "scientific_subject_target_shape",
    )
    for key in TARGET_FIELDS - {"event_revision", "material_id"}:
        if target[key] is not None or key in {"property_id", "event_id", "state_id"}:
            identifier(target[key])
    keys, artifact_rows, records = [], {}, {}
    for row in result["rows"]:
        require(
            type(row) is dict
            and set(row) == {"table", "row_id", "snapshot"}
            and type(row["table"]) is str
            and row["table"] in TABLE_FIELDS
            and type(row["row_id"]) is str
            and 1 <= len(row["row_id"]) <= 200
            and type(row["snapshot"]) is dict,
            "scientific_subject_row_shape",
        )
        keys.append((row["table"], row["row_id"]))
        records[(row["table"], row["row_id"])] = row["snapshot"]
        if row["table"] == "evidence_artifacts":
            artifact_rows[row["row_id"]] = row["snapshot"]
    require(
        keys == sorted(set(keys)) and ("event_properties", target["property_id"]) in keys,
        "scientific_subject_row_inventory",
    )
    prop = records[("event_properties", target["property_id"])]
    event = records.get(("research_events", target["event_id"]))
    state = records.get(("material_states", target["state_id"]))
    require(
        prop.get("id") == target["property_id"]
        and prop.get("event_id") == target["event_id"]
        and event is not None
        and state is not None
        and event.get("revision") == target["event_revision"]
        and all(
            event.get(key) == target[key]
            for key in ("material_id", "state_id", "structure_id", "producer_run_id")
        )
        and state.get("material_id") == target["material_id"]
        and state.get("sample_id") == target["sample_id"],
        "scientific_subject_target_bindings",
    )
    artifact_ids = []
    for artifact in result["artifacts"]:
        require(
            type(artifact) is dict
            and set(artifact) == {"artifact_id", "bytes_sha256", "hash_status"},
            "scientific_subject_artifact_shape",
        )
        identifier(artifact["artifact_id"])
        status, checksum = artifact["hash_status"], artifact["bytes_sha256"]
        require(
            type(status) is str
            and (
                (status == "verified" and _hash(checksum))
                or status in {"unavailable", "not_applicable"}
                and checksum is None
            ),
            "scientific_subject_artifact_hash",
        )
        artifact_ids.append(artifact["artifact_id"])
        snapshot = artifact_rows.get(artifact["artifact_id"])
        require(
            snapshot is not None
            and snapshot.get("bytes_sha256") == checksum
            and snapshot.get("hash_status") == status,
            "scientific_subject_artifact_binding",
        )
    require(artifact_ids == sorted(artifact_rows), "scientific_subject_artifact_inventory")
    support = result["support_artifact_ids"]
    require(
        type(support) is list
        and len(support) <= MAX_ARTIFACTS
        and all(type(value) is str for value in support)
        and support == sorted(set(support))
        and set(support) <= set(artifact_ids),
        "scientific_subject_support_inventory",
    )
    native = result["native_import"]
    if native is not None:
        require(
            type(native) is dict
            and set(native)
            == {"outcome_id", "outcome_sha256", "package_id", "package_sha256", "source_files"}
            and _hash(native["outcome_sha256"])
            and _hash(native["package_sha256"]),
            "scientific_subject_native_shape",
        )
        identifier(native["outcome_id"]), identifier(native["package_id"])
        require(
            native["outcome_id"] == target["native_outcome_id"]
            and type(native["source_files"]) is list
            and 1 <= len(native["source_files"]) <= 19,
            "scientific_subject_native_inventory",
        )
        file_ids = []
        for item in native["source_files"]:
            require(
                type(item) is dict
                and set(item) == {"file_id", "artifact_id", "sha256", "size_bytes"}
                and _hash(item["sha256"])
                and type(item["size_bytes"]) is int
                and 0 <= item["size_bytes"] <= 8 * 1024 * 1024,
                "scientific_subject_native_file",
            )
            identifier(item["file_id"]), identifier(item["artifact_id"])
            source_artifact = artifact_rows.get(item["artifact_id"])
            require(
                source_artifact is not None
                and source_artifact.get("bytes_sha256") == item["sha256"],
                "scientific_subject_native_source_binding",
            )
            file_ids.append(item["file_id"])
        require(file_ids == sorted(set(file_ids)), "scientific_subject_native_file_inventory")
    else:
        require(target["native_outcome_id"] is None, "scientific_subject_native_binding")
    return result


@dataclass(frozen=True, slots=True)
class ResultSubject:
    text: str
    sha256: str
    subject_id: UUID
    property_row_sha256: str

    @property
    def data(self):
        """A fresh private copy; never return this source-bearing object on HTTP."""
        require(
            hashlib.sha256(self.text.encode("utf-8")).hexdigest() == self.sha256,
            "scientific_subject_private_snapshot_changed",
        )
        return _json(self.text)


async def require_read_session(db):
    require(not (db.new or db.dirty or db.deleted), "scientific_subject_clean_session_required")
    row = (
        (
            await db.execute(
                sa.text("""SELECT current_setting('transaction_isolation') AS isolation,
        current_setting('TimeZone') AS timezone,
        (SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout') AS timeout_ms""")
            )
        )
        .mappings()
        .one()
    )
    require(
        row["isolation"] in {"repeatable read", "serializable"} and row["timezone"] == "UTC",
        "scientific_subject_stable_utc_session_required",
    )
    require(
        type(row["timeout_ms"]) is int and 0 < row["timeout_ms"] <= MAX_SECONDS * 1000,
        "scientific_subject_bounded_statement_timeout_required",
    )


async def capture_result_subject(db, property_id):
    """Capture one exact SQL subject without reverse consumer enumeration."""
    property_id = identifier(property_id)
    try:
        async with asyncio.timeout(MAX_SECONDS):
            await require_read_session(db)
            with db.no_autoflush:
                result = (
                    (
                        await db.execute(
                            sa.text("""
                    WITH captured AS MATERIALIZED (
                      SELECT public.sclib_scientific_subject_capture_v1(:property_id) AS body
                    ) SELECT body,
                      (SELECT public.sclib_scientific_adjudication_canonical_v1(item->'snapshot')
                       FROM jsonb_array_elements(body::jsonb->'rows') AS item
                       WHERE item->>'table'='event_properties' AND item->>'row_id'=:property_key) AS property_text
                    FROM captured
                """),
                            {"property_id": property_id, "property_key": str(property_id)},
                        )
                    )
                    .mappings()
                    .one()
                )
                text, property_text = result["body"], result["property_text"]
                data = _json(text)
                require(
                    data["target"].get("property_id") == str(property_id)
                    and type(property_text) is str
                    and 0 < len(property_text.encode()) <= MAX_SUBJECT_BYTES,
                    "scientific_subject_target_mismatch",
                )
                sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
                subject_id = uuid5(
                    NAMESPACE_URL,
                    json.dumps([VERSION, str(property_id), sha256], separators=(",", ":")),
                )
                return ResultSubject(
                    text,
                    sha256,
                    subject_id,
                    hashlib.sha256(property_text.encode("utf-8")).hexdigest(),
                )
    except (SQLAlchemyError, TimeoutError):
        raise ScientificSubjectUnavailable("scientific_subject_capture_unavailable") from None
