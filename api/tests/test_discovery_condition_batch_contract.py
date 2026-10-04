"""Pure closed-contract counterexamples; all science content is synthetic."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

from services import discovery_condition_batch_contract as contract
from services.research_release_manifest import canonical

FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/discovery-designs-native.synthetic.json"


def native_reference():
    wire = json.loads(FIXTURE.read_text())
    entry = wire["page"]["entries"][0]
    row = json.loads(entry["receipt"]["receipt_canonical_json"])
    row["record_sha256"] = entry["record_sha256"]
    actor = {key: wire["capabilities"][key] for key in (
        "actor_user_id", "session_version", "curator_grant_id")}
    return row, entry["projection"], actor


def axes():
    return {"pressures": [{"kind": "specified", "raw_gpa": "10"}], "temperatures_k": ["300"]}


def alias_axes():
    return {"pressures": [{"kind": "ambient", "raw_gpa": None}] + [
        {"kind": "specified", "raw_gpa": value} for value in ("0", "0.0", "10", "20")],
        "temperatures_k": [None, "250", "300"]}


def retain_request():
    row, projection, actor = native_reference()
    manifest = contract.build_manifest(row, projection, actor, axes())
    return {"version": contract.REQUEST_VERSION, "request_key": "condition-batch:specific-input/1",
        "operation": "retain_batch", "payload": {"parent": manifest["parent"], "axes": axes(),
            "expected_input_sha256": manifest["input_sha256"],
            "expected_manifest_sha256": manifest["manifest_sha256"]}}


def child_request():
    return {"version": contract.REQUEST_VERSION, "request_key": "condition-child:specific-candidate/1",
        "operation": "propose_candidate_child", "payload": {"batch": {
            "id": "00000000-0000-0000-0000-000000000001", "record_sha256": "a" * 64,
            "manifest_sha256": "b" * 64}, "candidate_sha256": "c" * 64}}


def assert_code(call, expected):
    with pytest.raises(contract.DiscoveryConditionBatchError) as error:
        call()
    assert str(error.value) == expected
    assert str(error.value) in contract.ERROR_CODES


def test_versions_limits_and_false_authority_remain_distinct_from_local_generation():
    assert contract.VERSION == "discovery-condition-batch/1.0.0"
    assert contract.REQUEST_VERSION == "discovery-condition-batch-operation/1.0.0"
    assert contract.OPERATIONS == ("retain_batch", "propose_candidate_child")
    assert (contract.MAX_BYTES, contract.MAX_PAGE, contract.MAX_OPTIONS, contract.MAX_SCENARIOS,
            contract.MAX_MANIFEST_BYTES, contract.MAX_EXPORT_BYTES) == (16384, 8, 8, 64, 4194304, 4194432)
    assert contract.AUTHORITY == {"scientific_acceptance": False, "canonical_promotions": 0,
        "ml_training_approved": False, "public_release": False, "calculation_executed": False,
        "scope": "private_owner_condition_batch"}


def test_closed_requests_validate_and_snapshot_before_async_use():
    request = retain_request()
    detached = contract.snapshot(request)
    request["payload"]["axes"]["pressures"][0]["raw_gpa"] = "999"
    request["payload"]["parent"]["record_sha256"] = "f" * 64
    assert detached["payload"]["axes"] == axes()
    assert detached["payload"]["parent"]["record_sha256"] != "f" * 64
    assert contract.validate(child_request()) == child_request()


@pytest.mark.parametrize("change", [
    lambda r: r.update(scientific_acceptance=True),
    lambda r: r["payload"].update(proposal={"predicted_tc": 300}),
    lambda r: r["payload"].update(source_pins={"context_sha256": "a" * 64}),
    lambda r: r["payload"].update(scenarios=[]),
    lambda r: r["payload"].update(batch_saved=True),
    lambda r: r["payload"]["parent"].update(is_head=True),
    lambda r: r["payload"]["axes"].update(atomic_sites=[]),
    lambda r: r["payload"]["axes"]["pressures"][0].update(unit="GPa"),
])
def test_retention_refuses_uploaded_proposals_source_authority_or_open_objects(change):
    request = retain_request()
    change(request)
    with pytest.raises(contract.DiscoveryConditionBatchError) as error:
        contract.validate(request)
    assert str(error.value) in contract.ERROR_CODES


@pytest.mark.parametrize("change", [
    lambda r: r["payload"].update(proposal={}),
    lambda r: r["payload"].update(baseline={}),
    lambda r: r["payload"]["batch"].update(parent={}),
    lambda r: r["payload"].update(candidate_sha256="C" * 64),
    lambda r: r["payload"]["batch"].update(id="00000000-0000-0000-0000-000000000001 "),
])
def test_child_is_exact_batch_and_candidate_pin_only(change):
    request = child_request()
    change(request)
    with pytest.raises(contract.DiscoveryConditionBatchError) as error:
        contract.validate(request)
    assert str(error.value) in contract.ERROR_CODES


@pytest.mark.parametrize("value", ["", "/first", "a" * 161, "private\ntext", "私有", True, None])
def test_request_key_uses_existing_bounded_design_syntax(value):
    request = child_request()
    request["request_key"] = value
    assert_code(lambda: contract.validate(request), "condition_batch_request_key_required")


def test_request_byte_bound_is_canonical_byte_bound(monkeypatch):
    request = child_request()
    size = len(canonical(request))
    monkeypatch.setattr(contract, "MAX_BYTES", size)
    contract.validate(request)
    monkeypatch.setattr(contract, "MAX_BYTES", size - 1)
    assert_code(lambda: contract.snapshot(request), "condition_batch_operation_byte_bound")


@pytest.mark.parametrize("revision", [0, -1, 1001, True, 1.0, "1"])
def test_parent_revision_is_exact_existing_native_integer_bound(revision):
    request = retain_request()
    request["payload"]["parent"]["revision"] = revision
    assert_code(lambda: contract.validate(request), "condition_batch_revision_required")


@pytest.mark.parametrize("raw", ["-1", "-0", "+1", "NaN", "Infinity", "0x10", "1e999", "1e-999",
    " 1", "1 ", "", "1" * 65, "٣٠٠", "0e1000000000000000000", "0e-1999999999999999998",
    "0.0e-1999999999999999997", "0e" + "9" * 61, 300, True, None])
def test_invalid_decimal_rejects_entire_sweep_with_static_code(raw):
    selected = axes()
    selected["pressures"].append({"kind": "specified", "raw_gpa": raw})
    assert_code(lambda: contract.estimate(selected), "condition_batch_decimal_invalid")


def test_raw_decimal_length_boundary_and_native_zero_exponent_offsets():
    assert contract.decimal_identity("0" * 64) == "0e0"
    for spelling in ("0e999999999999999999", "0e-1999999999999999997",
                     "0.0e1000000000000000000", "0.00e1000000000000000001"):
        assert contract.decimal_identity(spelling) == "0e0"
    assert contract.decimal_identity(".10e1") == "1e0"
    assert contract.decimal_identity("000100.00") == "1e2"


def test_exact_precision_does_not_merge_binary_float_aliases():
    raw = ["9007199254740992", "9007199254740993", "1.00000000000000000000000001",
           "1.00000000000000000000000002", "3e-324", "4e-324"]
    assert float(raw[0]) == float(raw[1]) and float(raw[-2]) == float(raw[-1])
    chosen = {"pressures": [{"kind": "specified", "raw_gpa": value} for value in raw],
              "temperatures_k": ["300"]}
    assert contract.estimate(chosen)["unique_cartesian_count"] == 6


@pytest.mark.parametrize("selected,code", [
    ({"pressures": [], "temperatures_k": [None]}, "condition_batch_empty_axis"),
    ({"pressures": axes()["pressures"], "temperatures_k": []}, "condition_batch_empty_axis"),
    ({"pressures": axes()["pressures"]}, "condition_batch_axes_invalid"),
    ({"pressures": [{"kind": "ambient", "raw_gpa": "0"}], "temperatures_k": [None]}, "condition_batch_pressure_invalid"),
    ({"pressures": [{"kind": "unknown", "raw_gpa": None}], "temperatures_k": [None]}, "condition_batch_pressure_invalid"),
    ({"pressures": axes()["pressures"], "temperatures_k": [300]}, "condition_batch_temperature_invalid"),
    ({"pressures": axes()["pressures"] * 9, "temperatures_k": [None]}, "condition_batch_axis_limit"),
    ({"pressures": axes()["pressures"], "temperatures_k": [None] * 9}, "condition_batch_axis_limit"),
])
def test_whole_axes_refusal_and_no_silent_truncation(selected, code):
    assert_code(lambda: contract.estimate(selected), code)


def test_full_8_by_8_and_15_to_12_explicit_estimates():
    row, projection, actor = native_reference()
    chosen = {"pressures": [{"kind": "specified", "raw_gpa": str(i)} for i in range(8)],
              "temperatures_k": [str(290 + i) for i in range(8)]}
    manifest = contract.build_manifest(row, projection, actor, chosen)
    assert len(manifest["scenarios"]) == len({item["candidate_sha256"] for item in manifest["scenarios"]}) == 64
    assert contract.estimate(alias_axes()) == {"raw_cartesian_count": 15, "unique_cartesian_count": 12,
        "pressure": {"raw_count": 5, "unique_count": 4, "collapsed_count": 1},
        "temperature": {"raw_count": 3, "unique_count": 3, "collapsed_count": 0},
        "collapsed_reason_codes": ["pressure_aliases_collapsed"], "max_scenarios": 64}


def test_literal_typescript_browser_artifact_parity_for_existing_native_synthetic_parent():
    # These literal digests were independently checked against the local TS
    # planner's actual downloaded artifact. The fixture remains synthetic and
    # neither this equality nor a checksum asserts live SQL authorization.
    row, projection, actor = native_reference()
    manifest = contract.build_manifest(row, projection, actor, alias_axes())
    assert manifest["input_sha256"] == "47844ecbc764400a52c199bf28b5f98b880161cd031399f6cd9cd920b90f1740"
    assert manifest["manifest_sha256"] == "17de1ff390afbb508d53a7eb553711129f898229eab33f792fede0148bd9c2af"
    assert manifest["scenarios"][0]["candidate_sha256"] == "874b8225c69ca3922c64ff77f4ba5da5b62e46f7823104370f14052c7357270d"
    assert manifest["scenarios"][-1]["candidate_sha256"] == "f1484a81e2c36e4b21a6bbc7505cc8de12935f7ba11883e698957ef3f806259b"


def test_ambient_specified_zero_unknown_pressure_and_temperature_remain_distinct():
    row, projection, actor = native_reference()
    chosen = {"pressures": [{"kind": "unspecified", "raw_gpa": None}, {"kind": "ambient", "raw_gpa": None},
        {"kind": "specified", "raw_gpa": "0"}, {"kind": "specified", "raw_gpa": "0.000e999999999999999999"}],
        "temperatures_k": [None, "0", "0e-999999999999999999"]}
    manifest = contract.build_manifest(row, projection, actor, chosen)
    assert len(manifest["scenarios"]) == 6
    assert {item["conditions"]["pressure"]["kind"] for item in manifest["scenarios"]} == {"unspecified", "ambient", "specified"}
    assert sum(item["conditions"]["temperature_k"] is None for item in manifest["scenarios"]) == 3


def test_first_alias_and_raw_input_order_are_sealed_independently_from_candidate_identity():
    row, projection, actor = native_reference()
    chosen = {"pressures": [{"kind": "specified", "raw_gpa": value} for value in ("01.00", "1e0", "1", ".10e1")],
              "temperatures_k": ["0300.0", "3e2", "300"]}
    a = contract.build_manifest(row, projection, actor, chosen)
    assert a["scenarios"][0]["conditions"] == {"pressure": {"kind": "specified", "raw_gpa": "01.00"}, "temperature_k": "0300.0"}
    assert json.loads(a["input_canonical_json"])["axes"] == chosen
    changed = deepcopy(chosen)
    changed["pressures"].reverse()
    changed["temperatures_k"].reverse()
    renewed = {**actor, "session_version": actor["session_version"] + 1}
    b = contract.build_manifest(row, projection, renewed, changed)
    assert a["scenarios"][0]["candidate_sha256"] == b["scenarios"][0]["candidate_sha256"]
    assert a["input_sha256"] != b["input_sha256"] and a["manifest_sha256"] != b["manifest_sha256"]
    c = contract.build_manifest(row, projection, renewed, chosen)
    assert a["input_sha256"] == c["input_sha256"] and a["manifest_sha256"] != c["manifest_sha256"]


def test_candidate_identity_changes_with_immutable_parent_digest():
    row, projection, actor = native_reference()
    a = contract.build_manifest(row, projection, actor, axes())
    changed = deepcopy(row)
    changed["record_sha256"] = "a" * 64
    b = contract.build_manifest(changed, projection, actor, axes())
    assert a["scenarios"][0]["conditions"] == b["scenarios"][0]["conditions"]
    assert a["scenarios"][0]["candidate_sha256"] != b["scenarios"][0]["candidate_sha256"]


def test_unchanged_local_artifact_proposals_and_authority_have_independent_objects():
    row, projection, actor = native_reference()
    original_row, original_projection, original_actor = deepcopy(row), deepcopy(projection), deepcopy(actor)
    manifest = contract.build_manifest(row, projection, actor, alias_axes())
    sha = manifest.pop("manifest_sha256")
    assert hashlib.sha256(canonical(manifest)).hexdigest() == sha
    assert hashlib.sha256(manifest["input_canonical_json"].encode()).hexdigest() == manifest["input_sha256"]
    assert manifest["scope"] == "local_private_condition_sweep"
    assert all(manifest[key] is False for key in ("scientific_acceptance", "ml_training_approved", "public_release",
        "calculation_executed", "database_changed", "batch_saved", "atomic_sites_generated"))
    assert manifest["canonical_promotions"] == 0
    assert set(manifest["source_pins"]) == {"baseline", "context_sha256", "projection_sha256", "event_id", "state_id", "producer_run_id"}
    assert "values" not in manifest["source_pins"] and "context_json" not in manifest["source_pins"]
    assert row == original_row and projection == original_projection and actor == original_actor
    first, second = manifest["scenarios"][:2]
    first["proposal"]["next_action"]["question"] = "A later user draft change"
    first["conditions"]["pressure"]["kind"] = "unspecified"
    assert second["proposal"]["next_action"] == row["design"]["next_action"]
    assert first["proposal"]["target_conditions"] != first["conditions"]


def test_unknown_resource_totals_are_not_zero_and_estimates_are_not_aggregated():
    row, projection, actor = native_reference()
    row["design"]["next_action"]["budget"][0].update(status="estimated", raw_upper="0")
    manifest = contract.build_manifest(row, projection, actor, axes())
    assert manifest["scenarios"][0]["proposal"]["next_action"]["budget"][0]["raw_upper"] == "0"
    assert manifest["budget_totals"][0]["status"] == "not_aggregated"
    assert all(item["total"] is None for item in manifest["budget_totals"])
    assert all(item["status"] == "unknown" for item in manifest["budget_totals"][1:])


def test_native_uuid_row_identity_is_extracted_without_context_receipt_egress():
    row, projection, actor = native_reference()
    native = deepcopy(row)
    native["id"], native["design_id"] = UUID(native["id"]), UUID(native["design_id"])
    native["context_json"] = "PRIVATE SOURCE VALUE NEVER INCLUDED"
    native["unrelated"] = object()
    manifest = contract.build_manifest(native, projection, actor, axes())
    assert "PRIVATE SOURCE" not in canonical(manifest).decode()
    assert manifest == contract.build_manifest(row, projection, actor, axes())


@pytest.mark.parametrize("change,code", [
    (lambda row, projection, actor: row["baseline"].update(kind="unanchored", material_id=None, property_id=None, record_index=None), "condition_batch_source_unavailable"),
    (lambda row, projection, actor: row.update(context_sha256="a" * 64), "condition_batch_parent_invalid"),
    (lambda row, projection, actor: row["design"].update(predicted_tc=300), "condition_batch_parent_invalid"),
    (lambda row, projection, actor: projection.update(event_id="not-an-id"), "condition_batch_identifier_required"),
    (lambda row, projection, actor: actor.update(scientific_acceptance=True), "condition_batch_closed_object_required"),
    (lambda row, projection, actor: actor.update(session_version=True), "condition_batch_actor_invalid"),
])
def test_received_parent_pins_and_actor_are_closed_not_science_or_authorization(change, code):
    row, projection, actor = native_reference()
    change(row, projection, actor)
    assert_code(lambda: contract.build_manifest(row, projection, actor, axes()), code)


def test_manifest_limit_counts_utf8_bytes_without_returning_a_partial_manifest(monkeypatch):
    row, projection, actor = native_reference()
    row["design"]["hypothesis"] = "科学" * 2000
    manifest = contract.build_manifest(row, projection, actor, axes())
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    size = len(canonical(body))
    assert size > len(canonical(body).decode())
    monkeypatch.setattr(contract, "MAX_MANIFEST_BYTES", size)
    contract.build_manifest(row, projection, actor, axes())
    monkeypatch.setattr(contract, "MAX_MANIFEST_BYTES", size - 1)
    assert_code(lambda: contract.build_manifest(row, projection, actor, axes()), "condition_batch_manifest_limit")


def test_full_size_valid_unicode_design_exceeds_4mib_bound_at_64_candidates():
    row, projection, actor = native_reference()
    row["design"]["hypothesis"] = "🧪" * 4000
    row["design"]["next_action"]["prerequisites"] = ["🧪" * 1000] * 16
    chosen = {"pressures": [{"kind": "specified", "raw_gpa": str(i)} for i in range(8)],
              "temperatures_k": [str(290 + i) for i in range(8)]}
    assert_code(lambda: contract.build_manifest(row, projection, actor, chosen), "condition_batch_manifest_limit")
