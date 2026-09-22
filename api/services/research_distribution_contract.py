"""Private exact RPS dependency inventory; no authorization or scientific grant.

The service caller must load rows/capsules itself under its database boundary.
Arbitrary supplied rows cannot authenticate a database observation. This module
performs no DB/network or caller-path I/O. The existing public-bundle verifier
reads only its own installed implementation sources to check its frozen digest.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from uuid import UUID

from services import priority_public_bundle as public
from services import research_release_manifest as capsule
from services.ml_frozen_provenance import _registry_intact, resolve_result_context
from services.research_priority import canonical_json

VERSION = "research-distribution-inventory/1.0.0"
BINDINGS_VERSION = "research-distribution-bindings/1.0.0"
DEPENDENCY_VERSION = "research-distribution-dependency/1.0.0"
INTERNAL_SCHEMA = "rps-artifact-record/1.0.0"
MAX_BINDINGS = 5000
MAX_DEPENDENCIES = 20000
MAX_CAPSULES = 8
MAX_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 48
MAX_NODES = 500000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,120}\Z")
INTERNAL_KINDS = {
    "material": "other", "state": "other", "action": "other",
    "profile_assignment": "policy", "rubric": "policy", "action_template": "policy",
    "review": "review", "template_review": "review",
}
_BINDING_FIELDS = {"artifact_id", "artifact_sha256", "artifact_kind", "root", "identity"}
_ROOT_FIELDS = {
    "source_capture": {"kind", "source_revision_id", "source_revision_record_sha256",
                       "capture_id", "capture_record_sha256", "bytes_sha256"},
    "frozen_result": {"kind", "manifest_sha256", "table", "row_id", "row_sha256"},
    "internal_artifact": {"kind", "evidence_artifact_id", "artifact_kind", "record_sha256", "bytes_sha256"},
}
AUTHORITY = {
    "scientific_acceptance": False, "ml_training_approved": False,
    "source_rights_verified": False, "current_authorization_checked": False,
    "database_observation_authenticated": False,
}


class ResearchDistributionError(ValueError):
    """Static controlled failure; no source text, caller path, or secret detail."""


def _require(condition):
    if not condition:
        raise ResearchDistributionError("distribution_binding_verification_failed")


def _object(value, fields):
    _require(type(value) is dict and set(value) == set(fields))


def _hash(value):
    _require(type(value) is str and _HASH.fullmatch(value))
    return value


def _uuid(value):
    _require(type(value) is str and str(UUID(value)) == value)
    return value


def _bounded(value):
    pending, nodes, text_bytes = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(nodes <= MAX_NODES and depth <= MAX_DEPTH)
        if type(item) is dict:
            _require(len(item) <= MAX_DEPENDENCIES and all(type(key) is str for key in item))
            _require(nodes + len(pending) + 2 * len(item) <= MAX_NODES)
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            _require(len(item) <= MAX_DEPENDENCIES and nodes + len(pending) + len(item) <= MAX_NODES)
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            text_bytes += len(item.encode("utf-8"))
            _require(text_bytes <= MAX_BYTES)
        elif type(item) in (int, float):
            _require(math.isfinite(item))
        else:
            _require(item is None or type(item) is bool)
    encoded = canonical_json(value).encode("utf-8")
    _require(len(encoded) <= MAX_BYTES)
    return encoded


def _prepare(release, bindings, *, expected_release_sha256, expected_bindings_sha256,
             public_bundle, expected_public_bundle_sha256):
    for value in (expected_release_sha256, expected_bindings_sha256, expected_public_bundle_sha256):
        _hash(value)
    _require(capsule.digest(bindings) == expected_bindings_sha256)
    _bounded({"release": release, "bindings": bindings, "public_bundle": public_bundle})
    public.verify_public_bundle(public_bundle, expected_bundle_sha256=expected_public_bundle_sha256,
                                expected_release_sha256=expected_release_sha256)
    _require(canonical_json(public_bundle["release"]) == canonical_json(release))
    _object(bindings, {"version", "release_id", "release_manifest_sha256", "public_bundle_sha256", "bindings"})
    _require(bindings["version"] == BINDINGS_VERSION and bindings["release_id"] == release["id"]
             and bindings["release_manifest_sha256"] == expected_release_sha256
             and bindings["public_bundle_sha256"] == expected_public_bundle_sha256)
    artifacts = {item["id"]: item for item in release["artifacts"]}
    entries = bindings["bindings"]
    _require(type(entries) is list and len(entries) == len(artifacts) <= MAX_BINDINGS)
    seen, roots, manifests = [], set(), set()
    for entry in entries:
        _object(entry, _BINDING_FIELDS)
        identifier = entry["artifact_id"]
        _require(type(identifier) is str and _ID.fullmatch(identifier) and identifier in artifacts)
        artifact = artifacts[identifier]
        _require(entry["artifact_sha256"] == artifact["sha256"] and entry["artifact_kind"] == artifact["kind"])
        seen.append(identifier)
        identity = entry["identity"]
        if artifact["kind"] in {"material", "state"}:
            _object(identity, {"table", "row_id", "row_sha256"})
            _require(identity["table"] == ("materials" if artifact["kind"] == "material" else "material_states"))
            _hash(identity["row_sha256"])
            roots.add(capsule.row_reference(identity["table"], identity["row_id"]))
            if identity["table"] == "material_states":
                _uuid(identity["row_id"])
        else:
            _require(identity is None)
        root = entry["root"]
        _require(type(root) is dict and type(root.get("kind")) is str and root["kind"] in _ROOT_FIELDS)
        _object(root, _ROOT_FIELDS[root["kind"]])
        if root["kind"] == "internal_artifact":
            _require(artifact["kind"] in INTERNAL_KINDS and root["artifact_kind"] == INTERNAL_KINDS[artifact["kind"]])
            _uuid(root["evidence_artifact_id"])
            _hash(root["record_sha256"])
            _hash(root["bytes_sha256"])
            roots.add(("evidence_artifacts", root["evidence_artifact_id"]))
        else:
            _require(artifact["kind"] == "evidence")
            if root["kind"] == "source_capture":
                _require(artifact["content"]["source_kind"] == "literature")
                _uuid(root["source_revision_id"])
                _uuid(root["capture_id"])
                for key in ("source_revision_record_sha256", "capture_record_sha256", "bytes_sha256"):
                    _hash(root[key])
                roots.update({("source_revisions", root["source_revision_id"]), ("source_captures", root["capture_id"])})
            else:
                _require(type(root["table"]) is str and root["table"] in {"material_claims", "event_properties"})
                _uuid(root["row_id"])
                _hash(root["row_sha256"])
                manifests.add(_hash(root["manifest_sha256"]))
    _require(seen == sorted(artifacts) and len(seen) == len(set(seen)))
    _require(len(manifests) <= MAX_CAPSULES)
    return json.loads(_bounded(release)), json.loads(_bounded(bindings)), {
        "live_row_roots": [{"table": table, "row_id": row_id} for table, row_id in sorted(roots)],
        "capsule_manifest_sha256s": sorted(manifests),
    }


def distribution_loading_plan(release, bindings, *, expected_release_sha256, expected_bindings_sha256,
                              public_bundle, expected_public_bundle_sha256):
    """Return exact live seeds and capsule pins; this is not a trusted loader."""
    try:
        return _prepare(release, bindings, expected_release_sha256=expected_release_sha256,
            expected_bindings_sha256=expected_bindings_sha256, public_bundle=public_bundle,
            expected_public_bundle_sha256=expected_public_bundle_sha256)[2]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise ResearchDistributionError("distribution_binding_verification_failed") from exc


def _live_rows(rows, seeds):
    _require(type(rows) is list and len(rows) <= MAX_DEPENDENCIES)
    found = {}
    for envelope in rows:
        verified = capsule._rows([envelope])
        key = next(iter(verified))
        _require(key not in found)
        found.update(verified)
    _require(rows == [found[key] for key in sorted(found)])
    # This validates composite references and ancestry too. Rooting every supplied
    # row here does NOT admit extras: exact seed reachability is checked below.
    graph = capsule._closure(found, set(found))
    reached = _reach(graph, seeds)
    _require(reached == set(found))
    return found, graph


def _reach(graph, seeds):
    seen, pending = set(), list(seeds)
    while pending:
        key = pending.pop()
        _require(key in graph)
        if key not in seen:
            seen.add(key)
            pending.extend(graph[key] - seen)
    return seen


def _bytes(found, values):
    _require(type(values) is dict and len(values) <= MAX_DEPENDENCIES)
    expected = {row["data"]["bytes_sha256"] for (table, _), row in found.items()
                if table in {"evidence_artifacts", "source_captures"}}
    _require(set(values) == expected)
    total = 0
    for key, payload in values.items():
        _hash(key)
        _require(type(payload) is bytes and len(payload) <= capsule.LIMITS["file_bytes"])
        total += len(payload)
        _require(total <= MAX_BYTES and hashlib.sha256(payload).hexdigest() == key)
    for (table, _), row in found.items():
        if table == "evidence_artifacts":
            _require(row["data"]["hash_status"] == "verified")
        elif table in {"source_revisions", "source_captures"}:
            _require(_registry_intact(table, row["data"]))
    return total


def _root_seeds(entry):
    root = entry["root"]
    seeds = set()
    if entry["identity"]:
        seeds.add((entry["identity"]["table"], entry["identity"]["row_id"]))
    if root["kind"] == "source_capture":
        seeds.update({("source_revisions", root["source_revision_id"]), ("source_captures", root["capture_id"])})
    elif root["kind"] == "internal_artifact":
        seeds.add(("evidence_artifacts", root["evidence_artifact_id"]))
    return seeds


def _identity(artifact, entry, entries, artifacts, found):
    identity = entry["identity"]
    if identity is None:
        return
    envelope = found[(identity["table"], identity["row_id"])]
    _require(envelope["row_sha256"] == identity["row_sha256"])
    data = envelope["data"]
    if artifact["kind"] == "material":
        _require(artifact["content"]["formula"] == data["formula"])
    else:
        material_id = artifact["content"]["material_id"]
        _require(material_id in entries and artifacts[material_id]["kind"] == "material")
        material_identity = entries[material_id]["identity"]
        _require(data["material_id"] == material_identity["row_id"])
        for public_key, row_key in (("pressure_status", "pressure_status"), ("pressure_gpa", "pressure_gpa"),
                                    ("temperature_role", "temperature_role"), ("temperature_k", "temperature_k")):
            left, right = artifact["content"][public_key], data[row_key]
            if public_key in {"pressure_gpa", "temperature_k"}:
                _require((left is None and right is None) or (
                    type(left) in {int, float} and type(right) in {int, float}
                    and math.isfinite(left) and math.isfinite(right) and left == right))
            else:
                _require(type(left) is str and type(right) is str and left == right)


def _source_capture(artifact, root, found):
    revision = found[("source_revisions", root["source_revision_id"])]["data"]
    capture = found[("source_captures", root["capture_id"])]["data"]
    _require(revision["record_sha256"] == root["source_revision_record_sha256"]
             and capture["record_sha256"] == root["capture_record_sha256"]
             and capture["source_revision_id"] == revision["id"]
             and capture["bytes_sha256"] == root["bytes_sha256"])
    _require(revision["version_status"] == "pinned" and revision["provider_revision"] is not None
             and artifact["content"]["source_version"] == revision["provider_revision"])
    _require(revision["work_id"] is not None and ("works", revision["work_id"]) in found)
    mapping = found.get(("paper_work_map", revision["paper_id"]))
    _require(mapping and mapping["data"]["work_id"] == revision["work_id"]
             and mapping["data"]["review_status"] == "accepted")
    # URL/title/license/locator prose stays a declared description, not proof
    # that a passage entails the assessment, or that a license authorizes use.


def _frozen_result(artifact, root, found, artifact_bytes):
    # This binds the exact declared result/origin, NOT its applicability to any
    # assessed material/state. Evidence can be contextual/opposing or support a
    # general execution template; the frozen RPS fields have no closed semantic
    # bridge contract. No automatic same-state scientific support is asserted.
    key = (root["table"], root["row_id"])
    _require(key in found and found[key]["row_sha256"] == root["row_sha256"])
    data = found[key]["data"]
    event = found.get(("research_events", data["event_id"]))
    _require(event is not None)
    kind = artifact["content"]["source_kind"]
    if kind == "calculation":
        _require(event["data"]["event_type"] == "calculation" and event["data"]["knowledge_origin"] == "Computed")
    elif kind == "curation":
        _require(event["data"]["event_type"] == "curation" and event["data"]["knowledge_origin"] == "Inferred")
    else:
        _require(key[0] == "material_claims")
        node = resolve_result_context(found, key, artifact_bytes).root
        _require(node.source_audit and all(item["review_binding_verified"] is True for item in node.source_audit))


def verify_distribution_bindings(release, bindings, *, expected_release_sha256, expected_bindings_sha256,
                                 rows, artifact_bytes, capsules=None, public_bundle, expected_public_bundle_sha256):
    """Verify every artifact and expand all permission targets, without grants.

    Frozen-result bindings conservatively include EVERY row of their pinned
    capsule, not just the chosen result. All such dependencies need separate
    purpose permissions at the live service boundary. This may intentionally
    withhold a package whose broad frozen capture contains unlicensed material.
    """
    try:
        return _verify(release, bindings, expected_release_sha256=expected_release_sha256,
            expected_bindings_sha256=expected_bindings_sha256, rows=rows, artifact_bytes=artifact_bytes,
            capsules={} if capsules is None else capsules, public_bundle=public_bundle,
            expected_public_bundle_sha256=expected_public_bundle_sha256)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise ResearchDistributionError("distribution_binding_verification_failed") from exc


def _verify(release, bindings, *, expected_release_sha256, expected_bindings_sha256,
            rows, artifact_bytes, capsules, public_bundle, expected_public_bundle_sha256):
    release, bindings, plan = _prepare(release, bindings,
        expected_release_sha256=expected_release_sha256, expected_bindings_sha256=expected_bindings_sha256,
        public_bundle=public_bundle, expected_public_bundle_sha256=expected_public_bundle_sha256)
    _require(type(capsules) is dict and set(capsules) == set(plan["capsule_manifest_sha256s"])
             and len(capsules) <= MAX_CAPSULES)
    seeds = {(item["table"], item["row_id"]) for item in plan["live_row_roots"]}
    metadata = {"release": release, "bindings": bindings, "rows": rows, "public_bundle": public_bundle,
                "manifests": []}
    for value in capsules.values():
        _object(value, {"manifest", "artifact_bytes"})
        metadata["manifests"].append(value["manifest"])
    total_bytes = len(_bounded(metadata))
    live, graph = _live_rows(rows, seeds)
    total_bytes += _bytes(live, artifact_bytes)
    all_rows, capture_memberships, frozen = {}, {}, {}

    def add_rows(found, manifest_sha256=None):
        for key, envelope in found.items():
            _require(key not in all_rows or all_rows[key] == envelope)
            all_rows[key] = envelope
            capture_memberships.setdefault(key, set())
            if manifest_sha256:
                capture_memberships[key].add(manifest_sha256)
        _require(len(all_rows) <= MAX_DEPENDENCIES)

    add_rows(live)
    for sha, value in sorted(capsules.items()):
        capsule.verify_manifest(value["manifest"], artifact_bytes=value["artifact_bytes"], expected_manifest_sha256=sha)
        found = capsule._rows(value["manifest"]["rows"])
        total_bytes += _bytes(found, value["artifact_bytes"])
        _require(total_bytes <= MAX_BYTES)
        frozen[sha] = found
        add_rows(found, sha)
    _require(total_bytes <= MAX_BYTES)
    artifacts = {item["id"]: item for item in release["artifacts"]}
    entries = {item["artifact_id"]: item for item in bindings["bindings"]}
    selected = {}
    for identifier, entry in entries.items():
        artifact, root = artifacts[identifier], entry["root"]
        _identity(artifact, entry, entries, artifacts, live)
        members = _reach(graph, _root_seeds(entry)) if _root_seeds(entry) else set()
        if root["kind"] == "source_capture":
            _source_capture(artifact, root, live)
        elif root["kind"] == "internal_artifact":
            data = live[("evidence_artifacts", root["evidence_artifact_id"])]["data"]
            expected = canonical_json(artifact).encode("utf-8")
            expected_hash = hashlib.sha256(expected).hexdigest()
            _require(data["kind"] == root["artifact_kind"] == INTERNAL_KINDS[artifact["kind"]]
                     and data["schema_version"] == INTERNAL_SCHEMA
                     and data["record_sha256"] == root["record_sha256"] == expected_hash
                     and data["bytes_sha256"] == root["bytes_sha256"] == expected_hash
                     and artifact_bytes[expected_hash] == expected)
        else:
            found = frozen[root["manifest_sha256"]]
            _frozen_result(artifact, root, found, capsules[root["manifest_sha256"]]["artifact_bytes"])
            members.update(found)
        selected[identifier] = members
    for entry in release["assessments"]:
        assessment = entry["assessment"]
        material_binding = entries[assessment["material"]["id"]]["identity"]
        data = live[("materials", material_binding["row_id"])]["data"]
        _require(assessment["formula"] == data["formula"] and assessment["family"] == data["family"])
    dependencies, identifiers = [], {}
    for key, envelope in sorted(all_rows.items()):
        table, row_id = key
        data = envelope["data"]
        row_sha256 = envelope["row_sha256"]
        identifier = capsule.digest({"version": DEPENDENCY_VERSION, "table": table,
                                     "row_id": row_id, "row_sha256": row_sha256})
        identifiers[key] = identifier
        record_hash = data.get("record_sha256")
        if record_hash is not None:
            _hash(record_hash)
        byte_hash = data["bytes_sha256"] if table in {"evidence_artifacts", "source_captures"} else None
        dependencies.append({
            "dependency_id": identifier, "table": table, "row_id": row_id, "row_sha256": row_sha256,
            "record_sha256": record_hash, "bytes_sha256": byte_hash, "projection": data,
            "capsule_manifest_sha256s": sorted(capture_memberships[key]),
        })
    output = {
        "version": VERSION, "release_id": release["id"], "release_manifest_sha256": expected_release_sha256,
        "public_bundle_sha256": expected_public_bundle_sha256, "bindings_sha256": expected_bindings_sha256,
        "artifact_bindings": [{**entry, "dependency_ids": sorted(identifiers[key] for key in selected[entry["artifact_id"]])}
                              for entry in bindings["bindings"]],
        "dependencies": sorted(dependencies, key=lambda item: item["dependency_id"]), **AUTHORITY,
    }
    return json.loads(_bounded(output))
