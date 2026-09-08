"""Synthetic public-bundle integrity, not scientific review or source licensing."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from services import priority_public_bundle as public
from services.priority_release_cache import clear_release_cache
from services.priority_releases import PriorityRelease
from services.research_priority import Assessment, action_specification, canonical_json, digest
from tests.test_research_priority import release_payload

CANARY = "PRIVATE-NESTED-TEXT-REVIEWER-CREDENTIAL-DO-NOT-PUBLISH"


def reseal_public_release(value):
    """Synthetic fixture-only reference rebuild; creates no genuine approval."""
    value = deepcopy(value)
    artifacts = {item["id"]: item for item in value["artifacts"]}
    def seal(item):
        item["sha256"] = digest({key: content for key, content in item.items() if key != "sha256"})
        return {"id": item["id"], "sha256": item["sha256"]}
    for item in value["artifacts"]:
        seal(item)
    for entry in value["assessments"]:
        a = entry["assessment"]
        requirements = a["action_requirements"]
        for key in ("material", "state", "profile_assignment"):
            a[key] = seal(artifacts[a[key]["id"]])
        requirements["template_review"] = seal(artifacts[requirements["template_review"]["id"]])
        requirements["template_ref"] = seal(artifacts[requirements["template_ref"]["id"]])
        action = artifacts[a["action"]["id"]]
        action["content"]["action_requirements_hash"] = digest(requirements)
        action["content"]["assessment_action_hash"] = digest(action_specification(Assessment.model_validate(a)))
        a["action"] = seal(action)
        review = artifacts[entry["review"]["id"]]
        review["content"]["assessment_hash"] = digest(a)
        entry["review"] = seal(review)
    value["manifest_sha256"] = digest({key: item for key, item in value.items() if key != "manifest_sha256"})
    return value


def public_release_payload():
    """Actual v1.2 contract, with clearly synthetic opaque public identities."""
    value = release_payload()
    for item in value["artifacts"]:
        if item["kind"] in {"review", "template_review"}:
            item["content"]["reviewer_id"] = "public-reviewer:" + digest({"synthetic_public_fixture": item["id"]})[:32]
    return reseal_public_release(value)


def disclosure_for(value):
    return {"version": public.DISCLOSURE_VERSION, "release_manifest_sha256": value["manifest_sha256"],
        "scope": "complete_rps_release", "free_text_review": "declared_cleared_for_publication",
        "review_attestations": [{"artifact_id": item["id"], "artifact_sha256": item["sha256"],
            "public_reviewer_id": item["content"]["reviewer_id"],
            "attestation_kind": "public_review_attestation" if item["content"]["reviewer_id"].startswith("public-attestation:")
                else "consented_public_pseudonym",
            "consent_reference_sha256": digest({"synthetic_test_not_actual_consent": item["sha256"]})}
            for item in sorted(value["artifacts"], key=lambda item: item["id"]) if item["kind"] in {"review", "template_review"}]}


def public_bundle_payload():
    value = public_release_payload()
    return public.build_public_bundle(value, disclosure=disclosure_for(value))


def verify(value):
    return public.verify_public_bundle(value, expected_bundle_sha256=value["bundle_sha256"])


def reseal(value):
    value["bundle_sha256"] = public.bundle_sha256(value)
    return value


def test_complete_actual_policy_release_rows_recompute_without_authority():
    release = public_release_payload()
    before = deepcopy(release)
    document = public.build_public_bundle(release, disclosure=disclosure_for(release))
    result = verify(document)
    assert release == before == document["release"]
    assert document["rows"] == PriorityRelease.model_validate(release).rows()
    assert document["rows"][0]["result"]["score_display"] == 7100
    assert result["integrity_verified"] and result["scoring_recomputed"] and result["recursive_field_contract_verified"]
    assert result["assessment_count"] == 1 and result["artifact_count"] == len(release["artifacts"])
    for key in ("reviewer_identity_authenticated", "source_rights_verified", "current_public_authorization_checked",
                "scientific_acceptance", "empirical_calibration_verified"):
        assert result[key] is False
    assert public.verifier_source_sha256() == document["verifier"]["source_sha256"]
    assert '"reviewer_id"' not in canonical_json(result)


def test_preparation_copies_inputs_and_never_rewrites_private_legacy_release():
    private = release_payload()
    original = deepcopy(private)
    with pytest.raises(public.PublicPriorityBundleError):
        public.build_public_bundle(private, disclosure=disclosure_for(private))
    assert private == original
    value = public_release_payload()
    disclosure = disclosure_for(value)
    bundle = public.build_public_bundle(value, disclosure=disclosure)
    value["artifacts"].clear()
    disclosure["review_attestations"].clear()
    assert verify(bundle)["integrity_verified"]


@pytest.mark.parametrize("kind", ["material", "review", "profile_assignment", "state", "action", "evidence", "rubric", "action_template", "template_review"])
def test_every_artifact_kind_rejects_nested_unknown_canary_even_after_hashes_rebuilt(kind):
    value = public_release_payload()
    item = next(item for item in value["artifacts"] if item["kind"] == kind)
    item["content"]["private_payload"] = {"nested": [{"raw_text": CANARY, "reviewer_email": "private@example.org"}]}
    # All pre-existing parent hashes are rebuilt where possible. Closed field
    # rejection is independent from whether a caller can recompute checksums.
    try:
        value = reseal_public_release(value)
    except ValueError:
        pass  # a closed action-template subtree can be refused even earlier
    with pytest.raises(public.PublicPriorityBundleError) as error:
        public.build_public_bundle(value, disclosure=disclosure_for(value))
    assert CANARY not in str(error.value)


@pytest.mark.parametrize("target", ["bundle", "disclosure", "attestation", "verifier", "row", "campaign", "assessment", "dimension", "cost", "prerequisite", "dependency", "resource"])
def test_recursive_unknown_fields_cannot_be_resealed_into_publication(target):
    value = public_bundle_payload()
    assessment = value["release"]["assessments"][0]["assessment"]
    target_object = {"bundle": value, "disclosure": value["disclosure"],
        "attestation": value["disclosure"]["review_attestations"][0], "verifier": value["verifier"],
        "row": value["rows"][0], "campaign": value["release"]["campaign"], "assessment": assessment,
        "dimension": assessment["dimensions"]["stability"], "cost": assessment["costs"][0],
        "prerequisite": assessment["action_requirements"]["prerequisites"][0],
        "dependency": assessment["action_requirements"]["dependencies"][0],
        "resource": assessment["action_requirements"]["resources"][0]}[target]
    target_object["private"] = {"source_context": CANARY}
    with pytest.raises(public.PublicPriorityBundleError) as error:
        verify(reseal(value))
    assert CANARY not in str(error.value)


@pytest.mark.parametrize("field", ["score_raw", "score_display", "score_upper", "p_lower", "p_upper", "g_lower", "g_upper",
    "a_lower", "a_upper", "affordability_lower", "affordability_upper", "assessed_weight", "eligibility", "effective_weights", "contributions"])
def test_every_recomputed_value_is_compared_not_only_display_score(field):
    value = public_bundle_payload()
    value["rows"][0]["result"][field] = None
    with pytest.raises(public.PublicPriorityBundleError, match="score rows"):
        verify(reseal(value))


@pytest.mark.parametrize("mutation", ["policy", "missing_policy", "missing_artifact", "missing_assessment", "missing_rows", "row_order",
    "wrong_release", "wrong_bundle", "verifier_version", "verifier_source", "unknown_version"])
def test_changed_or_missing_transitive_inputs_and_verifier_fail_closed(mutation):
    value = public_bundle_payload()
    if mutation == "policy": value["policy"]["offset"] += 1
    elif mutation == "missing_policy": value["policy"].pop("profiles_percent")
    elif mutation == "missing_artifact": value["release"]["artifacts"].pop(0)
    elif mutation == "missing_assessment": value["release"]["assessments"].clear()
    elif mutation == "missing_rows": value["rows"].clear()
    elif mutation == "row_order": value["rows"].append(deepcopy(value["rows"][0]))
    elif mutation == "wrong_release": value["release"]["manifest_sha256"] = "0" * 64
    elif mutation == "wrong_bundle": value["bundle_sha256"] = "0" * 64
    elif mutation == "verifier_version": value["verifier"]["version"] = "future"
    elif mutation == "verifier_source": value["verifier"]["source_sha256"] = "0" * 64
    else: value["schema_version"] = "future"
    if mutation != "wrong_bundle": reseal(value)
    with pytest.raises(public.PublicPriorityBundleError): verify(value)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "hash", "identity", "consent", "kind", "release", "scope", "free_text"])
def test_every_declared_review_consent_is_exactly_bound_without_authentication(mutation):
    value = public_bundle_payload()
    disclosure = value["disclosure"]
    entries = disclosure["review_attestations"]
    if mutation == "missing": entries.pop()
    elif mutation == "duplicate": entries.append(deepcopy(entries[0]))
    elif mutation == "extra": entries[0]["artifact_id"] = "unrelated"
    elif mutation == "hash": entries[0]["artifact_sha256"] = "0" * 64
    elif mutation == "identity": entries[0]["public_reviewer_id"] = "private@example.org"
    elif mutation == "consent": entries[0]["consent_reference_sha256"] = None
    elif mutation == "kind": entries[0]["attestation_kind"] = "assumed_public"
    elif mutation == "release": disclosure["release_manifest_sha256"] = "0" * 64
    elif mutation == "scope": disclosure["scope"] = "metadata_only"
    else: disclosure["free_text_review"] = "not_reviewed"
    with pytest.raises(public.PublicPriorityBundleError): verify(reseal(value))


def test_public_attestation_identifiers_are_supported_without_claiming_people_authentication():
    value = public_release_payload()
    for item in value["artifacts"]:
        if item["kind"] in {"review", "template_review"}:
            item["content"]["reviewer_id"] = item["content"]["reviewer_id"].replace("public-reviewer:", "public-attestation:")
    value = reseal_public_release(value)
    result = verify(public.build_public_bundle(value, disclosure=disclosure_for(value)))
    assert result["reviewer_identity_authenticated"] is False


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'{"a":NaN}', b'{"a":Infinity}',
    b'{"a":-Infinity}', b'{"a":1e999}', b'\xff', b'[[[[[[[', b'{"a": "\\ud800"}'])
def test_strict_json_rejects_duplicate_nonfinite_invalid_bytes(payload):
    with pytest.raises(public.PublicPriorityBundleError): public.strict_json(payload)


def test_depth_node_string_and_total_byte_bounds(monkeypatch):
    for limit, amount in (("MAX_DEPTH", 1), ("MAX_NODES", 5), ("MAX_STRING_BYTES", 10), ("MAX_BYTES", 50)):
        value = public_bundle_payload()
        with monkeypatch.context() as patch:
            patch.setattr(public, limit, amount)
            with pytest.raises(public.PublicPriorityBundleError): verify(value)


def test_safe_file_receipt_is_immutable_and_nested_access_is_detached(tmp_path):
    clear_release_cache()
    value = public_bundle_payload()
    path = tmp_path / (value["release"]["id"] + ".public.json")
    path.write_text(canonical_json(value), encoding="utf-8")
    receipt = public.read_public_bundle(tmp_path, value["release"]["id"], value["bundle_sha256"],
        expected_release_sha256=value["release"]["manifest_sha256"])
    assert receipt.canonical_bytes == canonical_json(value).encode()
    receipt.document["rows"].clear()
    receipt.metadata.clear()
    assert len(receipt.document["rows"]) == 1 and receipt.metadata["scoring_recomputed"]
    with pytest.raises(FrozenInstanceError): receipt.release_id = "changed"
    with pytest.raises(public.PublicPriorityBundleError):
        public.read_public_bundle(tmp_path, value["release"]["id"], value["bundle_sha256"], expected_release_sha256="0" * 64)
    with pytest.raises(public.PublicPriorityBundleError):
        public.read_public_bundle(tmp_path, "../unsafe", value["bundle_sha256"])


def test_whitespace_or_symlink_file_is_not_a_canonical_public_package(tmp_path):
    clear_release_cache()
    value = public_bundle_payload()
    path = tmp_path / (value["release"]["id"] + ".public.json")
    path.write_text(canonical_json(value) + "\n")
    with pytest.raises(public.PublicPriorityBundleError):
        public.read_public_bundle(tmp_path, value["release"]["id"], value["bundle_sha256"])
    target = tmp_path / "target.json"
    target.write_text(canonical_json(value))
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(public.PublicPriorityBundleError):
        public.read_public_bundle(tmp_path, value["release"]["id"], value["bundle_sha256"])


@pytest.mark.parametrize("name", list(public._SOURCE_FILES))
def test_every_actual_verifier_contract_cache_and_cli_source_is_digest_bound(monkeypatch, name):
    value = public_bundle_payload()
    original = Path.read_bytes
    def changed(path):
        result = original(path)
        return result + b"\n# synthetic changed installed verifier\n" if path.name == name else result
    monkeypatch.setattr(Path, "read_bytes", changed)
    assert public.verifier_source_sha256() != value["verifier"]["source_sha256"]
    with pytest.raises(public.PublicPriorityBundleError, match="source digest"):
        verify(value)


@pytest.mark.parametrize("identifier", [".public-test", ":public-test", "-public-test", ".."])
def test_every_existing_release_identifier_is_safe_as_a_suffixed_leaf(tmp_path, identifier):
    value = public_release_payload()
    value["id"] = identifier
    value = reseal_public_release(value)
    document = public.build_public_bundle(value, disclosure=disclosure_for(value))
    (tmp_path / (identifier + ".public.json")).write_text(canonical_json(document))
    receipt = public.read_public_bundle(tmp_path, identifier, document["bundle_sha256"])
    assert receipt.release_id == identifier


def test_exact_approved_bytes_work_through_explicitly_configured_parent_symlink(tmp_path):
    # The configured directory is trusted administration, not an ownership
    # attestation or an anti-hostile-sysadmin filesystem sandbox.
    value = public_bundle_payload()
    directory = tmp_path / "source"
    directory.mkdir()
    alias = tmp_path / "configured"
    alias.symlink_to(directory, target_is_directory=True)
    (directory / (value["release"]["id"] + ".public.json")).write_text(canonical_json(value))
    receipt = public.read_public_bundle(alias, value["release"]["id"], value["bundle_sha256"])
    assert receipt.bundle_sha256 == value["bundle_sha256"]


def test_credential_bearing_evidence_url_is_refused_even_in_an_unreferenced_valid_artifact():
    value = public_release_payload()
    source = deepcopy(next(item for item in value["artifacts"] if item["kind"] == "evidence"))
    source["id"] = "unreferenced-public-source"
    source["content"]["url"] = "https://private:secret@example.org/source"
    value["artifacts"].append(source)
    value = reseal_public_release(value)
    # Old release permits this URL; the public envelope must not.
    PriorityRelease.model_validate(value)
    with pytest.raises(public.PublicPriorityBundleError, match="credential-bearing"):
        public.build_public_bundle(value, disclosure=disclosure_for(value))
