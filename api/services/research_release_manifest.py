"""Bounded offline research-closure integrity, never scientific authorization.

The database writer enumerates owned rows under its shared write lock. This
module independently reconstructs references inside that pinned capture; it
cannot discover an omitted database row after an attacker reseals an entirely
new manifest. The caller must independently pin the expected manifest digest.
No database, network, filesystem, ORM or provider imports are used here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from datetime import date, datetime
from uuid import UUID

from .research_release_spec import FKS, SPEC, TABLE_FIELDS

VERSION = "research-release/1.0.0"
CLOSURE_POLICY_VERSION = "research-closure/1.0.0"
REVIEW_VERSION = "research-freeze-processing-review/1.0.0"
LIMITS = {"rows": 1000, "examples": 100, "artifacts": 200,
          "file_bytes": 8 * 1024 * 1024, "combined_bytes": 64 * 1024 * 1024,
          "json_depth": 48, "json_nodes": 200000}
SOURCE_ROOT_TABLES = frozenset({"snapshot_event_memberships", "claim_source_occurrences",
                              "research_import_memberships", "research_import_receipts"})
OWNED_RELATIONS = {
    "ml_dataset_snapshots": (("ml_examples", "dataset_snapshot_id"),),
    "ml_examples": (("ml_example_inputs", "example_id"),),
    "research_events": (("material_claims", "event_id"), ("event_properties", "event_id"),
                        ("event_evidence", "event_id")),
    "material_claims": (("claim_qc", "claim_id"),),
    "source_snapshots": (("snapshot_event_memberships", "snapshot_id"),),
    "papers": (("paper_work_map", "paper_id"),),
}
_MANIFEST_FIELDS = frozenset({"version", "closure_policy_version", "dataset_id",
                            "policy_artifact_ids", "review_artifact_id", "source_roots",
                            "rows", "artifacts", "limits", "scientific_acceptance",
                            "public_release", "ml_training_approved"})
_HASH = re.compile(r"^[0-9a-f]{64}$")


class ResearchReleaseVerificationError(ValueError):
    """The bounded integrity capsule cannot be verified."""


def _require(condition, message):
    if not condition:
        raise ResearchReleaseVerificationError(message)


def _bounded_json(value):
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(nodes <= LIMITS["json_nodes"] and depth <= LIMITS["json_depth"], "JSON resource limit")
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "JSON object keys must be strings")
            _require(nodes + len(pending) + 2 * len(item) <= LIMITS["json_nodes"], "JSON resource limit")
            pending.extend((key, depth + 1) for key in item)
            pending.extend((value, depth + 1) for value in item.values())
        elif type(item) is list:
            _require(nodes + len(pending) + len(item) <= LIMITS["json_nodes"], "JSON resource limit")
            pending.extend((value, depth + 1) for value in item)
        elif type(item) is float:
            _require(math.isfinite(item), "nonfinite JSON number")
        elif type(item) is str:
            try:
                item.encode("utf-8")
            except UnicodeError as exc:
                raise ResearchReleaseVerificationError("invalid Unicode") from exc
        else:
            _require(item is None or type(item) in {int, bool}, "non-JSON value")


def canonical(value):
    _bounded_json(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise ResearchReleaseVerificationError("invalid canonical JSON") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _same(actual, expected, message):
    _require(canonical(actual) == canonical(expected), message)


def row_reference(table, row_id):
    _require(type(table) is str and table in TABLE_FIELDS, "unsupported closure table")
    _require(type(row_id) is str and 0 < len(row_id) <= 200, "invalid closure row ID")
    return table, row_id


def owned_relations(table):
    return OWNED_RELATIONS.get(table, ())


def dependencies(table, data):
    """Exact outbound references for the shared server/offline closure policy."""
    _require(type(table) is str and table in TABLE_FIELDS and type(data) is dict, "unsupported row shape")
    refs = set()
    for fields, target, _columns in FKS[table]:
        if all(data.get(field) is not None for field in fields):
            refs.add(row_reference(target, data[fields[0]]))
    if table == "research_import_receipts":
        manifest = data.get("selection_manifest")
        _require(type(manifest) is dict and type(manifest.get("row_ids")) is dict,
                 "shadow receipt requires pinned row inventory")
        for name, identifiers in manifest["row_ids"].items():
            _require(name in {"research_import_snapshots", "research_import_occurrences",
                              "research_import_revisions", "research_import_memberships"},
                     "unsupported shadow receipt dependency")
            _require(type(identifiers) is list and len(identifiers) <= LIMITS["rows"],
                     "shadow receipt dependency limit")
            for identifier in identifiers:
                refs.add(row_reference(name, identifier))
    return tuple(sorted(refs))


def _field_shape(value, declaration):
    if value is None:
        return declaration["nullable"]
    kind = declaration["type"]
    if kind == "JSONB":
        return True
    if kind == "BOOLEAN":
        return type(value) is bool
    if kind in {"INTEGER", "SMALLINT", "BIGINT"}:
        return type(value) is int
    if kind in {"FLOAT", "DOUBLE PRECISION"}:
        return type(value) in {int, float}
    if kind.startswith("ARRAY"):
        return type(value) is list
    if kind == "UUID":
        try:
            return type(value) is str and str(UUID(value)) == value
        except (ValueError, AttributeError):
            return False
    if kind in {"DATETIME", "DATE"}:
        try:
            if type(value) is not str:
                return False
            parsed = datetime.fromisoformat(value) if kind == "DATETIME" else date.fromisoformat(value)
            return kind == "DATE" or parsed.tzinfo is not None and parsed.utcoffset() is not None
        except ValueError:
            return False
    if kind.startswith("VARCHAR("):
        return type(value) is str and len(value) <= int(kind[8:-1])
    return type(value) is str


def _rows(rows):
    _require(type(rows) is list and 0 < len(rows) <= LIMITS["rows"], "closure row limit or shape")
    found = {}
    for row in rows:
        _require(type(row) is dict and set(row) == {"table", "row_id", "data", "row_sha256"},
                 "invalid closure row envelope")
        key = row_reference(row["table"], row["row_id"])
        _require(key not in found, "duplicate closure row")
        data = row["data"]
        _require(type(data) is dict and set(data) == TABLE_FIELDS[key[0]], "incomplete or unknown row fields")
        _require(all(_field_shape(data[name], declaration)
                     for name, declaration in SPEC[key[0]]["fields"].items()), "invalid typed row field")
        _same(data["paper_id" if key[0] == "paper_work_map" else "id"], key[1], "row identity mismatch")
        _same(row["row_sha256"], digest(data), "row digest mismatch")
        found[key] = row
    _same(rows, [found[key] for key in sorted(found)], "rows must be canonically ordered")
    _require(sum(key[0] == "ml_examples" for key in found) <= LIMITS["examples"], "example limit")
    return found


def _roots(manifest, found, *, allow_preview):
    roots = {row_reference("ml_dataset_snapshots", manifest["dataset_id"])}
    policies = manifest["policy_artifact_ids"]
    _require(type(policies) is list and 2 <= len(policies) <= 20
             and all(type(item) is str for item in policies)
             and policies == sorted(set(policies)), "task and registry policy roots required")
    for identifier in policies:
        key = row_reference("evidence_artifacts", identifier)
        _require(key in found and found[key]["data"]["kind"] == "policy", "policy artifact unresolved")
        roots.add(key)
    source_roots = manifest["source_roots"]
    _require(type(source_roots) is list and len(source_roots) <= LIMITS["rows"], "source root limit")
    selected = []
    for item in source_roots:
        _require(type(item) is dict and set(item) == {"table", "row_id"}
                 and type(item["table"]) is str and item["table"] in SOURCE_ROOT_TABLES,
                 "unsupported explicit source root")
        selected.append(row_reference(item["table"], item["row_id"]))
    _require(selected == sorted(set(selected)), "source roots must be unique and ordered")
    roots.update(selected)
    review = manifest["review_artifact_id"]
    if review is None:
        _require(allow_preview, "processing review required")
    else:
        roots.add(row_reference("evidence_artifacts", review))
    _require(all(key in found for key in roots), "missing closure root")
    return roots


def _dag(edges, label):
    nodes = set(edges) | {item for targets in edges.values() for item in targets}
    indegree = {key: 0 for key in nodes}
    for targets in edges.values():
        for target in targets:
            indegree[target] += 1
    ready = deque(key for key in nodes if indegree[key] == 0)
    visited = 0
    while ready:
        key = ready.popleft()
        visited += 1
        for target in edges.get(key, ()):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    _require(visited == len(nodes), f"{label} cycle")


def _closure(found, roots):
    graph = {key: set(dependencies(key[0], row["data"])) for key, row in found.items()}
    for key, row in found.items():
        for child_table, field in owned_relations(key[0]):
            graph[key].update(child for child, entry in found.items()
                              if child[0] == child_table and entry["data"][field] == key[1])
        for fields, target, columns in FKS[key[0]]:
            if all(row["data"][field] is not None for field in fields):
                target_key = (target, row["data"][fields[0]])
                _require(target_key in found, "missing dependency")
                _same([row["data"][field] for field in fields],
                      [found[target_key]["data"][field] for field in columns],
                      "dependency revision or relational binding mismatch")
    _require(all(dependency in found for targets in graph.values() for dependency in targets),
             "missing dependency")
    seen, pending = set(), list(roots)
    while pending:
        key = pending.pop()
        if key not in seen:
            seen.add(key)
            pending.extend(graph[key] - seen)
    _require(seen == set(found), "unreachable undeclared closure rows")
    derivation = {}
    for key, row in found.items():
        data = row["data"]
        if key[0] == "event_evidence" and data["link_type"] == "derives_from":
            _require(data["input_event_id"] is not None
                     and (data["input_property_id"] is None) != (data["input_claim_id"] is None),
                     "derivation requires an exact result input")
            derivation.setdefault(data["event_id"], set()).add(data["input_event_id"])
    _dag(derivation, "scientific derivation")
    for table, field in (("research_runs", "parent_run_id"), ("structure_records", "parent_structure_id"),
                         ("research_events", "supersedes_id"), ("research_import_revisions", "supersedes_id"),
                         ("materials", "parent_material_id")):
        _dag({key[1]: {row["data"][field]} for key, row in found.items()
              if key[0] == table and row["data"][field] is not None}, f"{table} ancestry")
    return graph


def _artifact_inventory(found, artifact_bytes):
    _require(type(artifact_bytes) is dict and len(artifact_bytes) <= LIMITS["artifacts"], "artifact limit or shape")
    expected = set()
    for key, row in found.items():
        data = row["data"]
        if key[0] == "evidence_artifacts":
            _require(data["hash_status"] == "verified", "artifact bytes unavailable or unverified")
            expected.add(data["bytes_sha256"])
        elif key[0] == "source_captures":
            expected.add(data["bytes_sha256"])
    _require(all(type(value) is str and _HASH.fullmatch(value) for value in expected), "invalid byte digest")
    _require(set(artifact_bytes) == expected, "missing or undeclared artifact bytes")
    inventory = []
    total = 0
    for value in sorted(expected):
        payload = artifact_bytes[value]
        _require(type(payload) is bytes and len(payload) <= LIMITS["file_bytes"], "artifact byte limit or shape")
        _require(hashlib.sha256(payload).hexdigest() == value, "artifact byte digest mismatch")
        total += len(payload)
        _require(total <= LIMITS["combined_bytes"], "combined byte limit")
        inventory.append({"sha256": value, "bytes": len(payload), "path": f"{value}.bin"})
    return inventory


def processing_review_payload(base_manifest):
    _require(type(base_manifest) is dict and base_manifest.get("review_artifact_id") is None,
             "processing review requires base preview")
    return {"version": REVIEW_VERSION, "preview_sha256": digest(base_manifest),
            "restricted_internal_processing_approved": True, "scientific_acceptance": False,
            "public_release_approved": False, "ml_training_approved": False}


def base_manifest(manifest):
    """Remove only the isolated processing root, not scientific decision roots."""
    review = manifest["review_artifact_id"]
    if review is None:
        return json.loads(canonical(manifest))
    selected = next((row for row in manifest["rows"]
                     if row["table"] == "evidence_artifacts" and row["row_id"] == review), None)
    _require(selected is not None, "processing review row missing")
    base = json.loads(canonical(manifest))
    base["review_artifact_id"] = None
    base["rows"] = [row for row in base["rows"] if not (row["table"] == "evidence_artifacts" and row["row_id"] == review)]
    retained = {row["data"]["bytes_sha256"] for row in base["rows"]
                if row["table"] in {"evidence_artifacts", "source_captures"}}
    base["artifacts"] = [item for item in base["artifacts"] if item["sha256"] in retained]
    return base


def preview_digest(manifest):
    return digest(base_manifest(manifest))


def verify_manifest(manifest, *, artifact_bytes, expected_manifest_sha256=None, allow_preview=False):
    """Verify typed pinned rows, exact closure, DAGs, bytes and review binding."""
    _require(type(allow_preview) is bool, "allow_preview requires boolean")
    _require(type(manifest) is dict and set(manifest) == _MANIFEST_FIELDS, "unsupported manifest fields")
    encoded = canonical(manifest)
    _require(len(encoded) <= LIMITS["file_bytes"], "manifest byte limit")
    actual = hashlib.sha256(encoded).hexdigest()
    if expected_manifest_sha256 is not None:
        _require(type(expected_manifest_sha256) is str and _HASH.fullmatch(expected_manifest_sha256)
                 and actual == expected_manifest_sha256, "pinned manifest digest mismatch")
    _require(manifest["version"] == VERSION and manifest["closure_policy_version"] == CLOSURE_POLICY_VERSION,
             "unsupported manifest version")
    _same(manifest["limits"], LIMITS, "unsupported manifest limits")
    _require(all(manifest[key] is False for key in ("scientific_acceptance", "public_release", "ml_training_approved")),
             "integrity is not scientific or publication approval")
    found = _rows(manifest["rows"])
    roots = _roots(manifest, found, allow_preview=allow_preview)
    _closure(found, roots)
    dataset = found[("ml_dataset_snapshots", manifest["dataset_id"])]["data"]
    examples = sum(key[0] == "ml_examples" and row["data"]["dataset_snapshot_id"] == manifest["dataset_id"]
                   for key, row in found.items())
    _require(examples > 0 and dataset["row_count"] == examples, "dataset example count mismatch or empty")
    inventory = _artifact_inventory(found, artifact_bytes)
    _same(manifest["artifacts"], inventory, "artifact inventory mismatch")
    _require(len(encoded) + sum(item["bytes"] for item in inventory) <= LIMITS["combined_bytes"], "combined byte limit")
    for key, row in found.items():
        if key[0] == "research_import_revisions":
            _require(row["data"]["review_status"] == "pending" and row["data"]["scientific_acceptance"] is False,
                     "shadow interpretation cannot inherit scientific acceptance")
    if manifest["review_artifact_id"] is not None:
        review_key = ("evidence_artifacts", manifest["review_artifact_id"])
        review = found[review_key]["data"]
        base = base_manifest(manifest)
        base_bytes = {item["sha256"]: artifact_bytes[item["sha256"]] for item in base["artifacts"]}
        verify_manifest(base, artifact_bytes=base_bytes, allow_preview=True)
        document = processing_review_payload(base)
        _require(review["kind"] == "review" and review["schema_version"] == REVIEW_VERSION,
                 "processing review schema mismatch")
        _require(type(review["metadata"]) is dict, "processing review metadata missing")
        _same(review["metadata"].get("shadow_freeze_review"), document, "processing review preview mismatch")
        _same(review["record_sha256"], digest(document), "processing review record digest mismatch")
        _require(artifact_bytes[review["bytes_sha256"]] == canonical(document), "processing review bytes mismatch")
    return {"version": VERSION, "manifest_sha256": actual, "preview_sha256": preview_digest(manifest),
            "row_count": len(found), "artifact_count": len(inventory),
            "integrity_verified": True, "scientific_acceptance": False, "public_release": False,
            "ml_training_approved": False, "reviewer_authority_authenticated": False,
            "database_completeness_independently_proven": False}


def build_manifest(*, dataset_id, rows, policy_artifact_ids, source_roots, artifact_bytes,
                   review_artifact_id=None):
    """Assemble a validated preview/final manifest; creates no approval."""
    found = _rows(sorted(rows, key=lambda row: (row["table"], row["row_id"])))
    manifest = {"version": VERSION, "closure_policy_version": CLOSURE_POLICY_VERSION,
                "dataset_id": dataset_id, "policy_artifact_ids": sorted(policy_artifact_ids),
                "review_artifact_id": review_artifact_id,
                "source_roots": sorted(source_roots, key=lambda row: (row["table"], row["row_id"])),
                "rows": [found[key] for key in sorted(found)],
                "artifacts": _artifact_inventory(found, artifact_bytes), "limits": dict(LIMITS),
                "scientific_acceptance": False, "public_release": False, "ml_training_approved": False}
    verify_manifest(manifest, artifact_bytes=artifact_bytes, allow_preview=review_artifact_id is None)
    return manifest
