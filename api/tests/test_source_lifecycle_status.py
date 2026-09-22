"""Pure negative source overlays: retained bibliography is never acceptance."""
from pathlib import Path

import pytest

from services.material_visibility import visibility_for_material
from services.source_lifecycle_status import (
    combined_lifecycle_revision,
    lifecycle_review_required,
    lifecycle_status,
    overlay_source_lifecycle,
)
from services.source_visibility import occurrence_visibility, source_visibility


def test_source_overlay_retains_original_bibliography_but_holds_reported_support():
    source = overlay_source_lifecycle("published", "a" * 64)
    value = source_visibility(source)
    assert value["source_status"] == "active"
    assert value["bibliography_available"] is True
    assert value["reported_claim_filter_eligible"] is False
    assert value["warning_codes"] == ["source_lifecycle_review_required"]
    record = occurrence_visibility({}, paper_status=source)
    assert record["state"] == "pending"
    assert record["archive_available"] is True
    assert not record["reported_claim_filter_eligible"]
    assert "source_lifecycle_review_required" in record["reason_codes"]


@pytest.mark.parametrize("payload", ({}, {"status": "published"},
    {"status": "published", "lifecycle_review_required": False, "lifecycle_revision": "a" * 64},
    {"status": "published", "lifecycle_review_required": True, "lifecycle_revision": "forged"}))
def test_malformed_overlay_fails_closed_without_fake_retraction(payload):
    assert lifecycle_review_required(payload)
    assert lifecycle_status(payload) is None
    value = occurrence_visibility({}, paper_status=payload)
    assert value["state"] == "pending"
    assert not value["reported_claim_filter_eligible"]


def test_overlay_preserves_original_retraction_precedence():
    value = occurrence_visibility({}, paper_status=overlay_source_lifecycle("retracted", "a" * 64))
    assert value["state"] == "retracted"


def test_material_revision_binds_lifecycle_head_even_when_both_revisions_held():
    material = {"id": "material:synthetic", "status": "active_research", "records": [],
                "needs_review": False, "disputed": False, "retracted": False}
    anomaly = {"version": "anomaly-review/1.0.0", "needs_review": False, "counts": {}}
    first, second = [visibility_for_material(material, anomaly_review=anomaly,
        source_statuses={"paper:synthetic": overlay_source_lifecycle("published", digest * 64)})
        for digest in ("a", "b")]
    assert first["state"] == second["state"] == "pending"
    assert first["review_revision"] != second["review_revision"]
    assert "source_lifecycle_review_required" in first["reason_codes"]


def test_shared_direct_and_work_bindings_are_order_stable_and_distinguish_dependencies():
    assert combined_lifecycle_revision("a" * 64) == "a" * 64
    assert combined_lifecycle_revision() is None
    assert combined_lifecycle_revision("a" * 64, "b" * 64) != combined_lifecycle_revision("b" * 64, "a" * 64)
    assert combined_lifecycle_revision(None, "a" * 64) != "a" * 64
    with pytest.raises(ValueError):
        combined_lifecycle_revision("bad", "a" * 64)


def test_repeated_source_statuses_with_distinct_heads_remain_sortable():
    material = {"id": "material:synthetic", "status": "active_research", "records": [], "needs_review": False}
    anomaly = {"version": "anomaly-review/1.0.0", "needs_review": False, "counts": {}}
    statuses = [overlay_source_lifecycle("published", digest * 64) for digest in ("a", "b")]
    forward = visibility_for_material(material, anomaly_review=anomaly, source_statuses=statuses)
    reverse = visibility_for_material(material, anomaly_review=anomaly, source_statuses=list(reversed(statuses)))
    assert forward == reverse
    assert forward["state"] == "pending"


def test_shared_pure_overlay_contract_is_byte_identical():
    root = Path(__file__).resolve().parents[2]
    assert (root / "api/services/source_lifecycle_status.py").read_bytes() == (
        root / "ingestion/ingestion/source_lifecycle_status.py").read_bytes()
