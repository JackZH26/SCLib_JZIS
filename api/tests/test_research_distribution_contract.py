"""Closed synthetic rows, not evidence of a real database or source license."""
import hashlib
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

import pytest

from services import priority_public_bundle as public
from services import research_distribution_contract as distribution
from services import research_release_manifest as capsule
from services.ml_frozen_provenance import _sql_values
from services.research_priority import canonical_json
from services.research_release_spec import SPEC
from tests.test_priority_public_bundle import (
    disclosure_for,
    public_release_payload,
    reseal_public_release,
)


def synthetic_row(table, **values):
    data = {}
    for key, declaration in SPEC[table]["fields"].items():
        kind = declaration["type"]
        if declaration["nullable"]:
            data[key] = None
        elif kind == "UUID":
            data[key] = str(uuid5(NAMESPACE_URL, "synthetic-distribution:" + table + ":" + key))
        elif kind == "DATETIME":
            data[key] = "2026-01-01T00:00:00Z"
        elif kind == "BOOLEAN":
            data[key] = False
        elif kind in {"FLOAT", "DOUBLE PRECISION"}:
            data[key] = 0.0
        elif kind in {"INTEGER", "BIGINT", "SMALLINT"}:
            data[key] = 0
        elif kind == "JSONB":
            data[key] = {}
        elif kind.startswith("ARRAY"):
            data[key] = []
        else:
            data[key] = "synthetic"
    data.update(values)
    if table in {"source_revisions", "source_captures"}:
        native = _sql_values(table, data)
        data["record_sha256"] = capsule.digest({
            key: item for key, item in native.items() if key not in {"created_at", "record_sha256"}
        })
    return {"table": table, "row_id": data["paper_id" if table == "paper_work_map" else "id"],
            "data": data, "row_sha256": capsule.digest(data)}


def make_distribution():
    release = public_release_payload()
    changed = {}
    for artifact in release["artifacts"]:
        if artifact["kind"] == "evidence":
            artifact["content"]["source_kind"] = "literature"
            artifact["sha256"] = capsule.digest({key: value for key, value in artifact.items() if key != "sha256"})
            changed[artifact["id"]] = artifact["sha256"]
    def references(value):
        if type(value) is dict:
            if set(value) == {"id", "sha256"} and value["id"] in changed:
                value["sha256"] = changed[value["id"]]
            else:
                for item in value.values():
                    references(item)
        elif type(value) is list:
            for item in value:
                references(item)
    references(release)
    release = reseal_public_release(release)
    bundle = public.build_public_bundle(release, disclosure=disclosure_for(release))
    payload = b"Synthetic source bytes; not a publication or license."
    sha = hashlib.sha256(payload).hexdigest()
    work = synthetic_row("works")
    paper = synthetic_row("papers", id="synthetic-distribution-paper")
    mapping = synthetic_row("paper_work_map", paper_id=paper["row_id"], work_id=work["row_id"], review_status="accepted")
    revision = synthetic_row("source_revisions", paper_id=paper["row_id"], work_id=work["row_id"],
                             provider_revision="1", revision_key="v1", version_status="pinned",
                             metadata_sha256="1" * 64)
    capture = synthetic_row("source_captures", source_revision_id=revision["row_id"], bytes_sha256=sha,
                            representation="source_text")
    material = synthetic_row("materials", id="synthetic-distribution-material", formula="TEST", family="synthetic")
    state_payload = b"Synthetic captured state declaration; not scientific approval."
    state_sha = hashlib.sha256(state_payload).hexdigest()
    state_source = synthetic_row("evidence_artifacts",
        id=str(uuid5(NAMESPACE_URL, "synthetic-distribution-state-source")), kind="other",
        schema_version="synthetic-state/1.0.0", record_sha256=state_sha, bytes_sha256=state_sha,
        hash_status="verified", access="restricted")
    state = synthetic_row("material_states", material_id=material["row_id"], source_artifact_id=state_source["row_id"],
                          pressure_status="explicit_ambient", pressure_gpa=0, temperature_role="unknown")
    rows = [work, paper, mapping, revision, capture, material, state, state_source]
    artifact_bytes = {sha: payload, state_sha: state_payload}
    bindings = []
    for artifact in sorted(release["artifacts"], key=lambda item: item["id"]):
        identity = None
        if artifact["kind"] == "evidence":
            root = {"kind": "source_capture", "source_revision_id": revision["row_id"],
                    "source_revision_record_sha256": revision["data"]["record_sha256"],
                    "capture_id": capture["row_id"], "capture_record_sha256": capture["data"]["record_sha256"],
                    "bytes_sha256": sha}
        else:
            blob = canonical_json(artifact).encode()
            blob_sha = hashlib.sha256(blob).hexdigest()
            document = synthetic_row("evidence_artifacts",
                id=str(uuid5(NAMESPACE_URL, "synthetic-distribution-artifact:" + artifact["id"])),
                kind=distribution.INTERNAL_KINDS[artifact["kind"]], schema_version=distribution.INTERNAL_SCHEMA,
                bytes_sha256=blob_sha, record_sha256=blob_sha, hash_status="verified", access="restricted")
            rows.append(document)
            artifact_bytes[blob_sha] = blob
            root = {"kind": "internal_artifact", "evidence_artifact_id": document["row_id"],
                    "artifact_kind": document["data"]["kind"], "record_sha256": blob_sha, "bytes_sha256": blob_sha}
            if artifact["kind"] in {"material", "state"}:
                selected = material if artifact["kind"] == "material" else state
                identity = {key: selected[key] for key in ("table", "row_id", "row_sha256")}
        bindings.append({"artifact_id": artifact["id"], "artifact_sha256": artifact["sha256"],
                         "artifact_kind": artifact["kind"], "root": root, "identity": identity})
    manifest = {"version": distribution.BINDINGS_VERSION, "release_id": release["id"],
                "release_manifest_sha256": release["manifest_sha256"], "public_bundle_sha256": bundle["bundle_sha256"],
                "bindings": bindings}
    return {"release": release, "bindings": manifest, "public_bundle": bundle,
            "expected_release_sha256": release["manifest_sha256"], "expected_bindings_sha256": capsule.digest(manifest),
            "expected_public_bundle_sha256": bundle["bundle_sha256"],
            "rows": sorted(rows, key=lambda row: (row["table"], row["row_id"])),
            "artifact_bytes": artifact_bytes}


def plan(fixture):
    return distribution.distribution_loading_plan(**{
        key: value for key, value in fixture.items() if key not in {"rows", "artifact_bytes", "capsules"}
    })


def repin_bindings(fixture):
    fixture["expected_bindings_sha256"] = capsule.digest(fixture["bindings"])


def reseal_row(row):
    if row["table"] in {"source_revisions", "source_captures"}:
        native = _sql_values(row["table"], row["data"])
        row["data"]["record_sha256"] = capsule.digest({
            key: value for key, value in native.items() if key not in {"created_at", "record_sha256"}
        })
    row["row_sha256"] = capsule.digest(row["data"])


def test_complete_recursive_artifact_inventory_and_actual_row_hashes_are_detached():
    fixture = make_distribution()
    before = deepcopy(fixture)
    loading = plan(fixture)
    result = distribution.verify_distribution_bindings(**fixture)
    assert fixture == before
    assert loading["capsule_manifest_sha256s"] == []
    assert len(result["artifact_bindings"]) == len(fixture["release"]["artifacts"])
    assert len(result["dependencies"]) == len(fixture["rows"])
    assert all(result[key] is False for key in distribution.AUTHORITY)
    assert result == distribution.verify_distribution_bindings(**fixture)
    dependencies = {item["dependency_id"]: item for item in result["dependencies"]}
    assert list(dependencies) == sorted(dependencies)
    for item in dependencies.values():
        assert item["row_sha256"] == capsule.digest(item["projection"])
        assert item["dependency_id"] == capsule.digest({
            "version": distribution.DEPENDENCY_VERSION, "table": item["table"],
            "row_id": item["row_id"], "row_sha256": item["row_sha256"],
        })
        assert item["capsule_manifest_sha256s"] == []
    assert set().union(*(set(item["dependency_ids"]) for item in result["artifact_bindings"])) == set(dependencies)
    fixture["rows"][0]["data"].clear()
    assert all(item["projection"] for item in result["dependencies"])


@pytest.mark.parametrize("mutation", [
    "missing_binding", "duplicate_binding", "extra_binding", "reordered_bindings",
    "unknown_top", "unknown_binding", "unknown_root", "unknown_identity", "bad_uuid",
    "bad_hash", "wrong_artifact_kind", "wrong_artifact_hash", "missing_identity",
    "forged_internal_evidence", "wrong_internal_kind", "missing_bundle", "wrong_bundle_pin",
])
def test_closed_binding_inventory_rejects_even_rehashed_inputs(mutation):
    fixture = make_distribution()
    entries = fixture["bindings"]["bindings"]
    material = next(item for item in entries if item["artifact_kind"] == "material")
    evidence = next(item for item in entries if item["artifact_kind"] == "evidence")
    if mutation == "missing_binding": entries.pop()
    elif mutation == "duplicate_binding": entries[-1] = deepcopy(entries[0])
    elif mutation == "extra_binding": entries.append(deepcopy(entries[0]))
    elif mutation == "reordered_bindings": entries.reverse()
    elif mutation == "unknown_top": fixture["bindings"]["public_release"] = True
    elif mutation == "unknown_binding": material["approved"] = True
    elif mutation == "unknown_root": material["root"]["license"] = "forged"
    elif mutation == "unknown_identity": material["identity"]["approved"] = True
    elif mutation == "bad_uuid": material["root"]["evidence_artifact_id"] = "x"
    elif mutation == "bad_hash": material["root"]["record_sha256"] = "A" * 64
    elif mutation == "wrong_artifact_kind": material["artifact_kind"] = "state"
    elif mutation == "wrong_artifact_hash": material["artifact_sha256"] = "f" * 64
    elif mutation == "missing_identity": material["identity"] = None
    elif mutation == "forged_internal_evidence": evidence["root"] = deepcopy(material["root"])
    elif mutation == "wrong_internal_kind": material["root"]["artifact_kind"] = "literature_locator"
    elif mutation == "missing_bundle": fixture["public_bundle"] = None
    elif mutation == "wrong_bundle_pin": fixture["expected_public_bundle_sha256"] = "f" * 64
    repin_bindings(fixture)
    with pytest.raises(distribution.ResearchDistributionError, match="^distribution_binding_verification_failed$"):
        plan(fixture)


@pytest.mark.parametrize("mutation", [
    "missing_row", "extra_row", "duplicate_row", "row_hash", "internal_bytes", "missing_bytes", "extra_bytes",
    "internal_record_pin", "internal_schema", "identity_hash", "formula", "family", "pressure", "temperature",
    "state_material", "source_revision_pin", "source_capture_pin", "source_version", "source_work_unresolved",
    "source_mapping", "source_bytes",
])
def test_live_dependency_projection_and_bytes_cannot_be_relabelled(mutation):
    fixture = make_distribution()
    rows = fixture["rows"]
    by_table = {row["table"]: row for row in rows}
    entries = fixture["bindings"]["bindings"]
    internal = next(item for item in entries if item["artifact_kind"] == "rubric")
    document = next(row for row in rows if row["table"] == "evidence_artifacts"
                    and row["row_id"] == internal["root"]["evidence_artifact_id"])
    evidence = next(item for item in entries if item["artifact_kind"] == "evidence")
    if mutation == "missing_row": rows.remove(by_table["papers"])
    elif mutation == "extra_row":
        rows.append(synthetic_row("works", id=str(uuid5(NAMESPACE_URL, "extra-unused"))))
        rows.sort(key=lambda row: (row["table"], row["row_id"]))
    elif mutation == "duplicate_row": rows.append(deepcopy(rows[-1]))
    elif mutation == "row_hash": rows[0]["row_sha256"] = "f" * 64
    elif mutation == "internal_bytes": fixture["artifact_bytes"][internal["root"]["bytes_sha256"]] = b"not the descriptor"
    elif mutation == "missing_bytes": fixture["artifact_bytes"].pop(internal["root"]["bytes_sha256"])
    elif mutation == "extra_bytes": fixture["artifact_bytes"]["f" * 64] = b"undeclared"
    elif mutation == "internal_record_pin": internal["root"]["record_sha256"] = "f" * 64
    elif mutation == "internal_schema":
        document["data"]["schema_version"] = "pdf/1"
        reseal_row(document)
    elif mutation == "identity_hash":
        next(item for item in entries if item["artifact_kind"] == "material")["identity"]["row_sha256"] = "f" * 64
    elif mutation in {"formula", "family"}:
        by_table["materials"]["data"][mutation] = "different"
        reseal_row(by_table["materials"])
        next(item for item in entries if item["artifact_kind"] == "material")["identity"]["row_sha256"] = by_table["materials"]["row_sha256"]
    elif mutation in {"pressure", "temperature"}:
        field = "pressure_gpa" if mutation == "pressure" else "temperature_k"
        by_table["material_states"]["data"][field] = 12.0
        reseal_row(by_table["material_states"])
        next(item for item in entries if item["artifact_kind"] == "state")["identity"]["row_sha256"] = by_table["material_states"]["row_sha256"]
    elif mutation == "state_material":
        by_table["material_states"]["data"]["material_id"] = "different"
        reseal_row(by_table["material_states"])
    elif mutation == "source_revision_pin": evidence["root"]["source_revision_record_sha256"] = "f" * 64
    elif mutation == "source_capture_pin": evidence["root"]["capture_record_sha256"] = "f" * 64
    elif mutation in {"source_version", "source_work_unresolved"}:
        revision = by_table["source_revisions"]
        revision["data"]["provider_revision" if mutation == "source_version" else "work_id"] = "changed" if mutation == "source_version" else None
        reseal_row(revision)
        for item in entries:
            if item["artifact_kind"] == "evidence":
                item["root"]["source_revision_record_sha256"] = revision["data"]["record_sha256"]
    elif mutation == "source_mapping":
        by_table["paper_work_map"]["data"]["review_status"] = "pending"
        reseal_row(by_table["paper_work_map"])
    elif mutation == "source_bytes": fixture["artifact_bytes"][evidence["root"]["bytes_sha256"]] = b"wrong source"
    repin_bindings(fixture)
    with pytest.raises(distribution.ResearchDistributionError):
        distribution.verify_distribution_bindings(**fixture)


@pytest.mark.parametrize("where", ["bindings", "rows"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), "\ud800", object()])
def test_invalid_json_is_rejected_without_partial_inventory(where, invalid):
    fixture = make_distribution()
    fixture[where] = invalid
    with pytest.raises(distribution.ResearchDistributionError):
        distribution.verify_distribution_bindings(**fixture)


@pytest.mark.parametrize("limit", ["MAX_BINDINGS", "MAX_DEPENDENCIES", "MAX_BYTES", "MAX_NODES", "MAX_DEPTH"])
def test_private_resource_bounds_fail_closed(monkeypatch, limit):
    fixture = make_distribution()
    monkeypatch.setattr(distribution, limit, 1)
    with pytest.raises(distribution.ResearchDistributionError):
        distribution.verify_distribution_bindings(**fixture)


def test_required_public_bundle_cannot_be_swapped_even_when_individually_valid():
    fixture = make_distribution()
    fixture["release"]["id"] = "different"
    with pytest.raises(distribution.ResearchDistributionError):
        plan(fixture)
