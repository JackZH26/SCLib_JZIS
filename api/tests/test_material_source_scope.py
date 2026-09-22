"""Pure source-policy fixtures, executed through the guarded API runner."""
from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from services import material_source_scope as policy
from services.material_anomalies import material_review, review_context
from services.material_source_scope import (
    SOURCE_SCOPE_VERSION,
    VISIBILITY_VERSION,
    SourceScope,
    SourceScopeError,
    current_visibility_allows_view,
    legacy_parent_visibility,
    scoped_material_visibility,
    validate_scoped_visibility,
)
from services.material_visibility import (
    MATERIAL_VISIBILITY_VERSION,
    visibility_allows_view,
    visibility_for_material,
)
from services.source_lifecycle_status import overlay_source_lifecycle


def record(paper="active-paper", **changes):
    return {"paper_id": paper, "formula": "MgB2", "tc_kelvin": "39 K",
            "pressure_gpa": "0 GPa", "pressure_state": "explicit_ambient",
            "knowledge_origin": "Observed", "source_role": "primary", **changes}


def material(records=None, **changes):
    return {"id": "material-a", "status": "active_research", "needs_review": False,
            "retracted": False, "disputed": False,
            "records": [record(), record("held-paper")] if records is None else records, **changes}


def statuses(held="retracted", **changes):
    return {"active-paper": "published", "held-paper": held, **changes}


def legacy(value, sources, **kwargs):
    return visibility_for_material(value, anomaly_review=material_review(
        value["records"], scope_id=value["id"], context=review_context(value), compact=True),
        source_statuses=sources, **kwargs)


def scoped(value=None, sources=None, **kwargs):
    return scoped_material_visibility(material() if value is None else value,
        source_statuses=statuses() if sources is None else sources, **kwargs)


@pytest.mark.parametrize("sources", [
    {}, {"active-paper": None, "held-paper": None},
    {"active-paper": "published", "held-paper": "published"},
    {"active-paper": "published", "held-paper": None},
    {"active-paper": "retracted", "held-paper": "retracted"},
    {"active-paper": "corrected", "held-paper": "retracted"},
])
def test_ordinary_and_unsplittable_inputs_preserve_exact_v1(sources):
    value = material()
    visibility, scope = scoped(value, sources)
    assert scope is None
    assert visibility == legacy(value, sources)


@pytest.mark.parametrize("records", [[], {}, "malformed", [None], ["bad"], [record()]])
def test_non_list_or_single_record_legacy_policy_unchanged(records):
    value = material(records)
    sources = {"active-paper": "published"}
    visibility, scope = scoped(value, sources)
    assert scope is None
    assert visibility == legacy(value, sources)


@pytest.mark.parametrize("held", ["retracted", "withdrawn", "corrected", "disputed",
    overlay_source_lifecycle("published", "a" * 64)])
def test_only_exact_active_source_survives_each_lifecycle_hold(held):
    value = material()
    before = copy.deepcopy(value)
    visibility, scope = scoped(value, statuses(held))
    assert visibility["version"] == VISIBILITY_VERSION
    assert visibility["state"] == "catalogue"
    assert visibility["scientific_acceptance"] is False
    assert visibility["reason_codes"] == visibility["reason_messages"] == []
    assert scope is not None
    assert scope.version == SOURCE_SCOPE_VERSION
    assert scope.indices == (0, 1)
    assert scope.eligible_indices == (0,)
    assert scope.paper_ids == ("active-paper", "held-paper")
    assert scope.eligible_paper_ids == ("active-paper",)
    assert scope.reason_for(0) == ()
    assert scope.reason_for(1)
    assert scope.paper_for(1) == "held-paper"
    assert scope.eligible_records(value["records"]) == [value["records"][0]]
    assert scope.validate(value["records"]) is scope
    assert visibility["source_scope"] == {
        "version": SOURCE_SCOPE_VERSION, "status": "eligible_records_only",
        "total_records": 2, "eligible_records": 1, "excluded_records": 1,
        "eligible_source_count": 1, "fingerprint": scope.fingerprint,
        "independent_support_count": None,
    }
    assert current_visibility_allows_view(visibility)
    assert current_visibility_allows_view(visibility, include_archive=True)
    assert not visibility_allows_view(visibility)  # Frozen consumers must not opt in accidentally.
    assert validate_scoped_visibility(visibility) == visibility
    assert value == before


@pytest.mark.parametrize("bad_record,bad_status,reason", [
    (record("unknown"), None, "source_status_unknown"),
    (record("unknown"), "preprint", "source_status_unknown"),
    (record("unknown"), 1, "source_status_unknown"),
    (record("unknown"), {}, "source_metadata_invalid"),
    (record("unknown", needs_review=True), "published", "record_review_required"),
    (record("unknown", disputed=True), "published", "record_disputed"),
    (record("unknown", retracted=True), "published", "record_retracted"),
    (record("unknown", corrected=True), "published", "record_corrected"),
    (record("unknown", review_status="pending"), "published", "record_review_required"),
    (record("unknown", needs_review=0), "published", "record_review_metadata_invalid"),
    (record("unknown", review_status=False), "published", "record_review_metadata_invalid"),
    (record("unknown", tc_kelvin="900 K"), "published", "record_anomaly_review_required"),
    (record("unknown", tc_kelvin="-1 K"), "published", "record_anomaly_review_required"),
    (record(None), "published", "record_source_unresolved"),
    (record(""), "published", "record_source_unresolved"),
    ({"formula": "MgB2", "tc_kelvin": 39}, "published", "record_source_unresolved"),
    (None, "published", "record_format_invalid"),
    ("not-an-object", "published", "record_format_invalid"),
])
def test_complete_partition_excludes_unknown_malformed_or_record_held_values(bad_record, bad_status, reason):
    value = material([record(), bad_record, record("held-paper")])
    visibility, scope = scoped(value, statuses(unknown=bad_status))
    assert visibility["version"] == VISIBILITY_VERSION
    assert scope.eligible_indices == (0,)
    assert reason in scope.reason_for(1)
    assert scope.indices == (0, 1, 2)
    assert visibility["source_scope"]["excluded_records"] == 2


@pytest.mark.parametrize("changes", [
    {"needs_review": True}, {"retracted": True}, {"disputed": True},
    {"needs_review": 0}, {"retracted": "false"}, {"disputed": []},
    {"status": "pending"}, {"status": "under_review"}, {"status": "corrected"},
    {"status": "retracted"}, {"status": "withdrawn"}, {"status": "refuted"},
    {"status": "accepted"}, {"status": "unknown"}, {"status": 1},
    {"status": "quarantined"}, {"review_reason": "provenance_quarantine_private"},
])
def test_material_governance_always_blocks_scope(changes):
    value = material(**changes)
    visibility, scope = scoped(value)
    assert scope is None
    assert visibility == legacy(value, statuses())
    assert not current_visibility_allows_view(visibility)


@pytest.mark.parametrize("changes", [
    {"provenance_status": "quarantined"}, {"status": "quarantined"},
    {"review_status": "provenance_quarantined"},
    {"review_reason": " PROVENANCE_QUARANTINE_restricted"},
])
def test_record_provenance_quarantine_is_global_even_when_that_source_is_held(changes):
    value = material([record(), record("held-paper", **changes)])
    visibility, scope = scoped(value)
    assert scope is None
    assert visibility["state"] == "quarantined"
    assert not current_visibility_allows_view(visibility, include_archive=True)


def test_retained_negative_numeric_anomaly_recomputed_only_for_eligible_records():
    value = material([record(), record("held-paper", tc_kelvin="900 K")])
    assert legacy(value, statuses())["state"] == "pending"
    visibility, scope = scoped(value)
    assert scope.eligible_indices == (0,)
    assert current_visibility_allows_view(visibility)
    value["needs_review"] = True
    assert scoped(value)[1] is None  # Explicit global review remains sticky.


def test_no_active_record_or_all_active_records_anomalous_never_upgrades():
    value = material([record(tc_kelvin="900 K"), record("held-paper")])
    assert scoped(value)[1] is None
    assert scoped(material([record(None), record("held-paper")]))[1] is None


def test_duplicate_records_keep_original_positions_and_count_sources_not_independence():
    value = material([record(), record(), record("active-2"), record("held-paper")])
    visibility, scope = scoped(value, statuses(**{"active-2": "active"}))
    assert scope.eligible_indices == (0, 1, 2)
    assert scope.record_sha256[0] == scope.record_sha256[1]
    assert scope.eligible_paper_ids == ("active-2", "active-paper")
    assert visibility["source_scope"]["eligible_records"] == 3
    assert visibility["source_scope"]["eligible_source_count"] == 2
    assert visibility["source_scope"]["independent_support_count"] is None


def test_positive_private_notes_do_not_approve_or_leak():
    secret = "PRIVATE_REVIEW_CANARY"
    value = material(admin_decision={"accepted": True, "notes": secret}, review_reason=secret)
    value["records"][1]["review_note"] = secret
    visibility, scope = scoped(value)
    assert scope is not None
    assert secret not in json.dumps(visibility)
    assert "active-paper" not in json.dumps(visibility)
    assert "held-paper" not in json.dumps(visibility)
    assert visibility["scientific_acceptance"] is False
    value["needs_review"] = True
    assert scoped(value)[1] is None


@pytest.mark.parametrize("error", ["missing_parent", "cyclic_parent", "depth_exceeded", "unknown"])
def test_unresolved_ancestry_never_scopes_or_grants_archive(error):
    visibility, scope = scoped(ancestry_error=error)
    assert scope is None
    assert not current_visibility_allows_view(visibility, include_archive=True)


def test_parent_holds_and_missing_parent_preserved():
    parent = legacy(material(needs_review=True), {})
    child = material(parent_material_id="parent")
    assert scoped(child, parent_visibility=parent)[1] is None
    visibility, scope = scoped(child)
    assert scope is None
    assert visibility["archive_available"] is False


def test_v2_parent_bridge_validates_and_preserves_exact_revision():
    parent, _ = scoped()
    bridged = legacy_parent_visibility(parent)
    assert bridged["version"] == MATERIAL_VISIBILITY_VERSION
    assert bridged["review_revision"] == parent["review_revision"]
    assert "source_scope" not in bridged
    child = material(parent_material_id="parent")
    visibility, scope = scoped(child, parent_visibility=parent)
    assert scope is not None
    changed = copy.deepcopy(parent)
    changed["review_revision"] = "b" * 64
    newer, _ = scoped(child, parent_visibility=changed)
    assert newer["review_revision"] != visibility["review_revision"]
    assert newer["source_scope"]["fingerprint"] != visibility["source_scope"]["fingerprint"]
    changed["scientific_acceptance"] = True
    held, no_scope = scoped(child, parent_visibility=changed)
    assert no_scope is None
    assert not current_visibility_allows_view(held, include_archive=True)
    # Even without a parent FK, explicitly supplied malformed parent stays a hold.
    assert not current_visibility_allows_view(scoped(parent_visibility=changed)[0])


def test_v1_parent_bridge_and_predicate_semantics_are_not_redefined():
    value = {"version": MATERIAL_VISIBILITY_VERSION, "state": "catalogue",
             "archive_available": True, "public_catalogue_eligible": True,
             "scope": "legacy-enrichment", "unknown_legacy_field": "unchanged"}
    assert legacy_parent_visibility(value) is value
    assert current_visibility_allows_view(value) == visibility_allows_view(value)
    value["state"] = "pending"
    assert current_visibility_allows_view(value, include_archive=True) == visibility_allows_view(value, include_archive=True)


@pytest.mark.parametrize("sources", [
    {"active-paper": "published", "held-paper": None, "unrelated": "retracted"},
    {"active-paper": "published", "held-paper": {}},
    {"active-paper": "published", "held-paper": {"status": "published", "lifecycle_review_required": True}},
    {"active-paper": "published", "held-paper": "retracted", "": "published"},
    ["published", "retracted"], "retracted", None,
])
def test_no_upgrade_from_unrelated_holds_or_unbound_malformed_status_inventory(sources):
    assert scoped_material_visibility(material(), source_statuses=sources)[1] is None


@pytest.mark.parametrize("mutate", [
    lambda records: records.reverse(),
    lambda records: records.pop(),
    lambda records: records.append(record()),
    lambda records: records[0].update(tc_kelvin="40 K"),
    lambda records: records[1].update(tc_kelvin="40 K"),
    lambda records: records[0].update(paper_id="another-paper"),
])
def test_all_original_records_are_bound_before_selection(mutate):
    value = material()
    _, scope = scoped(value)
    mutate(value["records"])
    with pytest.raises(SourceScopeError, match="source_scope_record_inventory_changed"):
        scope.eligible_records(value["records"])


@pytest.mark.parametrize("field,value", [
    ("version", "wrong"), ("material_id", "other"), ("indices", (False, 1)),
    ("indices", (1, 0)), ("eligible_indices", (1,)), ("eligible_indices", (False,)),
    ("eligible_indices", (0, 0)), ("eligible_indices", (3,)), ("eligible_indices", []),
    ("paper_ids", ("held-paper", "active-paper")), ("paper_ids", ()),
    ("reason_codes", (("source_retracted",), ())), ("record_sha256", ("a" * 64, "b" * 64)),
    ("fingerprint", "a" * 64), ("_seal", "a" * 64),
])
def test_private_scope_replacement_is_not_a_selection_authority(field, value):
    raw = material()
    _, scope = scoped(raw)
    modified = replace(scope, **{field: value})
    with pytest.raises(SourceScopeError):
        modified.eligible_records(raw["records"])


def test_scope_cannot_be_constructed_or_mutated_as_an_authority():
    _, scope = scoped()
    copied = SourceScope(scope.version, scope.material_id, scope.indices, scope.eligible_indices,
                         scope.paper_ids, scope.reason_codes, scope.record_sha256, scope.fingerprint)
    with pytest.raises(SourceScopeError):
        copied.validate()
    with pytest.raises(FrozenInstanceError):
        scope.material_id = "other"
    records = scope.eligible_records(material()["records"])
    records[0]["tc_kelvin"] = "900 K"
    assert scope.eligible_records(material()["records"])[0]["tc_kelvin"] == "39 K"


@pytest.mark.parametrize("index", [-1, True, 2, "0"])
def test_private_index_access_is_strict(index):
    _, scope = scoped()
    with pytest.raises(SourceScopeError):
        scope.paper_for(index)
    with pytest.raises(SourceScopeError):
        scope.reason_for(index)


@pytest.mark.parametrize("key,value", [
    ("version", "material-visibility/3.0.0"), ("version", []),
    ("scientific_acceptance", True), ("scientific_acceptance", 0),
    ("archive_available", 1), ("public_catalogue_eligible", 1),
    ("state", "pending"), ("state", []), ("source_status", "approved"),
    ("review_revision", "A" * 64), ("reason_codes", ["source_retracted"]),
    ("reason_messages", ["PRIVATE_CANARY"]), ("warning_codes", ["unknown"]),
    ("warning_messages", ["PRIVATE_CANARY"]), ("source_scope", None),
])
def test_public_v2_closed_fields_reject_malformed_values(key, value):
    visibility, _ = scoped()
    visibility[key] = value
    assert not current_visibility_allows_view(visibility)
    with pytest.raises(SourceScopeError):
        validate_scoped_visibility(visibility)


@pytest.mark.parametrize("key,value", [
    ("version", "old"), ("status", "all_sources_approved"),
    ("total_records", 3), ("total_records", True), ("total_records", 5001),
    ("eligible_records", 0), ("excluded_records", 0), ("eligible_source_count", 2),
    ("fingerprint", "not-a-hash"), ("independent_support_count", 0),
])
def test_public_source_counts_do_not_claim_independent_support(key, value):
    visibility, _ = scoped()
    visibility["source_scope"][key] = value
    assert not current_visibility_allows_view(visibility, include_archive=True)


def test_public_validator_is_detached_and_requires_complete_closed_shape():
    visibility, _ = scoped()
    detached = validate_scoped_visibility(visibility)
    detached["source_scope"]["eligible_records"] = 99
    assert visibility["source_scope"]["eligible_records"] == 1
    for key in list(visibility):
        broken = copy.deepcopy(visibility)
        del broken[key]
        assert not current_visibility_allows_view(broken)
    for target in (visibility, visibility["source_scope"]):
        target["extra"] = "private"
        assert not current_visibility_allows_view(visibility)
        del target["extra"]
    with pytest.raises(SourceScopeError):
        validate_scoped_visibility(legacy(material(), {}))


def test_scope_and_review_fingerprints_reproducible_but_bind_every_input():
    value = material()
    first, scope = scoped(value)
    assert scoped(copy.deepcopy(value))[0] == first
    value["records"][1]["note"] = "retained-only-change"
    changed, _ = scoped(value)
    assert changed["source_scope"]["fingerprint"] != scope.fingerprint
    assert changed["review_revision"] != first["review_revision"]
    source_a = statuses(overlay_source_lifecycle("published", "a" * 64))
    source_b = statuses(overlay_source_lifecycle("published", "b" * 64))
    assert scoped(sources=source_a)[0]["review_revision"] != scoped(sources=source_b)[0]["review_revision"]


@pytest.mark.parametrize("name,limit", [("MAX_RECORDS", 1), ("MAX_BYTES", 80), ("MAX_NODES", 10), ("MAX_DEPTH", 1)])
def test_scope_budget_failure_is_explicit_non_catalogue_v1_not_partial_success(monkeypatch, name, limit):
    monkeypatch.setattr(policy, name, limit)
    visibility, scope = scoped()
    assert scope is None
    assert visibility["version"] == MATERIAL_VISIBILITY_VERSION
    assert "anomaly_assessment_unavailable" in visibility["reason_codes"]
    assert not current_visibility_allows_view(visibility)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "\ud800", {1: "bad-key"}])
def test_noncanonical_inputs_fail_closed_without_losing_global_holds(bad):
    value = material([record(), record("held-paper", extra=bad)], needs_review=True)
    visibility, scope = scoped(value)
    assert scope is None
    assert "anomaly_assessment_unavailable" in visibility["reason_codes"]
    assert "material_review_required" in visibility["reason_codes"]
    assert not current_visibility_allows_view(visibility)


def test_orm_like_material_supported_without_accepting_its_stored_visibility():
    value = material(visibility={"public_catalogue_eligible": False})
    ordinary = scoped(value)[0]
    actual, scope = scoped_material_visibility(SimpleNamespace(**value), source_statuses=statuses())
    assert actual == ordinary
    assert scope is not None
