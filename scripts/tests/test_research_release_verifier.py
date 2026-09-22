"""Synthetic offline adversaries; no database, network or approved data."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from services import research_release_manifest as contract
from services.research_release_spec import SPEC

from scripts import verify_research_release as wrapper


def uid(label):
    return str(uuid5(NAMESPACE_URL, f"synthetic-release:{label}"))


def row(table, label, **values):
    data = {}
    for field, declaration in SPEC[table]["fields"].items():
        kind = declaration["type"]
        data[field] = None if declaration["nullable"] else (
            {} if kind == "JSONB" else False if kind == "BOOLEAN" else
            0 if kind in {"INTEGER", "SMALLINT", "BIGINT", "FLOAT"} else
            [] if kind.startswith("ARRAY") else uid(f"{label}:{field}") if kind == "UUID" else
            "2026-09-07T01:00:00+00:00" if kind == "DATETIME" else
            "2026-09-07" if kind == "DATE" else "fixture"
        )
    identity = "paper_id" if table == "paper_work_map" else "id"
    data[identity] = uid(label) if SPEC[table]["fields"][identity]["type"] == "UUID" else label
    data.update(values)
    return {"table": table, "row_id": data[identity], "data": data, "row_sha256": contract.digest(data)}


def artifact(label, payload, *, kind="policy", **values):
    byte_hash = hashlib.sha256(payload).hexdigest()
    return row("evidence_artifacts", label, kind=kind, schema_version="fixture/1",
               bytes_sha256=byte_hash, hash_status="verified", record_sha256="0" * 64,
               access="restricted", **values), (byte_hash, payload)


def review(base, payloads):
    document = contract.processing_review_payload(base)
    review_row, byte_item = artifact("processing-review", contract.canonical(document), kind="review")
    review_row["data"].update(schema_version=contract.REVIEW_VERSION,
                               record_sha256=contract.digest(document),
                               metadata={"shadow_freeze_review": document})
    review_row["row_sha256"] = contract.digest(review_row["data"])
    payloads = {**payloads, byte_item[0]: byte_item[1]}
    manifest = contract.build_manifest(
        dataset_id=base["dataset_id"], rows=[*base["rows"], review_row],
        policy_artifact_ids=base["policy_artifact_ids"], source_roots=base["source_roots"],
        artifact_bytes=payloads, review_artifact_id=review_row["row_id"],
    )
    return manifest, payloads


def fixture(*, graph=False):
    task, task_bytes = artifact("task", b"synthetic task policy v1")
    registry, registry_bytes = artifact("registry", b"synthetic registry v1")
    payloads = dict((task_bytes, registry_bytes))
    source = row("source_snapshots", "source", schema_version="ml-foundation-v1")
    material = row("materials", "MgB2", formula="MgB2", formula_normalized="MgB2")
    claim = row("material_claims", "claim", material_id="MgB2", source_snapshot_id=source["row_id"],
                property_type="tc", value_relation="exact", value_kelvin=39.0,
                result_status="observed", validity_status="pending")
    dataset = row("ml_dataset_snapshots", "dataset", source_snapshot_id=source["row_id"], row_count=1)
    example = row("ml_examples", "example", dataset_snapshot_id=dataset["row_id"],
                  claim_id=claim["row_id"], material_id="MgB2")
    rows = [task, registry, source, material, claim, dataset, example]
    if graph:
        state = row("material_states", "state", material_id="MgB2", source_artifact_id=task["row_id"])
        event = row("research_events", "event", material_id="MgB2", state_id=state["row_id"], revision=1)
        claim["data"].update(event_id=event["row_id"], result_key="Tc", interpretation_revision=1)
        claim["row_sha256"] = contract.digest(claim["data"])
        prop = row("event_properties", "property", event_id=event["row_id"], property_key="band_gap",
                   registry_version="rv2/1", relation="exact", value=0.0, unit="eV")
        membership = row("snapshot_event_memberships", "membership", snapshot_id=source["row_id"],
                         event_id=event["row_id"], event_revision=1)
        rows.extend((state, event, prop, membership))
    base = contract.build_manifest(dataset_id=dataset["row_id"], rows=rows,
                                   policy_artifact_ids=[task["row_id"], registry["row_id"]],
                                   source_roots=[], artifact_bytes=payloads)
    return review(base, payloads)


def write_bundle(tmp_path, manifest, payloads):
    directory = tmp_path / "capsule"
    directory.mkdir()
    path = directory / "manifest.json"
    path.write_bytes(contract.canonical(manifest))
    for sha, payload in payloads.items():
        (directory / f"{sha}.bin").write_bytes(payload)
    return path


def selected(manifest, table):
    return next(item for item in manifest["rows"] if item["table"] == table)


def reseal(manifest):
    for item in manifest["rows"]:
        item["row_sha256"] = contract.digest(item["data"])
    manifest["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    return contract.digest(manifest)


def test_preview_and_final_integrity_never_grant_scientific_or_public_approval(tmp_path):
    manifest, payloads = fixture(graph=True)
    path = write_bundle(tmp_path, manifest, payloads)
    result = wrapper.verify_research_release(manifest_path=path, expected_manifest_sha256=contract.digest(manifest))
    assert result["integrity_verified"] is True
    assert result["scientific_acceptance"] is False
    assert result["public_release"] is False
    assert result["ml_training_approved"] is False
    assert result["reviewer_authority_authenticated"] is False
    assert result["database_completeness_independently_proven"] is False
    assert result["preview_sha256"] == contract.digest(contract.base_manifest(manifest))


@pytest.mark.parametrize("field", ["scientific_acceptance", "public_release", "ml_training_approved"])
@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_no_forged_boolean_approval(field, value):
    manifest, payloads = fixture()
    manifest[field] = value
    with pytest.raises(contract.ResearchReleaseVerificationError, match="not scientific"):
        contract.verify_manifest(manifest, artifact_bytes=payloads)


def test_preview_cannot_pass_final_verifier():
    manifest, payloads = fixture()
    base = contract.base_manifest(manifest)
    base_bytes = {item["sha256"]: payloads[item["sha256"]] for item in base["artifacts"]}
    with pytest.raises(contract.ResearchReleaseVerificationError, match="processing review required"):
        contract.verify_manifest(base, artifact_bytes=base_bytes)
    assert contract.verify_manifest(base, artifact_bytes=base_bytes, allow_preview=True)["integrity_verified"]


@pytest.mark.parametrize("table", ["material_claims", "materials", "source_snapshots", "material_states", "research_events"])
def test_missing_required_rows_fail_even_after_resealing(table):
    manifest, payloads = fixture(graph=True)
    manifest["rows"] = [item for item in manifest["rows"] if item["table"] != table]
    with pytest.raises(contract.ResearchReleaseVerificationError, match="missing dependency"):
        contract.verify_manifest(manifest, artifact_bytes=payloads, expected_manifest_sha256=reseal(manifest))


@pytest.mark.parametrize("mutation,match", [
    (lambda m: m["rows"].append(copy.deepcopy(m["rows"][0])), "duplicate"),
    (lambda m: m["rows"][0]["data"].pop("created_at"), "incomplete"),
    (lambda m: m["rows"][0]["data"].update(unknown_reference="invented"), "incomplete"),
    (lambda m: selected(m, "material_claims")["data"].update(value_kelvin=True), "typed"),
    (lambda m: selected(m, "snapshot_event_memberships")["data"].update(event_revision=2), "binding"),
    (lambda m: selected(m, "ml_examples")["data"].update(material_id="different"), "binding"),
    (lambda m: selected(m, "ml_dataset_snapshots")["data"].update(row_count=2), "count"),
    (lambda m: m["rows"].append(row("works", "unreachable")), "unreachable"),
])
def test_typed_exact_closure_adversaries(mutation, match):
    manifest, payloads = fixture(graph=True)
    mutation(manifest)
    with pytest.raises(contract.ResearchReleaseVerificationError, match=match):
        contract.verify_manifest(manifest, artifact_bytes=payloads, expected_manifest_sha256=reseal(manifest))


def test_policy_and_review_artifact_byte_streams_are_required():
    manifest, payloads = fixture()
    for key in payloads:
        with pytest.raises(contract.ResearchReleaseVerificationError, match="digest mismatch"):
            contract.verify_manifest(manifest, artifact_bytes={**payloads, key: b"changed"})
        missing = {sha: payload for sha, payload in payloads.items() if sha != key}
        with pytest.raises(contract.ResearchReleaseVerificationError, match="missing or undeclared"):
            contract.verify_manifest(manifest, artifact_bytes=missing)


def test_reviewed_source_occurrence_closure_requires_capture_and_exact_revision_bytes():
    manifest, payloads = fixture()
    base = contract.base_manifest(manifest)
    payloads = {item["sha256"]: payloads[item["sha256"]] for item in base["artifacts"]}
    paper = row("papers", "paper")
    work = row("works", "work")
    mapping = row("paper_work_map", "paper", work_id=work["row_id"], review_status="accepted")
    claim = selected(base, "material_claims")
    claim["data"].update(paper_id=paper["row_id"], work_id=work["row_id"])
    claim["row_sha256"] = contract.digest(claim["data"])
    captured = b"Synthetic versioned source bytes; not an experimental result"
    sha = hashlib.sha256(captured).hexdigest()
    payloads[sha] = captured
    revision = row("source_revisions", "v1", paper_id=paper["row_id"], work_id=work["row_id"])
    capture = row("source_captures", "capture", source_revision_id=revision["row_id"], bytes_sha256=sha)
    witness = row("claim_source_occurrences", "witness", claim_id=claim["row_id"], work_id=work["row_id"],
                  source_revision_id=revision["row_id"], capture_id=capture["row_id"],
                  locator={"page": 1}, binding_status="pending")
    rows = [*base["rows"], paper, work, mapping, revision, capture, witness]
    source_roots = [{"table": "claim_source_occurrences", "row_id": witness["row_id"]}]
    expanded = contract.build_manifest(dataset_id=base["dataset_id"], rows=rows,
                                       policy_artifact_ids=base["policy_artifact_ids"],
                                       source_roots=source_roots, artifact_bytes=payloads)
    final, payloads = review(expanded, payloads)
    assert contract.verify_manifest(final, artifact_bytes=payloads)["integrity_verified"]
    with pytest.raises(contract.ResearchReleaseVerificationError, match="byte digest mismatch"):
        contract.verify_manifest(final, artifact_bytes={**payloads, sha: b"changed source revision"})
    capture["data"]["source_revision_id"] = uid("wrong-version")
    reseal(final)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="missing dependency|binding mismatch"):
        contract.verify_manifest(final, artifact_bytes=payloads)


def test_same_event_can_retain_distinct_selected_snapshot_memberships():
    manifest, payloads = fixture(graph=True)
    base = contract.base_manifest(manifest)
    payloads = {item["sha256"]: payloads[item["sha256"]] for item in base["artifacts"]}
    original = selected(base, "snapshot_event_memberships")
    later_snapshot = row("source_snapshots", "later-snapshot")
    later_member = copy.deepcopy(original)
    later_member["row_id"] = later_member["data"]["id"] = uid("later-member")
    later_member["data"]["snapshot_id"] = later_snapshot["row_id"]
    later_member["row_sha256"] = contract.digest(later_member["data"])
    expanded = contract.build_manifest(
        dataset_id=base["dataset_id"], rows=[*base["rows"], later_snapshot, later_member],
        policy_artifact_ids=base["policy_artifact_ids"],
        source_roots=[{"table": "snapshot_event_memberships", "row_id": later_member["row_id"]}],
        artifact_bytes=payloads,
    )
    final, payloads = review(expanded, payloads)
    assert contract.verify_manifest(final, artifact_bytes=payloads)["integrity_verified"]
    memberships = [item for item in final["rows"] if item["table"] == "snapshot_event_memberships"]
    assert len(memberships) == 2
    assert len({item["data"]["event_id"] for item in memberships}) == 1
    assert len({item["data"]["snapshot_id"] for item in memberships}) == 2


def test_omitted_owned_member_after_reseal_still_breaks_pinned_processing_review():
    manifest, payloads = fixture(graph=True)
    manifest["rows"] = [item for item in manifest["rows"] if item["table"] != "snapshot_event_memberships"]
    reseal(manifest)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="preview mismatch"):
        contract.verify_manifest(manifest, artifact_bytes=payloads)


def test_actor_ids_are_opaque_and_user_rows_are_not_exportable():
    manifest, payloads = fixture()
    qc = row("claim_qc", "qc", claim_id=selected(manifest, "material_claims")["row_id"],
             reviewed_by=uid("reviewer"))
    base = contract.base_manifest(manifest)
    payloads = {item["sha256"]: payloads[item["sha256"]] for item in base["artifacts"]}
    expanded = contract.build_manifest(dataset_id=base["dataset_id"], rows=[*base["rows"], qc],
                                       policy_artifact_ids=base["policy_artifact_ids"],
                                       source_roots=[], artifact_bytes=payloads)
    final, payloads = review(expanded, payloads)
    assert contract.verify_manifest(final, artifact_bytes=payloads)["integrity_verified"]
    assert "users" not in contract.TABLE_FIELDS
    with pytest.raises(contract.ResearchReleaseVerificationError, match="unsupported closure table"):
        contract.row_reference("users", uid("reviewer"))


def test_rehashed_data_change_invalidates_independent_processing_review():
    manifest, payloads = fixture()
    selected(manifest, "material_claims")["data"]["value_kelvin"] = 42.0
    reseal(manifest)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="preview mismatch"):
        contract.verify_manifest(manifest, artifact_bytes=payloads)


def test_review_document_cannot_be_a_different_verified_byte_stream():
    manifest, payloads = fixture()
    review_row = next(item for item in manifest["rows"] if item["row_id"] == manifest["review_artifact_id"])
    old_sha = review_row["data"]["bytes_sha256"]
    replacement = b"I claim to approve this but do not contain the bound review document"
    new_sha = hashlib.sha256(replacement).hexdigest()
    review_row["data"]["bytes_sha256"] = new_sha
    payloads.pop(old_sha)
    payloads[new_sha] = replacement
    manifest["artifacts"] = sorted([
        {"sha256": key, "bytes": len(value), "path": f"{key}.bin"} for key, value in payloads.items()
    ], key=lambda item: item["sha256"])
    reseal(manifest)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="review bytes mismatch"):
        contract.verify_manifest(manifest, artifact_bytes=payloads)


def test_scientific_cycles_reject_but_owned_relational_backrefs_pass():
    manifest, payloads = fixture(graph=True)
    contract.verify_manifest(manifest, artifact_bytes=payloads)
    first = selected(manifest, "research_events")
    second = copy.deepcopy(first)
    second["row_id"] = second["data"]["id"] = uid("second-event")
    second["data"]["supersedes_id"] = first["row_id"]
    first["data"]["supersedes_id"] = second["row_id"]
    manifest["rows"].append(second)
    reseal(manifest)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="ancestry cycle"):
        contract.verify_manifest(manifest, artifact_bytes=payloads)


@pytest.mark.parametrize("length", [1, 2, 3, 10])
def test_exact_result_derivation_cycles_fail(length):
    manifest, payloads = fixture(graph=True)
    event = selected(manifest, "research_events")
    prop = selected(manifest, "event_properties")
    events = [event]
    props = [prop]
    for index in range(1, length):
        copied_event, copied_prop = copy.deepcopy(event), copy.deepcopy(prop)
        copied_event["row_id"] = copied_event["data"]["id"] = uid(f"event-{index}")
        copied_prop["row_id"] = copied_prop["data"]["id"] = uid(f"property-{index}")
        copied_prop["data"]["event_id"] = copied_event["row_id"]
        manifest["rows"].extend((copied_event, copied_prop))
        events.append(copied_event)
        props.append(copied_prop)
    for index in range(length):
        target = (index + 1) % length
        manifest["rows"].append(row("event_evidence", f"edge-{index}", event_id=events[index]["row_id"],
                                    input_event_id=events[target]["row_id"],
                                    input_property_id=props[target]["row_id"], link_type="derives_from"))
    reseal(manifest)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="scientific derivation cycle"):
        contract.verify_manifest(manifest, artifact_bytes=payloads)


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}', b'"\\ud800"'])
def test_strict_json_rejects_ambiguous_or_nonfinite_values(payload):
    with pytest.raises(contract.ResearchReleaseVerificationError):
        wrapper.strict_json(payload)


@pytest.mark.parametrize("change", ["manifest", "artifact", "extra", "missing", "symlink", "hardlink", "directory"])
def test_filesystem_integrity_failures(tmp_path, change):
    manifest, payloads = fixture()
    path = write_bundle(tmp_path, manifest, payloads)
    leaf = path.parent / f"{next(iter(payloads))}.bin"
    if change == "manifest":
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "artifact":
        leaf.write_bytes(b"tampered")
    elif change == "extra":
        (path.parent / "notes.txt").write_text("private")
    elif change == "missing":
        leaf.unlink()
    elif change == "symlink":
        original = leaf.read_bytes()
        leaf.unlink()
        target = tmp_path / "target.bin"
        target.write_bytes(original)
        leaf.symlink_to(target)
    elif change == "hardlink":
        os.link(leaf, tmp_path / "alias.bin")
    elif change == "directory":
        leaf.unlink()
        leaf.mkdir()
    with pytest.raises(contract.ResearchReleaseVerificationError):
        wrapper.verify_research_release(manifest_path=path, expected_manifest_sha256=contract.digest(manifest))


def test_symlink_ancestor_and_path_traversal_rejected(tmp_path):
    manifest, payloads = fixture()
    path = write_bundle(tmp_path, manifest, payloads)
    alias = tmp_path / "alias"
    alias.symlink_to(path.parent, target_is_directory=True)
    for candidate in (alias / "manifest.json", path.parent / ".." / "capsule" / "manifest.json"):
        with pytest.raises(contract.ResearchReleaseVerificationError):
            wrapper.verify_research_release(manifest_path=candidate, expected_manifest_sha256=contract.digest(manifest))


def test_end_of_verification_recapture_detects_replacement(tmp_path, monkeypatch):
    manifest, payloads = fixture()
    path = write_bundle(tmp_path, manifest, payloads)
    original = wrapper.verify_manifest

    def replace_after_verify(*args, **kwargs):
        result = original(*args, **kwargs)
        replacement = path.parent / "replacement"
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        return result

    monkeypatch.setattr(wrapper, "verify_manifest", replace_after_verify)
    with pytest.raises(contract.ResearchReleaseVerificationError, match="changed during verification"):
        wrapper.verify_research_release(manifest_path=path, expected_manifest_sha256=contract.digest(manifest))


def test_budget_limits_and_type_sensitive_hashes():
    assert contract.digest({"a": False}) != contract.digest({"a": 0})
    assert contract.digest({"a": 1}) != contract.digest({"a": 1.0})
    value = {}
    for _ in range(50):
        value = {"nested": value}
    with pytest.raises(contract.ResearchReleaseVerificationError, match="resource limit"):
        contract.canonical(value)
    manifest, payloads = fixture()
    manifest["rows"] = manifest["rows"] * 200
    with pytest.raises(contract.ResearchReleaseVerificationError, match="row limit"):
        contract.verify_manifest(manifest, artifact_bytes=payloads)


def test_cli_is_offline_and_prints_metadata_only(tmp_path):
    manifest, payloads = fixture()
    path = write_bundle(tmp_path, manifest, payloads)
    result = subprocess.run([sys.executable, str(ROOT / "scripts/verify_research_release.py"),
                             "--manifest", str(path), "--expected-manifest-sha256", contract.digest(manifest)],
                            capture_output=True, text=True, check=False, timeout=20)
    assert result.returncode == 0, result.stderr
    metadata = json.loads(result.stdout)
    assert metadata["integrity_verified"] is True
    assert "MgB2" not in result.stdout and "value_kelvin" not in result.stdout
    assert "sqlalchemy" not in wrapper.__dict__
