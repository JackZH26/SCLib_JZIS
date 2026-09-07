"""Pure policy fixtures; pytest is still run through the disposable DB guard."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from services.anomaly_review import ANOMALY_POLICY_VERSION, build_anomaly_review
from services.material_visibility import (
    MATERIAL_VISIBILITY_VERSION,
    normalize_source_status,
    safe_public_review_reason,
    sanitize_review_metadata,
    visibility_allows_view,
    visibility_for_material,
)
from services.property_evidence import legacy_result_id
from services.scientific_filters import ResultFilters, matching_result_references


def _assessment(*, pending=False, year=2026):
    return {
        "version": ANOMALY_POLICY_VERSION, "evaluation_year": year,
        "needs_review": pending,
        "counts": {"no_findings": int(not pending), "review_required": int(pending),
                   "format_invalid": 0, "total_records": 1},
        "rule_counts": {"tc_global_reference": 1} if pending else {},
    }


def _material(**changes):
    return {"id": "material-a", "status": "active_research", "needs_review": False,
            "retracted": False, "disputed": False, "records": [], **changes}


def _visibility(material=None, **kwargs):
    return visibility_for_material(
        _material() if material is None else material,
        anomaly_review=kwargs.pop("anomaly_review", _assessment()),
        source_statuses=kwargs.pop("source_statuses", {"paper-1": "published"}), **kwargs,
    )


@pytest.mark.parametrize(("changes", "state", "catalogue", "archive"), [
    ({}, "catalogue", True, True),
    ({"status": "active"}, "catalogue", True, True),
    ({"status": None}, "catalogue", True, True),
    ({"needs_review": True}, "pending", False, True),
    ({"status": "pending"}, "pending", False, True),
    ({"disputed": True}, "disputed", False, True),
    ({"status": "disputed"}, "disputed", False, True),
    ({"status": "corrected"}, "corrected", False, True),
    ({"retracted": True}, "retracted", False, True),
    ({"status": "retracted"}, "retracted", False, True),
    ({"status": "withdrawn"}, "retracted", False, True),
    ({"status": "unknown"}, "unknown", False, True),
    ({"status": "accepted"}, "unknown", False, True),
    ({"status": "approved"}, "unknown", False, True),
    ({"review_reason": "provenance_quarantine_nims"}, "quarantined", False, False),
    ({"review_reason": " provenance_quarantine_other_source"}, "quarantined", False, False),
    ({"review_reason": "PROVENANCE_QUARANTINE_new " + "x" * 1000}, "quarantined", False, False),
    ({"status": "quarantined"}, "quarantined", False, False),
])
def test_catalogue_and_archive_policy_matrix(changes, state, catalogue, archive):
    visibility = _visibility(_material(**changes))
    assert visibility["version"] == MATERIAL_VISIBILITY_VERSION
    assert visibility["state"] == state
    assert visibility["scientific_acceptance"] is False
    assert visibility["public_catalogue_eligible"] is catalogue
    assert visibility["archive_available"] is archive
    assert visibility_allows_view(visibility) is catalogue
    assert visibility_allows_view(visibility, include_archive=True) is archive


def test_fresh_anomaly_holds_legacy_unflagged_material():
    record = {"tc_kelvin": 900, "pressure_gpa": 200, "paper_id": "p"}
    assessment = build_anomaly_review([record], scope_id="material-a", current_year=2026)
    visibility = _visibility(anomaly_review=assessment)
    assert visibility["state"] == "pending"
    assert "scientific_anomaly_review_required" in visibility["reason_codes"]
    assert visibility["archive_available"] is True


@pytest.mark.parametrize("assessment", [
    None, {}, {"version": "old", "needs_review": False},
    {"version": ANOMALY_POLICY_VERSION, "needs_review": "false"},
    {**_assessment(), "counts": {"format_invalid": 1}},
    {**_assessment(), "counts": {"total_records": True}},
    {**_assessment(), "counts": []},
    {**_assessment(), "rule_counts": {"test": -1}},
    {**_assessment(), "evaluation_year": True},
])
def test_missing_or_malformed_current_anomaly_is_held(assessment):
    visibility = _visibility(anomaly_review=assessment)
    assert visibility["state"] == "unknown"
    assert not visibility_allows_view(visibility)
    assert visibility_allows_view(visibility, include_archive=True)


@pytest.mark.parametrize("flags", [
    {"needs_review": "false"}, {"disputed": 0}, {"retracted": "no"},
])
def test_malformed_governing_flags_do_not_pass(flags):
    visibility = _visibility(_material(**flags))
    assert visibility["state"] == "unknown"
    assert "review_metadata_invalid" in visibility["reason_codes"]


@pytest.mark.parametrize(("statuses", "state", "source_state"), [
    ({"p": "published"}, "catalogue", "active"),
    ({"p": "active"}, "catalogue", "active"),
    ({"p": "retracted"}, "retracted", "retracted"),
    ({"p": "withdrawn"}, "retracted", "retracted"),
    ({"p": "corrected"}, "corrected", "corrected"),
    ({"p": "disputed"}, "disputed", "unknown"),
    ({"p": "published", "q": "retracted"}, "pending", "mixed"),
    ({"p": "published", "q": "corrected"}, "corrected", "mixed"),
    ({"p": "published", "q": None}, "catalogue", "mixed"),
    ({"p": None}, "catalogue", "unknown"),
    (None, "catalogue", "unknown"),
    ([], "catalogue", "unknown"),
    (["retracted", "published"], "pending", "mixed"),
])
def test_authoritative_source_status_matrix(statuses, state, source_state):
    visibility = _visibility(source_statuses=statuses)
    assert visibility["state"] == state
    assert visibility["source_status"] == source_state
    assert visibility["scientific_acceptance"] is False


@pytest.mark.parametrize("statuses", ["published", {1: "published"}, {"p": True}, [None] * 20_001])
def test_malformed_source_metadata_fails_closed(statuses):
    visibility = _visibility(source_statuses=statuses)
    assert not visibility["public_catalogue_eligible"]
    assert "source_metadata_invalid" in visibility["reason_codes"]


def test_unknown_source_does_not_become_active_or_approved():
    visibility = _visibility(source_statuses={"p": "accepted"})
    assert visibility["source_status"] == "unknown"
    assert "source_status_unknown" in visibility["warning_codes"]
    assert visibility["scientific_acceptance"] is False


def test_legacy_notes_do_not_indiscriminately_hide_materials():
    visibility = _visibility(_material(review_reason="historical_category_a; original note"))
    assert visibility["state"] == "catalogue"
    assert visibility["reason_codes"] == []


def test_private_notes_and_source_context_do_not_enter_public_dto_or_fingerprint():
    source = _material(
        needs_review=True, review_reason="email private@example.com; note secret-one",
        admin_decision={"reviewed": True, "reviewer": "private@example.com"},
        records=[{"source_quote": "secret source excerpt", "reviewed": True}],
    )
    first = _visibility(source)
    second = _visibility({**source, "review_reason": "secret-two", "admin_decision": {"reviewer": "another"}})
    serialized = json.dumps(first)
    for private in ("private@example.com", "secret", "reviewer", "source_quote"):
        assert private not in serialized
    assert first == second
    assert safe_public_review_reason(first) == "This material is awaiting review."


def test_stored_anomaly_visibility_and_admin_approval_cannot_change_policy():
    material = _material(
        needs_review=True,
        visibility={"public_catalogue_eligible": True, "scientific_acceptance": True},
        anomaly_review=_assessment(),
        admin_decision={"decision": "override_flag", "reviewed": True},
        reviewed=True,
    )
    assert _visibility(material)["state"] == "pending"
    assert _visibility(material, anomaly_review=None)["public_catalogue_eligible"] is False
    assert _visibility(_material(anomaly_review=_assessment(pending=True)))["state"] == "catalogue"


@pytest.mark.parametrize(("parent_changes", "child_state", "archive"), [
    ({}, "catalogue", True),
    ({"needs_review": True}, "pending", True),
    ({"status": "corrected"}, "pending", True),
    ({"retracted": True}, "pending", True),
    ({"review_reason": "provenance_quarantine_nims"}, "quarantined", False),
])
def test_parent_hold_and_quarantine_inheritance(parent_changes, child_state, archive):
    parent = _visibility(_material(**parent_changes))
    child = _visibility(_material(parent_material_id="parent"), parent_visibility=parent)
    assert child["state"] == child_state
    assert child["archive_available"] is archive


def test_parent_hold_does_not_downgrade_stronger_child_state():
    parent = _visibility(_material(needs_review=True))
    child = _visibility(_material(parent_material_id="parent", retracted=True), parent_visibility=parent)
    assert child["state"] == "retracted"
    assert "parent_review_hold" in child["reason_codes"]


@pytest.mark.parametrize("parent", [None, {}, {"version": "legacy"}])
def test_unresolved_parent_is_never_catalogue_eligible(parent):
    child = _visibility(_material(parent_material_id="missing-parent"), parent_visibility=parent)
    assert child["state"] == "unknown"
    assert "parent_visibility_unavailable" in child["reason_codes"]
    assert "ancestry_provenance_unresolved" in child["reason_codes"]
    assert child["archive_available"] is False


@pytest.mark.parametrize(("record", "reason"), [
    ({"needs_review": True}, "record_review_required"),
    ({"review_status": "pending"}, "record_review_required"),
    ({"validity_status": "excluded"}, "record_review_required"),
    ({"status": "under_review"}, "record_review_required"),
    ({"disputed": True}, "record_disputed"),
    ({"status": "disputed"}, "record_disputed"),
    ({"retracted": True}, "record_retracted"),
    ({"source_status": "withdrawn"}, "record_retracted"),
    ({"review_status": "retracted"}, "record_retracted"),
    ({"corrected": True}, "record_corrected"),
    ({"review_status": "corrected"}, "record_corrected"),
    ({"needs_review": "false"}, "record_review_metadata_invalid"),
])
def test_raw_negative_governance_conservatively_holds_material_without_pretending_source_adjudication(record, reason):
    visibility = _visibility(_material(records=[{"tc_kelvin": 10, "paper_id": "p", **record}]))
    assert visibility["state"] == "pending"
    assert visibility["archive_available"]
    assert not visibility["public_catalogue_eligible"]
    assert reason in visibility["reason_codes"]
    assert visibility["source_status"] == "active"
    assert visibility["scientific_acceptance"] is False


@pytest.mark.parametrize("record", [
    {"review_reason": "provenance_quarantine_new_source"},
    {"provenance_status": "quarantined"}, {"review_status": "quarantined"},
])
def test_retained_record_quarantine_closes_every_material_view(record):
    visibility = _visibility(_material(records=[record]))
    assert visibility["state"] == "quarantined"
    assert not visibility["archive_available"]
    assert "record_provenance_quarantined" in visibility["reason_codes"]


def test_raw_reviewed_approval_does_not_cancel_negative_record_governance():
    visibility = _visibility(_material(records=[{"needs_review": True, "reviewed": True, "review_status": "approved"}]))
    assert visibility["state"] == "pending"
    assert _visibility(_material(records=[{"reviewed": True, "review_status": "approved"}]))["scientific_acceptance"] is False


def test_governance_scan_budget_exhaustion_does_not_hide_a_late_quarantine():
    records = [{}] * 20_000 + [{"review_reason": "provenance_quarantine_nims"}]
    visibility = _visibility(_material(records=records))
    assert visibility["state"] == "unknown"
    assert not visibility["archive_available"]
    assert "record_governance_unresolved" in visibility["reason_codes"]


def test_parent_unresolved_provenance_closes_child_archive_without_relabeling_retraction():
    parent = _visibility(_material(parent_material_id="missing"), ancestry_error="missing_parent")
    child = _visibility(_material(parent_material_id="parent"), parent_visibility=parent)
    assert child["state"] == "unknown"
    assert not child["archive_available"]
    assert "ancestry_provenance_unresolved" in child["reason_codes"]
    assert "parent_provenance_quarantined" not in child["reason_codes"]


def test_review_revision_is_deterministic_order_independent_and_policy_sensitive():
    first = _visibility(source_statuses={"p": "published", "q": "corrected"})
    reordered = _visibility(source_statuses={"q": "corrected", "p": "published"})
    assert first["review_revision"] == reordered["review_revision"]
    assert first["review_revision"] != _visibility(source_statuses={"q": "corrected", "r": "published"})["review_revision"]
    assert _visibility()["review_revision"] != _visibility(anomaly_review=_assessment(year=2027))["review_revision"]
    assert _visibility()["review_revision"] != _visibility(_material(needs_review=True))["review_revision"]
    assert len(first["review_revision"]) == 64


def test_parent_revision_changes_child_revision_even_when_hold_is_unchanged():
    parent1 = _visibility(_material(needs_review=True))
    parent2 = _visibility(_material(needs_review=True), anomaly_review=_assessment(year=2027))
    first = _visibility(_material(parent_material_id="parent"), parent_visibility=parent1)
    second = _visibility(_material(parent_material_id="parent"), parent_visibility=parent2)
    assert first["state"] == second["state"] == "pending"
    assert first["review_revision"] != second["review_revision"]


def test_review_revision_changes_for_material_identity_and_update_revision():
    original = _visibility()
    assert original["review_revision"] != _visibility(_material(id="another-material"))["review_revision"]
    assert original["review_revision"] != _visibility(_material(updated_at="2026-09-06T12:00:00Z"))["review_revision"]


def test_material_visibility_is_derived_not_part_of_raw_result_identity():
    record = {"tc_kelvin": 20, "formula": "NbN", "pressure_gpa": 1}
    annotated = {**record, "visibility": _visibility()}
    assert legacy_result_id(record, scope_id="material-a") == legacy_result_id(annotated, scope_id="material-a")
    original = matching_result_references([record], ResultFilters(tc_min=10), scope_id="material-a")
    projected = matching_result_references([annotated], ResultFilters(tc_min=10), scope_id="material-a")
    assert original[0]["result_id"] == projected[0]["result_id"]


def test_policy_accepts_orm_like_objects_without_mutating_any_input():
    source, assessment, statuses = _material(), _assessment(), {"p": "published"}
    before = copy.deepcopy((source, assessment, statuses))
    expected = visibility_for_material(source, anomaly_review=assessment, source_statuses=statuses)
    actual = visibility_for_material(SimpleNamespace(**source), anomaly_review=assessment, source_statuses=statuses)
    assert actual == expected
    assert (source, assessment, statuses) == before


def test_safe_review_reason_ignores_forged_messages_and_codes():
    assert safe_public_review_reason({"reason_codes": ["private@example.com", "material_review_required"],
                                      "reason_messages": ["Private note"]}) == "This material is awaiting review."
    assert safe_public_review_reason({"reason_codes": "private"}) is None


def test_recursive_review_metadata_projection_preserves_science_not_known_private_keys():
    source = {
        "tc_kelvin": "39 ± 1 K", "formula": "MgB2", "paper_id": "p",
        "admin_decision": {"reviewer": "private@example.com"},
        "scientific_values": {"tc_kelvin": {"raw_value": "39 ± 1 K", "review_notes": "private"}},
        "details": [{"reviewer_id": "private", "name": "Private Person", "email": "private@example.com",
                     "pressure_gpa": 1, "visibility": {"review_revision": "a" * 64}}],
        "INTERNAL-REVIEW": {"note": "private"}, "curatorNote": "private",
    }
    before = copy.deepcopy(source)
    projected = sanitize_review_metadata(source)
    assert source == before
    assert projected["tc_kelvin"] == "39 ± 1 K"
    assert projected["scientific_values"]["tc_kelvin"] == {"raw_value": "39 ± 1 K"}
    assert projected["details"] == [{"pressure_gpa": 1, "visibility": {"review_revision": "a" * 64}}]
    assert "private" not in json.dumps(projected).lower()


def test_review_metadata_projection_is_cycle_and_depth_bounded():
    cyclic = {"formula": "Nb"}
    cyclic["loop"] = cyclic
    assert sanitize_review_metadata(cyclic)["loop"] == {"redacted": "cyclic_metadata"}
    deep = {"tc_kelvin": 20}
    for _ in range(30):
        deep = {"nested": deep}
    assert "review_metadata_projection_limit" in json.dumps(sanitize_review_metadata(deep))
    assert len(sanitize_review_metadata([0] * 50_000)) <= 20_001


def test_archive_gate_rejects_stale_policy_and_quarantine_even_if_eligibility_forged():
    current = _visibility()
    assert not visibility_allows_view({**current, "version": "old"}, include_archive=True)
    assert not visibility_allows_view({**current, "state": "quarantined"}, include_archive=True)
    assert not visibility_allows_view({**current, "archive_available": False}, include_archive=True)
    assert not visibility_allows_view({**current, "state": "pending"})
    assert not visibility_allows_view({**current, "state": "unknown-status"}, include_archive=True)
    assert not visibility_allows_view(_visibility(_material(needs_review=True)), include_archive="false")


def test_inconsistent_parent_dto_never_passes_default_catalogue():
    child = _visibility(_material(parent_material_id="parent"), parent_visibility={**_visibility(), "state": "pending"})
    assert child["state"] == "unknown"
    assert "parent_visibility_unavailable" in child["reason_codes"]


@pytest.mark.parametrize(("raw", "normalized"), [
    (" Published ", "active"), ("WITHDRAWN", "retracted"), ("corrected", "corrected"),
    ("reviewed", "unknown"), (True, "unknown"), (None, "unknown"),
])
def test_source_status_normalization_is_explicit(raw, normalized):
    assert normalize_source_status(raw) == normalized
