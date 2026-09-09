"""Curator preparation of existing RPS descriptors and a sealed registration.

Never fetch sources, infer identities, mint human reviews or grant disclosure.
New descriptor UUIDs/timestamps belong to the durable inventory, not the stable
preview intent. The caller owns the outer transaction and acknowledgement.
"""
from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa

from services import research_distribution as distribution
from services import research_distribution_contract as contract
from services.research_access import active_grant, table
from services.research_distribution_inputs import capture_inputs, load_live_closure, require

VERSION = "rps-distribution-preparation/1.0.0"
SELECTION_VERSION = "rps-distribution-selections/1.0.0"
SOURCE = "sclib:rps-distribution-preparation"
AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False,
             "current_authorization_checked": False}


class PreparationConflict(contract.ResearchDistributionError):
    """The original request, source snapshot or preview intent does not match."""


class PreparationNotFound(contract.ResearchDistributionError):
    """No matching durable registration observed; not proof of rollback."""


def _match(value):
    if not value:
        raise PreparationConflict("distribution_preparation_changed")


def _capture(*, release, selections, public_bundle, expected_release_sha256,
             expected_selections_sha256, expected_public_bundle_sha256,
             artifact_bytes, capsule_artifact_bytes):
    # Capture every caller-owned dictionary before any SQL await.
    values = capture_inputs(release=release, bindings=selections, public_bundle=public_bundle,
        artifact_bytes=artifact_bytes, capsule_artifact_bytes={} if capsule_artifact_bytes is None else capsule_artifact_bytes)
    values["selections"] = values.pop("bindings")
    pins = {"expected_release_sha256": contract._hash(expected_release_sha256),
        "expected_selections_sha256": contract._hash(expected_selections_sha256),
        "expected_public_bundle_sha256": contract._hash(expected_public_bundle_sha256)}
    _match(distribution._sha(values["selections"]) == pins["expected_selections_sha256"])
    # Exact document verification remains the existing frozen public contract.
    contract.public.verify_public_bundle(values["public_bundle"],
        expected_bundle_sha256=pins["expected_public_bundle_sha256"],
        expected_release_sha256=pins["expected_release_sha256"])
    require(distribution._canonical(values["release"]) == distribution._canonical(values["public_bundle"]["release"]))
    release, selections = values["release"], values["selections"]
    contract._object(selections, {"version", "evidence_roots", "identities"})
    require(selections["version"] == SELECTION_VERSION)
    artifacts = {item["id"]: item for item in release["artifacts"]}
    require(0 < len(artifacts) == len(release["artifacts"]) <= contract.MAX_BINDINGS)
    roots, identities = {}, {}
    require(type(selections["evidence_roots"]) is list and type(selections["identities"]) is list
            and len(selections["evidence_roots"]) <= contract.MAX_BINDINGS
            and len(selections["identities"]) <= contract.MAX_BINDINGS)
    for item in selections["evidence_roots"]:
        contract._object(item, {"artifact_id", "root"})
        identifier, root = item["artifact_id"], item["root"]
        require(type(identifier) is str and identifier in artifacts and identifier not in roots
                and artifacts[identifier]["kind"] == "evidence" and type(root) is dict
                and root.get("kind") in {"source_capture", "frozen_result"})
        contract._object(root, contract._ROOT_FIELDS[root["kind"]])
        roots[identifier] = root
    for item in selections["identities"]:
        contract._object(item, {"artifact_id", "table", "row_id", "row_sha256"})
        identifier = item["artifact_id"]
        require(type(identifier) is str and identifier in artifacts and identifier not in identities
                and artifacts[identifier]["kind"] in {"material", "state"})
        require(item["table"] == ("materials" if artifacts[identifier]["kind"] == "material" else "material_states"))
        contract.capsule.row_reference(item["table"], item["row_id"])
        contract._hash(item["row_sha256"])
        identities[identifier] = {key: item[key] for key in ("table", "row_id", "row_sha256")}
    require(set(roots) == {key for key, item in artifacts.items() if item["kind"] == "evidence"}
            and set(identities) == {key for key, item in artifacts.items() if item["kind"] in {"material", "state"}})

    def byte_inventory(values):
        return [{"sha256": sha, "size_bytes": len(data)} for sha, data in sorted(values.items())]

    request = {"version": VERSION, **pins, "artifact_bytes": byte_inventory(values["artifact_bytes"]),
        "capsule_artifact_bytes": [{"manifest_sha256": sha, "files": byte_inventory(payloads)}
            for sha, payloads in sorted(values["capsule_artifact_bytes"].items())]}
    # Independently pinned release/bundle/selections bind their complete content;
    # each captured source byte map is already hash-verified, not a filename list.
    return values, pins, artifacts, roots, identities, distribution._sha(request)


def _describe(inventory):
    """Recover only sealed descriptor projections; never trust mutable live rows."""
    rows = {(row["table"], row["row_id"]): row for row in inventory["dependencies"]}
    descriptor_ids, plans, request_hashes = set(), [], set()
    for binding in inventory["artifact_bindings"]:
        if binding["root"]["kind"] != "internal_artifact":
            continue
        root = binding["root"]
        key = ("evidence_artifacts", root["evidence_artifact_id"])
        require(key in rows and key not in descriptor_ids)
        descriptor_ids.add(key)
        data = rows[key]["projection"]
        _match(data["source"] == SOURCE and data["source_version"] == VERSION and data["access"] == "restricted"
               and data["uri"] is None and data["license"] is None and data["hash_status"] == "verified"
               and data["schema_version"] == contract.INTERNAL_SCHEMA)
        metadata = data["metadata"]
        contract._object(metadata, {"rps_artifact_json", "preparation"})
        contract._object(metadata["preparation"], {"version", "request_sha256"})
        _match(metadata["preparation"]["version"] == VERSION)
        request_hashes.add(contract._hash(metadata["preparation"]["request_sha256"]))
        raw = metadata["rps_artifact_json"]
        require(type(raw) is str and len(raw.encode("utf-8")) <= contract.capsule.LIMITS["file_bytes"])
        artifact = json.loads(raw)
        require(type(artifact) is dict and artifact.get("kind") in contract.INTERNAL_KINDS)
        encoded = contract._bounded(artifact)
        require(encoded == raw.encode("utf-8"))
        sha = hashlib.sha256(encoded).hexdigest()
        _match(artifact["id"] == binding["artifact_id"] and artifact["kind"] == binding["artifact_kind"]
               and artifact["sha256"] == binding["artifact_sha256"] and data["kind"] == contract.INTERNAL_KINDS[artifact["kind"]]
               and data["bytes_sha256"] == data["record_sha256"] == root["bytes_sha256"] == root["record_sha256"] == sha)
        plans.append({"artifact_id": artifact["id"], "kind": data["kind"], "schema_version": contract.INTERNAL_SCHEMA, "bytes_sha256": sha})
    require(len(request_hashes) == 1 and len(plans) > 0)
    sources = [row for row in inventory["dependencies"] if (row["table"], row["row_id"]) not in descriptor_ids]
    return next(iter(request_hashes)), sorted(plans, key=lambda item: item["artifact_id"]), sources


def _intent(package, inventory):
    request_sha, plans, sources = _describe(inventory)
    return {"version": VERSION, "scope": distribution.SCOPE,
        "actor_user_id": str(package["actor_user_id"]), "actor_grant_id": str(package["actor_grant_id"]),
        "request_key": package["request_key"], "request_sha256": request_sha,
        "release_manifest_sha256": package["release_manifest_sha256"], "public_bundle_sha256": package["public_bundle_sha256"],
        "source_inventory_sha256": distribution._sha(sources), "descriptor_plan_sha256": distribution._sha(plans),
        "descriptor_count": len(plans), "source_dependency_count": len(sources), **AUTHORITY}


def _result(package, inventory, *, dry_run, replayed):
    intent = _intent(package, inventory)
    return {"version": VERSION, "dry_run": dry_run, "committed": False, "replayed": replayed,
        "intent": intent, "intent_sha256": distribution._sha(intent),
        "descriptor_count": intent["descriptor_count"], "source_dependency_count": intent["source_dependency_count"],
        "package": None if dry_run and not replayed else {"id": str(package["id"]),
            "record_sha256": package["record_sha256"], "bindings_sha256": package["bindings_sha256"],
            "inventory_sha256": package["inventory_sha256"], "dependency_count": package["dependency_count"]}, **AUTHORITY}


async def _existing(db, actor_user_id, request_key):
    relation = table(distribution.PREFIX + "packages")
    matches = await distribution._history(db, "packages", sa.and_(relation.c.actor_user_id == distribution._uuid(actor_user_id),
        relation.c.request_key == distribution._key(request_key)), header=True)
    return None if not matches else await distribution._package(db, matches[0]["id"])


async def preparation_capabilities(db, *, actor_user_id):
    await distribution._read_session(db)
    grant = await active_grant(db, distribution._uuid(actor_user_id), role="curator")
    return {"version": VERSION, "scope": distribution.SCOPE, "actor_user_id": str(actor_user_id),
        "actor_grant_id": str(grant["id"]), "can_read": True, "can_prepare": True, **AUTHORITY}


async def preparation_outcome(db, *, actor_user_id, request_key, expected_intent_sha256):
    await distribution._read_session(db)
    await active_grant(db, distribution._uuid(actor_user_id), role="curator")
    expected = contract._hash(expected_intent_sha256)
    existing = await _existing(db, actor_user_id, request_key)
    if existing is None:
        raise PreparationNotFound("distribution_preparation_not_observed")
    result = _result(*existing, dry_run=False, replayed=True)
    _match(result["intent_sha256"] == expected)
    return result


async def prepare_distribution(db, *, actor_user_id, request_key, release, selections, public_bundle,
        expected_release_sha256, expected_selections_sha256, expected_public_bundle_sha256,
        artifact_bytes, capsule_artifact_bytes=None, expected_intent_sha256=None, dry_run=True):
    require(type(dry_run) is bool and (dry_run or expected_intent_sha256 is not None))
    expected = None if expected_intent_sha256 is None else contract._hash(expected_intent_sha256)
    inputs, pins, artifacts, roots, identities, request_sha = _capture(release=release, selections=selections,
        public_bundle=public_bundle, expected_release_sha256=expected_release_sha256,
        expected_selections_sha256=expected_selections_sha256, expected_public_bundle_sha256=expected_public_bundle_sha256,
        artifact_bytes=artifact_bytes, capsule_artifact_bytes=capsule_artifact_bytes)
    async with distribution._write(db, dry_run) as operation:
        actor = await distribution._actor(db, actor_user_id, request_key, "curator")
        existing = await _existing(db, actor_user_id, request_key)
        if existing is not None:
            result = _result(*existing, dry_run=dry_run, replayed=True)
            _match(result["intent"]["request_sha256"] == request_sha
                   and result["intent"]["actor_grant_id"] == str(actor["actor_grant_id"]))
        else:
            live_roots = [{"table": item["table"], "row_id": item["row_id"]} for item in identities.values()]
            for root in roots.values():
                if root["kind"] == "source_capture":
                    live_roots.extend([{"table": "source_revisions", "row_id": root["source_revision_id"]},
                        {"table": "source_captures", "row_id": root["capture_id"]}])
            source_rows = await load_live_closure(db, live_roots)
            contract._bytes({(row["table"], row["row_id"]): row for row in source_rows}, inputs["artifact_bytes"])
            bindings, generated_bytes = [], {}
            for identifier, artifact in sorted(artifacts.items()):
                if artifact["kind"] == "evidence":
                    root = roots[identifier]
                else:
                    data = contract._bounded(artifact)
                    sha = hashlib.sha256(data).hexdigest()
                    require(len(data) <= contract.capsule.LIMITS["file_bytes"])
                    generated_bytes[sha] = data
                    require(sum(map(len, generated_bytes.values())) <= contract.MAX_BYTES)
                    relation = table("evidence_artifacts")
                    row = (await db.execute(relation.insert().values(kind=contract.INTERNAL_KINDS[artifact["kind"]],
                        schema_version=contract.INTERNAL_SCHEMA, source=SOURCE, source_version=VERSION,
                        record_sha256=sha, bytes_sha256=sha, hash_status="verified", access="restricted", uri=None, license=None,
                        # JSONB normalizes numbers (including -0.0). Retain the
                        # complete canonical byte text, not a reserialized object.
                        metadata={"rps_artifact_json": data.decode("utf-8"), "preparation": {"version": VERSION, "request_sha256": request_sha}})
                        .returning(relation.c.id))).scalar_one()
                    operation["changed"] = True
                    root = {"kind": "internal_artifact", "evidence_artifact_id": str(row),
                        "artifact_kind": contract.INTERNAL_KINDS[artifact["kind"]], "record_sha256": sha, "bytes_sha256": sha}
                bindings.append({"artifact_id": identifier, "artifact_kind": artifact["kind"], "artifact_sha256": artifact["sha256"],
                    "root": root, "identity": identities.get(identifier)})
            # Source bytes were checked against their exact live closure before
            # creating descriptors. Legitimately shared identical bytes dedupe.
            binding = {"version": contract.BINDINGS_VERSION, "release_id": inputs["release"]["id"],
                "release_manifest_sha256": pins["expected_release_sha256"],
                "public_bundle_sha256": pins["expected_public_bundle_sha256"], "bindings": bindings}
            registered = await distribution.register_distribution(db, actor_user_id=actor["actor_user_id"],
                request_key=actor["request_key"], release=inputs["release"], bindings=binding,
                public_bundle=inputs["public_bundle"], expected_release_sha256=pins["expected_release_sha256"],
                expected_public_bundle_sha256=pins["expected_public_bundle_sha256"], expected_bindings_sha256=distribution._sha(binding),
                artifact_bytes={**inputs["artifact_bytes"], **generated_bytes}, capsule_artifact_bytes=inputs["capsule_artifact_bytes"], dry_run=False)
            package = await distribution._get(db, "packages", registered["package_id"], header=True)
            result = _result(package, registered["inventory"], dry_run=dry_run, replayed=False)
        if expected is not None:
            _match(result["intent_sha256"] == expected)
    return result
