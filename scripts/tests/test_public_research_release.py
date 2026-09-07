"""Synthetic public-egress adversaries; no database, network or real grants."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from services import research_public_contract as public
from services import research_release_manifest as internal

from scripts import verify_public_research_release as wrapper
from scripts.tests.test_research_release_verifier import fixture, reseal, review, uid

CANARY = "PRIVATE-TEXT-REVIEWER-SECRET-DO-NOT-PUBLISH"


def sample(*, canaries=False):
    manifest, payloads = fixture(graph=True)
    if canaries:
        base = internal.base_manifest(manifest)
        for row in base["rows"]:
            data = row["data"]
            for field in ("raw_record", "metadata", "conditions", "context"):
                if field in data:
                    data[field] = {"private": [{"unknown": {"text": CANARY,
                                                         "uri": "https://private.invalid/secret",
                                                         "reviewer_id": CANARY}}]}
            if "uri" in data:
                data["uri"] = f"file:///private/{CANARY}"
        reseal(base)
        byte_subset = {item["sha256"]: payloads[item["sha256"]] for item in base["artifacts"]}
        manifest, payloads = review(base, byte_subset)
    permissions = [{"table": row["table"], "row_id": row["row_id"], "row_sha256": row["row_sha256"],
                    "permission_id": uid(f"metadata-permission:{row['table']}:{row['row_id']}"),
                    "permission_sha256": internal.digest({"synthetic_permission": row["row_sha256"]}),
                    "scope": "metadata_only", "license_code": "permission-on-file"}
                   for row in manifest["rows"]]
    return manifest, payloads, permissions


def build(manifest, payloads, permissions):
    return public.build_public_document(manifest=manifest, expected_capsule_sha256=internal.digest(manifest),
                                        permissions=permissions, artifact_bytes=payloads)


def body():
    return build(*sample())


def verify(document):
    return public.verify_public_document(document, expected_public_sha256=internal.digest(document))


def write(tmp_path, payload):
    directory = tmp_path / "public"
    directory.mkdir()
    path = directory / "public-manifest.json"
    path.write_bytes(payload)
    return path.resolve()


def test_actual_capsule_and_recursive_permission_receipts_produce_only_metadata():
    manifest, payloads, permissions = sample(canaries=True)
    before = copy.deepcopy((manifest, payloads, permissions))
    document = build(manifest, payloads, permissions)
    encoded = internal.canonical(document)
    assert CANARY.encode() not in encoded
    for forbidden in (b"https://", b"file://", b'"raw_record"', b'"conditions"', b'"value_kelvin"'):
        assert forbidden not in encoded
    assert document["capsule_sha256"] == internal.digest(manifest)
    assert len(document["objects"]) == len(manifest["rows"])
    assert sum(item["object_count"] for item in document["counts"]) == len(manifest["rows"])
    assert document["exclusions"] == public.EXCLUSIONS
    assert (manifest, payloads, permissions) == before
    for row in manifest["rows"]:
        identifier = public.public_object_sha256(capsule_sha256=internal.digest(manifest),
                                                 table=row["table"], row_id=row["row_id"],
                                                 row_sha256=row["row_sha256"])
        assert any(item["object_sha256"] == identifier for item in document["objects"])
        assert not any("row_id" in item or "row_sha256" in item for item in document["objects"])


def test_deterministic_projection_and_reordered_input_permissions():
    manifest, payloads, permissions = sample()
    assert build(manifest, payloads, permissions) == build(manifest, payloads, list(reversed(permissions)))


def test_offline_verification_is_not_authentication_or_live_admission():
    result = verify(body())
    assert result["integrity_verified"] is True
    assert result["scope"] == "metadata_only"
    for field in ("permission_authority_authenticated", "capsule_integrity_rechecked",
                  "current_public_availability_rechecked", "scientific_acceptance", "ml_training_approved"):
        assert result[field] is False


@pytest.mark.parametrize("table", ["evidence_artifacts", "material_claims", "material_states", "materials",
                                   "research_events", "event_properties", "snapshot_event_memberships",
                                   "source_snapshots", "ml_dataset_snapshots", "ml_examples"])
def test_every_transitive_object_needs_a_grant_even_when_its_payload_is_excluded(table):
    manifest, payloads, permissions = sample()
    permissions = [item for item in permissions if item["table"] != table]
    with pytest.raises(public.PublicResearchVerificationError, match="missing recursive"):
        build(manifest, payloads, permissions)


@pytest.mark.parametrize("license_code", [None, "", "unknown", "CC-BY", "arxiv", "public", ["CC0-1.0"]])
def test_unknown_licensing_cannot_be_inferred_from_source_or_resealed(license_code):
    manifest, payloads, permissions = sample()
    permissions[0]["license_code"] = license_code
    with pytest.raises(public.PublicResearchVerificationError, match="license"):
        build(manifest, payloads, permissions)


@pytest.mark.parametrize("license_code", sorted(public.LICENSE_CODES))
def test_explicit_supported_reviewed_license_codes_are_not_legal_proofs(license_code):
    manifest, payloads, permissions = sample()
    permissions[0]["license_code"] = license_code
    assert verify(build(manifest, payloads, permissions))["permission_authority_authenticated"] is False


@pytest.mark.parametrize("scope", [None, "excluded", "unknown", "structured_results", "public", True])
def test_other_scopes_require_a_new_versioned_projection(scope):
    manifest, payloads, permissions = sample()
    permissions[0]["scope"] = scope
    with pytest.raises(public.PublicResearchVerificationError, match="metadata permission"):
        build(manifest, payloads, permissions)


@pytest.mark.parametrize("change,match", [
    (lambda grants: grants[0].update(approved=True), "permission fields"),
    (lambda grants: grants[0].pop("permission_sha256"), "permission fields"),
    (lambda grants: grants[0].update(row_sha256="0" * 64), "stale"),
    (lambda grants: grants[0].update(row_id="unrelated"), "extra or duplicate"),
    (lambda grants: grants[0].update(table="users"), "object binding"),
    (lambda grants: grants[0].update(permission_id="reviewer@example.invalid"), "identifier"),
    (lambda grants: grants[1].update(permission_id=grants[0]["permission_id"]), "reused"),
    (lambda grants: grants[0].update(permission_sha256="A" * 64), "receipt digest"),
    (lambda grants: grants.append(copy.deepcopy(grants[0])), "extra or duplicate"),
])
def test_permission_receipts_are_exact_row_bound_inputs(change, match):
    manifest, payloads, permissions = sample()
    change(permissions)
    with pytest.raises(public.PublicResearchVerificationError, match=match):
        build(manifest, payloads, permissions)


def test_permission_inventory_is_bounded_before_processing():
    manifest, payloads, permissions = sample()
    with pytest.raises(public.PublicResearchVerificationError, match="inventory limit"):
        build(manifest, payloads, permissions * (public.LIMITS["objects"] + 1))


def test_actual_internal_artifact_bytes_are_rechecked_even_for_metadata_only_projection():
    manifest, payloads, permissions = sample()
    key = next(iter(payloads))
    with pytest.raises(public.PublicResearchVerificationError, match="capsule"):
        build(manifest, {**payloads, key: b"tampered actual file"}, permissions)


def test_capsule_expected_digest_cannot_be_self_declared_by_an_extra_permission_field():
    manifest, payloads, permissions = sample()
    with pytest.raises(public.PublicResearchVerificationError, match="capsule"):
        public.build_public_document(manifest=manifest, expected_capsule_sha256="0" * 64,
                                     permissions=permissions, artifact_bytes=payloads)


@pytest.mark.parametrize("change,match", [
    (lambda doc: doc.update(records=[{"nested": CANARY}]), "document fields"),
    (lambda doc: doc["objects"][0].update(metadata={"nested": [CANARY]}), "nested public object"),
    (lambda doc: doc["objects"][0].update(uri="https://private.invalid"), "nested public object"),
    (lambda doc: doc["counts"][0].update(review={"secret": CANARY}), "nested counts"),
    (lambda doc: doc["exclusions"].update(private={"text": CANARY}), "exclusions"),
    (lambda doc: doc["limits"].update(private={"text": CANARY}), "limits"),
    (lambda doc: doc["objects"][0].update(license_code={"nested": CANARY}), "license"),
    (lambda doc: doc["objects"][0].update(permission_id=CANARY), "identifier"),
    (lambda doc: doc["objects"][0].update(scope="structured_results"), "scope"),
    (lambda doc: doc["objects"][0].update(table="private_table"), "table"),
    (lambda doc: doc["objects"][0].update(object_sha256="not-a-hash"), "object digest"),
    (lambda doc: doc["objects"][0].update(permission_sha256="unknown"), "receipt digest"),
    (lambda doc: doc["objects"].append(copy.deepcopy(doc["objects"][0])), "duplicate"),
    (lambda doc: doc["objects"][1].update(permission_id=doc["objects"][0]["permission_id"]), "reused"),
    (lambda doc: doc["objects"].reverse(), "ordered"),
    (lambda doc: doc["counts"][0].update(object_count=True), "nested counts"),
    (lambda doc: doc["counts"].pop(), "nested counts"),
    (lambda doc: doc["counts"].reverse(), "nested counts"),
    (lambda doc: doc.update(dataset_object_sha256="0" * 64), "dataset object"),
    (lambda doc: doc.update(version="research-public-metadata/2.0.0"), "version"),
    (lambda doc: doc.update(scope="structured_results"), "scope"),
    (lambda doc: doc["exclusions"].update(scientific_values=False), "exclusions"),
])
def test_unknown_nested_egress_cannot_be_checksum_washed(change, match):
    document = body()
    change(document)
    with pytest.raises(public.PublicResearchVerificationError, match=match):
        verify(document)  # Deliberately reseal: the field policy must still fail.


@pytest.mark.parametrize("field", ["scientific_acceptance", "ml_training_approved"])
@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_false_approval_flags_are_exact_booleans(field, value):
    document = body()
    document[field] = value
    with pytest.raises(public.PublicResearchVerificationError, match="approval"):
        verify(document)


@pytest.mark.parametrize("expected", [None, "", "A" * 64, "0" * 64, True])
def test_independent_expected_public_hash_is_required(expected):
    with pytest.raises(public.PublicResearchVerificationError, match="pinned"):
        public.verify_public_document(body(), expected_public_sha256=expected)


def test_public_byte_limit_and_resource_bounds():
    document = body()
    document["objects"] *= public.LIMITS["objects"] + 1
    with pytest.raises(public.PublicResearchVerificationError):
        verify(document)
    document = body()
    document["objects"][0]["license_code"] = "x" * (public.LIMITS["file_bytes"] + 1)
    with pytest.raises(public.PublicResearchVerificationError, match="byte limit"):
        verify(document)


def test_public_object_identifier_is_scoped_to_exact_capsule():
    first = public.public_object_sha256(capsule_sha256="1" * 64, table="materials", row_id="MgB2",
                                       row_sha256="2" * 64)
    second = public.public_object_sha256(capsule_sha256="3" * 64, table="materials", row_id="MgB2",
                                        row_sha256="2" * 64)
    assert first != second


def test_safe_offline_file_and_cli(tmp_path):
    document = body()
    path = write(tmp_path, internal.canonical(document))
    digest = internal.digest(document)
    result = wrapper.verify_public_research_release(manifest_path=path, expected_public_sha256=digest)
    assert result == verify(document)
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/verify_public_research_release.py"),
                                "--manifest", str(path), "--expected-public-sha256", digest],
                               capture_output=True, text=True, check=False, timeout=20)
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == result


@pytest.mark.parametrize("payload,match", [
    (b'{"version":"a","version":"b"}', "duplicate"),
    (b'{"value":NaN}', "nonfinite"),
    (b'{"value":1e999}', "excessive JSON"),
    (b'{"value":"\\ud800"}', "excessive JSON"),
    (b"[" * 60 + b"0" + b"]" * 60, "excessive JSON"),
    (b"\xff", "excessive JSON"),
])
def test_offline_strict_json_rejects_malformed_resealed_bytes(tmp_path, payload, match):
    path = write(tmp_path, payload)
    with pytest.raises(public.PublicResearchVerificationError, match=match):
        wrapper.verify_public_research_release(manifest_path=path,
                                               expected_public_sha256=hashlib.sha256(payload).hexdigest())


def test_offline_canonical_bytes_required_even_when_noncanonical_bytes_hash_matches(tmp_path):
    payload = json.dumps(body(), indent=2).encode()
    path = write(tmp_path, payload)
    with pytest.raises(public.PublicResearchVerificationError, match="canonical"):
        wrapper.verify_public_research_release(manifest_path=path,
                                               expected_public_sha256=hashlib.sha256(payload).hexdigest())


@pytest.mark.parametrize("kind", ["leaf_symlink", "ancestor_symlink", "hardlink", "fifo", "directory",
                                  "relative", "traversal", "filename"])
def test_offline_path_and_file_alias_adversaries(tmp_path, kind):
    document = body()
    path = write(tmp_path, internal.canonical(document))
    digest = internal.digest(document)
    if kind == "leaf_symlink":
        target = path.with_name("original.json")
        path.rename(target)
        path.symlink_to(target)
    elif kind == "ancestor_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(path.parent, target_is_directory=True)
        path = alias / path.name
    elif kind == "hardlink":
        os.link(path, path.with_name("alias.json"))
    elif kind in {"fifo", "directory"}:
        path.unlink()
        os.mkfifo(path) if kind == "fifo" else path.mkdir()
    elif kind == "relative":
        path = Path("public-manifest.json")
    elif kind == "traversal":
        path = path.parent / ".." / "public" / path.name
    elif kind == "filename":
        path = path.with_name("private-manifest.json")
    with pytest.raises(public.PublicResearchVerificationError):
        wrapper.verify_public_research_release(manifest_path=path, expected_public_sha256=digest)


def test_offline_oversized_file_rejected_before_json(tmp_path):
    path = write(tmp_path, b"x" * (public.LIMITS["file_bytes"] + 1))
    with pytest.raises(public.PublicResearchVerificationError, match="byte limit"):
        wrapper.verify_public_research_release(manifest_path=path, expected_public_sha256="0" * 64)


def test_offline_detects_file_replacement_between_captures(tmp_path, monkeypatch):
    document = body()
    path = write(tmp_path, internal.canonical(document))
    original = wrapper._capture
    calls = 0

    def replaced(selected):
        nonlocal calls
        calls += 1
        payload, signature = original(selected)
        return (payload, signature) if calls == 1 else (payload, (*signature[:-1], signature[-1] + 1))

    monkeypatch.setattr(wrapper, "_capture", replaced)
    with pytest.raises(public.PublicResearchVerificationError, match="changed during verification"):
        wrapper.verify_public_research_release(manifest_path=path,
                                               expected_public_sha256=internal.digest(document))


def test_unrelated_private_file_is_not_read_or_followed(tmp_path):
    document = body()
    path = write(tmp_path, internal.canonical(document))
    (path.parent / "private-source.bin").symlink_to("/no-such-private-secret")
    assert wrapper.verify_public_research_release(manifest_path=path,
                                                  expected_public_sha256=internal.digest(document))["integrity_verified"]
