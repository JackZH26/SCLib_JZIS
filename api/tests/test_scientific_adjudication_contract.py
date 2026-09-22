"""Closed protocol tests; source text can never choose review authority."""
from copy import deepcopy
from uuid import uuid4

import pytest

from services import scientific_adjudication_contract as contract
from services.research_release_manifest import canonical


def request():
    profile = next(iter(contract.PROFILES))
    item = {"decision_id": str(uuid4()), "subject_id": str(uuid4()), "property_id": str(uuid4()),
        "scope": contract.PROFILES[profile][0], "profile_version": profile,
        "expected_subject_sha256": "a" * 64, "expected_previous_decision_id": None,
        "expected_impact_sha256": "b" * 64, "decision": "accept", "reason_code": "evidence_and_scope_match",
        "rationale": "Synthetic private rationale, not a real review.", "proposition": contract.PROFILES[profile][1],
        "limitations": list(contract.LIMITATIONS), "checks": {key: "satisfied" for key in contract.CHECKS},
        "evidence_refs": [{"artifact_id": str(uuid4()), "bytes_sha256": "c" * 64}],
        "source_inspection_attested": True, "resolves_decision_id": None, "extraction_decision_id": None}
    return {"version": contract.VERSION, "request_key": "synthetic-review:one", "items": [item]}


def test_python_and_sql_closed_profile_constants_match():
    from models import scientific_adjudication_v1 as model
    assert model.REQUEST_VERSION == contract.VERSION
    assert model.PROFILES == contract.PROFILES
    assert model.LIMITATIONS == contract.LIMITATIONS


def test_request_is_detached_and_does_not_silently_normalize_human_text():
    value = request()
    value["items"][0]["rationale"] = "  这是用于验证界面保存原文的合成说明，不是真正的科学审批。\nΔω = −0.1 THz.  "
    copied = contract.validate_request(value)
    assert copied == value
    value["items"][0]["checks"]["source_match"] = "unresolved"
    assert copied["items"][0]["checks"]["source_match"] == "satisfied"


@pytest.mark.parametrize("field,value", [
    ("decision_id", "NOT-A-UUID"), ("subject_id", None), ("property_id", 5),
    ("expected_previous_decision_id", ""), ("expected_subject_sha256", "A" * 64),
    ("expected_impact_sha256", 7), ("profile_version", "universal-approval/1"),
    ("scope", "material"), ("proposition", "full_zone_dynamical_stability"),
    ("limitations", []), ("limitations", list(reversed(contract.LIMITATIONS))),
    ("decision", "approve"), ("reason_code", "scientific_concern"),
    ("rationale", "short"), ("rationale", " " * 30), ("rationale", "x" * 2001),
    ("rationale", "long enough but invalid\x00text"), ("rationale", "x" * 20 + "\x7f"),
    ("checks", {key: None for key in contract.CHECKS}),
    ("source_inspection_attested", 1), ("source_inspection_attested", False),
    ("evidence_refs", []), ("extraction_decision_id", str(uuid4())),
    ("resolves_decision_id", str(uuid4())),
])
def test_wrong_types_missing_scope_limits_and_implicit_acceptance_are_rejected(field, value):
    body = request()
    body["items"][0][field] = value
    with pytest.raises(contract.ScientificAdjudicationError):
        contract.validate_request(body)


@pytest.mark.parametrize("where", ["top", "item", "check", "evidence"])
def test_unknown_keys_cannot_broaden_authority(where):
    body = request()
    target = {"top": body, "item": body["items"][0], "check": body["items"][0]["checks"],
              "evidence": body["items"][0]["evidence_refs"][0]}[where]
    target["actor_user_id"] = "forged-reviewer"
    with pytest.raises(contract.ScientificAdjudicationError):
        contract.validate_request(body)


@pytest.mark.parametrize("key", ["", "x/y", " ../review", "é", "/all", "x" * 161, "key?query=1", "key#fragment"])
def test_request_key_is_bounded_safe_for_exact_recovery_path(key):
    body = request()
    body["request_key"] = key
    with pytest.raises(contract.ScientificAdjudicationError):
        contract.validate_request(body)


@pytest.mark.parametrize("body", [b"", b"{}" * 65537, b'{"key":1,"key":2}', b'{"key":NaN}',
                                   b'{"key":Infinity}', b'{"key":-Infinity}', b'{"key":1e999}', b"\xff"],
    ids=["empty", "oversized-body", "duplicate-key", "nan", "positive-infinity",
         "negative-infinity", "overflow-number", "invalid-utf8"])
def test_ambiguous_or_oversize_raw_json_is_not_accepted(body):
    with pytest.raises(contract.ScientificAdjudicationError):
        contract.loads(body)


def test_duplicate_targets_and_implicit_large_batches_are_rejected():
    body = request()
    original = deepcopy(body["items"][0])
    body["items"].append(deepcopy(original))
    body["items"][1]["decision_id"] = str(uuid4())
    with pytest.raises(contract.ScientificAdjudicationError):
        contract.validate_request(body)
    body["items"] = [request()["items"][0] for _ in range(20)]
    assert len(contract.validate_request(body)["items"]) == 20
    body["items"].append(request()["items"][0])
    with pytest.raises(contract.ScientificAdjudicationError):
        contract.validate_request(body)


@pytest.mark.parametrize("change", ["later", "different_property", "different_subject", "different_hash", "self"])
def test_science_dependency_must_be_an_earlier_exact_accepted_fidelity_item(change):
    body = request()
    science = deepcopy(body["items"][0])
    science.update(decision_id=str(uuid4()), scope="scientific_result",
        profile_version="sampled-phonon-minimum-review/1.0.0", proposition="sampled_frequency_minimum_only",
        extraction_decision_id=body["items"][0]["decision_id"])
    body["items"].append(science)
    assert contract.validate_request(body) == body
    if change == "later": body["items"].reverse()
    if change == "different_property": science["property_id"] = str(uuid4())
    if change == "different_subject": science["subject_id"] = str(uuid4())
    if change == "different_hash": science["expected_subject_sha256"] = "0" * 64
    if change == "self": science["extraction_decision_id"] = science["decision_id"]
    with pytest.raises(contract.ScientificAdjudicationError):
        contract.validate_request(body)


def test_preview_hash_binds_actor_grant_and_entire_request():
    body = request()
    actor, grant = uuid4(), uuid4()
    original = contract.preview_binding(body, actor, grant)
    assert contract.preview_binding(contract.loads(canonical(body)), actor, grant) == original
    assert contract.preview_binding(body, uuid4(), grant) != original
    assert contract.preview_binding(body, actor, uuid4()) != original
    body["items"][0]["rationale"] += " Additional scoped reviewer explanation."
    assert contract.preview_binding(body, actor, grant) != original
