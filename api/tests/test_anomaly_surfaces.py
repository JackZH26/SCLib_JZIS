"""SC03 raw preservation, cross-surface field gates and nightly idempotence."""
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from models.db import Material
from models.search import MaterialDetail, MaterialSummary
from services.anomaly_review import ANOMALY_POLICY_VERSION
from services.audit_rules import ANOMALY_RULE, RULES
from services.audit_runner import _run_rule
from services.material_anomalies import retained_record_archive, review_context
from services.scientific_filters import ResultFilters, matching_result_references
from services.timeline_points import extract_timeline_points


def material(records, **kwargs):
    return {"id": "mat:anomaly-test", "formula": "X", "formula_normalized": "X",
            "formula_latex": None, "family": None, "subfamily": None, "arxiv_year": None,
            "status": "active", "tc_max": 60, "records": records, "total_papers": 1, **kwargs}


def test_cap_never_becomes_measurement_and_archive_preserves_actual_raw():
    row = material([{"tc_kelvin": 60, "paper_id": "paper:a", "year": 2026}], tc_max=45,
                   anomaly_context={"compound_thresholds": [{"field": "tc_max", "threshold": 45,
                       "reference_id": "manual_overrides:1", "mode": "upper_reference"}]})
    before = deepcopy(row)
    detail = MaterialDetail.model_validate(row)
    summary = MaterialSummary.model_validate(row)
    assert detail.tc_max is summary.tc_max is None
    assert detail.records[0]["tc_kelvin"] == 60
    assert detail.raw_archive["records"][0]["raw"]["tc_kelvin"] == 60
    assert detail.raw_archive["version"] == ANOMALY_POLICY_VERSION
    assert detail.anomaly_review["needs_review"]
    assert summary.anomaly_review["records"] == []
    assert row == before


def test_high_value_is_retained_but_not_selected_filtered_or_plotted():
    record = {"tc_kelvin": 400, "pressure_gpa": 200, "year": 2026,
              "knowledge_origin": "Computed", "paper_id": "paper:high"}
    row = material([record], tc_max=400)
    detail = MaterialDetail.model_validate(row)
    assert detail.tc_max is None
    assert detail.property_evidence["properties"]["tc_max"]["evidence"][0]["value"] == 400
    assert detail.records[0]["tc_kelvin"] == 400
    assert detail.anomaly_review["scientific_acceptance"] is False
    assert not matching_result_references([record], ResultFilters(tc_min=300), scope_id=row["id"])
    assert not extract_timeline_points(row["id"], [record], {}, current_year=2026)


def test_positive_millikelvin_is_not_deleted_and_old_1980_floor_is_retired():
    record = {"tc_kelvin": 0.001, "year": 1911, "paper_id": "paper:low"}
    detail = MaterialDetail.model_validate(material([record], tc_max=0.001))
    assert detail.tc_max == 0.001
    assert not detail.anomaly_review["needs_review"]
    assert extract_timeline_points("mat:low", [record], {}, current_year=2026)[0].tc_kelvin == 0.001


def test_raw_archive_is_bounded_allowlisted_and_not_full_source_export():
    record = {"tc": "400 K", "pressure": "1 GPa", "source_quote": "private source text",
              "reviewer_email": "private@invalid", "lattice_params": {"a": 3, "secret": "private"},
              "scientific_values": {"tc_kelvin": {"raw_value": {"secret": "private"}, "source_context": "private"}}}
    result = retained_record_archive([record] * 102, scope_id="mat:archive", context=review_context({}))
    encoded = json.dumps(result, allow_nan=False)
    assert result["returned"] == 100 and result["total"] == 102 and result["truncated"]
    assert result["records"][0]["raw"]["tc"] == "400 K"
    assert "private" not in encoded and "source_quote" not in encoded


@pytest.mark.asyncio
async def test_nightly_policy_is_idempotent_preserves_raw_and_does_not_trust_legacy_override(db_session):
    suffix = uuid4().hex
    raw = [{"tc_kelvin": 400, "paper_id": "paper:high"}]
    pending = Material(id=f"mat:anomaly-{suffix}", formula="X", formula_normalized=f"x-{suffix}",
                       records=raw, tc_max=45, needs_review=False, admin_decision={"action": "override", "rule": "tc_old"})
    quarantine = Material(id=f"mat:quarantine-{suffix}", formula="Y", formula_normalized=f"y-{suffix}",
                          records=raw, tc_max=400, needs_review=True, review_reason="provenance_quarantine_nims")
    held = Material(id=f"mat:held-{suffix}", formula="Z", formula_normalized=f"z-{suffix}",
                    records=[{"tc_kelvin": 2}], needs_review=True, review_reason="legacy_governance_hold")
    db_session.add_all([pending, quarantine, held])
    await db_session.flush()
    first = await _run_rule(db_session, ANOMALY_RULE)
    snapshot = deepcopy(pending.anomaly_review)
    second = await _run_rule(db_session, ANOMALY_RULE)
    assert first == second and first["flagged"] >= 2
    assert pending.anomaly_review == snapshot
    assert pending.records == raw and pending.tc_max == 45 and pending.needs_review
    assert pending.review_reason == ANOMALY_RULE.name
    assert quarantine.review_reason == "provenance_quarantine_nims"
    assert held.needs_review and held.review_reason == "legacy_governance_hold"
    await db_session.rollback()  # Do not affect other tests' retained materials.


def test_numeric_audit_registry_has_no_clipping_or_destructive_sql_rules():
    retired = {"tc_exceeds_family_cap", "tc_at_ambient_above_record", "implausible_pressure",
               "tc_exceeds_compound_cap", "hydride_low_pressure_high_tc", "ambient_sc_with_high_pressure",
               "record_year_out_of_range"}
    assert not retired.intersection(rule.name for rule in RULES)
    assert ANOMALY_POLICY_VERSION in ANOMALY_RULE.name


def test_timeline_rejects_noninteger_year_and_does_not_plot_review_required_pressure():
    for record in (
        {"tc_kelvin": 10, "year": 2020.5},
        {"tc_kelvin": 10, "measurement_year": 2020.5},
        {"tc_kelvin": 10, "year": 2020, "pressure_gpa": 900},
    ):
        assert not extract_timeline_points("mat:point", [record], {}, current_year=2026)


def test_review_context_preserves_selection_marker_and_uses_explicit_year():
    from datetime import UTC, datetime
    context = review_context({"anomaly_context": {
        "selection_policy": "atomic-anomaly-aggregation/1.0.0", "current_year": 1900,
    }})
    assert context["selection_policy"] == "atomic-anomaly-aggregation/1.0.0"
    assert context["current_year"] == datetime.now(UTC).year


@pytest.mark.asyncio
async def test_pending_timeline_cannot_publish_quarantined_material(client, db_session):
    from routers.timeline import _build_timeline_fallback
    from services.timeline_projection import (
        fetch_projected_timeline_points,
        refresh_timeline_projection,
    )
    suffix = uuid4().hex
    row = Material(id=f"mat:timeline-quarantine-{suffix}", formula=f"Q{suffix}",
                   formula_normalized=f"q-{suffix}", needs_review=True,
                   review_reason="provenance_quarantine_nims",
                   records=[{"tc_kelvin": 10, "year": 2020}])
    db_session.add(row)
    await db_session.flush()
    fallback = await _build_timeline_fallback(family=None, include_pending=True, experimental_only=False,
                        only_aps=False, max_points=None, offset=0, limit=None, db=db_session)
    assert row.formula not in [point.material for point in fallback.points]
    await refresh_timeline_projection(db_session)
    projected = await fetch_projected_timeline_points(db_session, family=None, include_pending=True,
                                                     experimental_only=False, only_aps=False)
    assert projected is not None
    assert row.formula not in [point.material for point in projected.points]
    await db_session.rollback()
