"""SC03 source preservation and property-scoped selections; no service calls."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from ingestion.anomaly_review import ANOMALY_POLICY_VERSION
from ingestion.extract.materials_aggregator import _derive_summary, _OverrideEntry
from ingestion.property_evidence import build_property_evidence


def record(paper="synthetic:a", **fields):
    return {"formula": "MgB2", "paper_id": paper, "tc_kelvin": 39.0,
            "measurement": "resistivity", "evidence_type": "primary_experimental",
            "confidence": 0.95, "year": 2024, **fields}


def test_high_tc_retained_with_unrelated_hc2_and_structure():
    rows = [record(tc_kelvin=400.0, pressure_gpa=200.0, hc2_tesla=14.25,
                   hc2_conditions="c-axis at 2 K", lattice_a=3.0, lattice_c=7.0)]
    before = deepcopy(rows)
    summary = _derive_summary("MgB2", rows)
    assert summary["records"] == rows == before
    assert summary["tc_max"] is summary["tc_max_experimental"] is None
    assert summary["hc2_tesla"] == 14.25
    assert summary["hc2_conditions"] == "c-axis at 2 K"
    assert summary["lattice_params"] == {"a": 3.0, "c": 7.0}
    assert summary["needs_review"] is True
    review = summary["anomaly_review"]
    assert review["version"] == ANOMALY_POLICY_VERSION
    assert review["raw_preserved"] and not review["scientific_acceptance"]
    assert any(f["rule_id"] == "tc_high_review" for f in review["records"][0]["findings"])


def test_cap_selects_existing_lower_source_not_cap_value():
    rows = [record("a", tc_kelvin=60), record("b", tc_kelvin=39)]
    summary = _derive_summary("MgB2", rows, overrides=[
        _OverrideEntry("tc_max", "45", True, "sensitive curator free text", None,
                       reference_id="manual_overrides:12")])
    assert summary["tc_max"] == 39
    assert summary["records"] == rows
    assert summary["total_papers"] == 2
    assert summary["anomaly_context"]["compound_thresholds"] == [{
        "field": "tc_max", "threshold": 45.0, "reference_id": "manual_overrides:12",
        "mode": "upper_reference"}]
    assert "sensitive" not in str(summary["anomaly_context"])
    assert "sensitive" not in str(summary["anomaly_review"])


def test_exact_numeric_override_needs_revision_and_is_not_applied():
    rows = [record(tc_kelvin=39, hc2_tesla=10)]
    summary = _derive_summary("MgB2", rows, overrides=[
        _OverrideEntry("tc_max", "45", False, "a citation does not authorize correction", None)])
    assert summary["tc_max"] is None
    assert summary["tc_max_experimental"] == 39  # different, explicitly unaffected view
    assert summary["hc2_tesla"] == 10
    assert summary["records"] == rows
    assert "legacy_numeric_override_requires_revision" in summary["anomaly_review"]["rule_counts"]


@pytest.mark.parametrize("value", ["NaN", "unparseable old value"])
def test_malformed_numeric_legacy_override_cannot_disappear_and_expose_value(value):
    rows = [record()]
    summary = _derive_summary("MgB2", rows,
                              overrides=[_OverrideEntry("tc_max", value, False, "ref", None)])
    assert summary["tc_max"] is None
    assert summary["records"] == rows
    assert summary["anomaly_context"]["compound_thresholds"][0]["threshold"] is None
    assert "review_context_unresolved" in summary["anomaly_review"]["rule_counts"]


def test_unknown_legacy_override_target_is_retained_as_unresolved_not_discarded():
    rows = [record(hc2_tesla=10)]
    summary = _derive_summary("MgB2", rows,
                              overrides=[_OverrideEntry("unrecognized_target", "45", True, "ref", None)])
    assert summary["tc_max"] is summary["hc2_tesla"] is None
    assert summary["records"] == rows
    assert summary["anomaly_context"]["compound_thresholds"][0]["field"] == "unrecognized_target"
    assert "review_context_unresolved" in summary["anomaly_review"]["rule_counts"]


def test_ambient_cap_does_not_change_high_pressure_headline_or_create_zero():
    rows = [record("a", tc_kelvin=40, pressure_gpa=5),
            record("b", tc_kelvin=39, pressure_gpa=0, pressure_state="explicit_ambient")]
    summary = _derive_summary("MgB2", rows, overrides=[
        _OverrideEntry("tc_ambient", "35", True, "legacy reference", None)])
    assert summary["tc_max"] == 40
    assert summary["tc_ambient"] is summary["ambient_sc"] is None
    assert summary["records"] == rows


def test_tc_max_reference_does_not_copy_ambient_value_back_into_excluded_view():
    summary = _derive_summary("MgB2", [record(pressure_gpa=0, pressure_state="explicit_ambient")],
                              overrides=[_OverrideEntry("tc_max", "35", True, "ref", None)])
    assert summary["tc_max"] is None
    assert summary["tc_ambient"] == 39


@pytest.mark.parametrize("value", [0.001, 39.123456789])
def test_source_precision_and_low_positive_tc_are_not_clipped_or_rounded(value):
    summary = _derive_summary("MgB2", [record(tc_kelvin=value, hc2_tesla=12.123456789)])
    assert summary["tc_max"] == value
    assert summary["hc2_tesla"] == 12.123456789


def test_cached_scalar_never_overrides_original_bound_or_unit():
    rows = [record(tc_kelvin=39, scientific_values={"tc_kelvin": {"raw_value": "<5 K"}})]
    assert _derive_summary("MgB2", rows)["tc_max"] is None
    summary = _derive_summary("MgB2", [record(tc_kelvin=39, tc_kelvin_unit="mK")])
    assert summary["tc_max"] == 0.039


def test_negative_outcome_does_not_become_positive_catalogue_measurement():
    summary = _derive_summary("MgB2", [record(result_status="not_detected", tc_kelvin=39)])
    assert summary["tc_max"] is summary["tc_max_experimental"] is None


def test_computed_mgb2_80_k_is_reviewed_not_labeled_physical_impossibility():
    rows = [record(tc_kelvin=80, measurement="DFT", evidence_type="primary_theoretical")]
    summary = _derive_summary("MgB2", rows)
    assert summary["tc_max_theoretical"] is summary["tc_max"] is None
    assert summary["records"] == rows
    finding = next(f for f in summary["anomaly_review"]["records"][0]["findings"]
                   if f["rule_id"] == "tc_family_reference_review")
    assert finding["applicability"]["physical_limit"] is False


def test_invalid_lattice_group_cannot_sneak_back_through_crystal_metadata():
    rows = [record(lattice_a=3.0, lattice_c="not-a-number", crystal_structure="hexagonal")]
    summary = _derive_summary("MgB2", rows)
    assert summary["lattice_params"] is None
    assert summary["tc_max"] == 39
    assert summary["records"] == rows


def test_summary_maxima_remain_supported_in_same_policy_context():
    rows = [record("a", hc2_tesla=100), record("b", hc2_tesla=20, hc2_conditions="2 K")]
    summary = _derive_summary("MgB2", rows,
                              overrides=[_OverrideEntry("hc2_tesla", "50", True, "ref", None)])
    assert summary["hc2_tesla"] == 20
    assert summary["hc2_conditions"] == "2 K"
    bundle = build_property_evidence(rows, scope_id="mat:MgB2", legacy_summary=summary,
                                     anomaly_context=summary["anomaly_context"])
    assert bundle["properties"]["hc2_tesla"]["selected"]["value"] == 20
    assert bundle["properties"]["tc_max"]["selected"]["value"] == 39


def test_parent_snapshot_does_not_mutate_or_reattach_historical_records():
    rows = [record()]
    before = deepcopy(rows)
    first = _derive_summary("MgB2", rows)
    second = _derive_summary("MgB2", rows)
    assert first == second
    assert first["records"] == before


def test_one_explicit_year_reference_is_shared_without_mutating_future_raw_year():
    rows = [record(year=2099)]
    summary = _derive_summary("MgB2", rows, current_year=2026)
    assert summary["anomaly_context"]["current_year"] == 2026
    assert "record_year_review" in summary["anomaly_review"]["rule_counts"]
    assert summary["arxiv_year"] is None
    assert summary["tc_max"] == 39  # chronology review does not erase unrelated Tc
    assert summary["records"] == rows


@pytest.mark.parametrize("field,value,expected_origin", [
    ("tc_max", "35", "Observed"),
    ("tc_max_experimental", "35", "Observed"),
])
def test_origin_pool_is_preserved_when_view_references_split_headline_and_split_maximum(field, value, expected_origin):
    rows = [record("observed-high", tc_kelvin=39), record("observed-low", tc_kelvin=30),
            record("computed-tie", tc_kelvin=30, measurement="DFT", evidence_type="primary_theoretical")]
    summary = _derive_summary("MgB2", rows,
                              overrides=[_OverrideEntry(field, value, True, "ref", None)])
    assert summary["tc_max"] != summary["tc_max_experimental"]
    bundle = build_property_evidence(rows, scope_id="mat:MgB2", legacy_summary=summary,
                                     anomaly_context=summary["anomaly_context"])
    assert bundle["properties"]["tc_max"]["selected"]["origin"]["knowledge_origin"] == expected_origin


def test_driver_retains_high_and_low_numeric_records_but_keeps_source_quality_filters(monkeypatch):
    """Exercise the real driver against a fake SQL executor, never a database."""
    from ingestion.extract import materials_aggregator as aggregator

    input_records = [record(tc_kelvin=400), record(tc_kelvin=0.001),
                     record(tc_kelvin=40, evidence_type="cited"),
                     record(tc_kelvin=38, confidence=0.1)]
    before = deepcopy(input_records)

    class Result:
        def __init__(self, rows): self.rows = rows
        def first(self): return self.rows[0] if self.rows else None
        def all(self): return self.rows

    class FakeDatabase:
        def __init__(self): self.inserts = []
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def commit(self): pass
        async def execute(self, statement):
            if statement.is_insert:
                self.inserts.append(statement.compile().params)
                return Result([])
            query = str(statement)
            if "FROM pipeline_state" in query:
                return Result([(str(aggregator.NORMALIZE_SCHEMA_VERSION),)])
            if "FROM papers" in query:
                return Result([("arxiv:synthetic", "arxiv", None, None, input_records, "T1"),
                               ("arxiv:excluded-tier", "arxiv", None, None, [record()], "T4")])
            return Result([])

    db = FakeDatabase()
    monkeypatch.setattr(aggregator, "_session_factory", lambda: lambda: db)
    assert asyncio.run(aggregator.aggregate_from_papers()) == 1
    assert len(db.inserts) == 1
    inserted = db.inserts[0]
    assert [r["tc_kelvin"] for r in inserted["records"]] == [400, 0.001]
    assert all(r["confidence"] == 0.95 for r in inserted["records"])
    assert inserted["tc_max"] == 0.001
    assert inserted["anomaly_review"]["counts"]["review_required"] == 1
    assert input_records == before
