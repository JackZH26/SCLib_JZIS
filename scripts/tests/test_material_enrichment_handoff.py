"""Packaged primary Tc handoffs preserve criteria without granting review."""

from __future__ import annotations

import json
import sys
import uuid
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "ingestion"))

from ingestion.claims.mapper import map_record_to_claim  # noqa: E402
from services import material_enrichment as enrich  # noqa: E402


def current_candidates() -> list[dict]:
    seed = json.loads(
        (ROOT / "api/services/resources/material_enrichment_seed.json").read_bytes()
    )
    return [candidate for report in seed["reports"] for candidate in report["candidates"]]


def map_handoff(row: dict) -> dict:
    # Pure mapper input only; this ID does not assert a registered DB snapshot.
    return map_record_to_claim(
        row["record"],
        material_id=row["material_id"],
        material_formula=row["record"]["formula_raw"],
        source_snapshot_id=uuid.uuid5(uuid.NAMESPACE_URL, "test:criterion-handoff-regression"),
    )


def test_primary_onset_and_zero_criteria_stay_distinct_through_typed_mapper():
    rows = enrich.pending_tc_records(current_candidates())
    known = [
        row for row in rows if row["record"]["tc_criterion"] in {"onset", "zero_resistance"}
    ]
    assert len(known) == 2
    assert {
        (row["record"]["tc_criterion"], map_handoff(row)["value_kelvin"]) for row in known
    } == {("onset", 23.0), ("zero_resistance", 21.5)}
    for row in known:
        claim = map_handoff(row)
        assert claim["tc_definition"] == row["record"]["tc_criterion"]
        assert claim["validity_status"] == "pending"
        assert row["record"]["tc_criterion"] == claim["raw_record"]["tc_criterion"]
        assert row["scientific_acceptance"] is False
        assert row["database_changed"] is False


def test_unknown_criterion_does_not_promote_conditions_origin_or_review():
    rows = enrich.pending_tc_records(current_candidates())
    unknown = [row for row in rows if row["record"]["tc_criterion"] == "unknown"]
    assert len(unknown) == 7
    for row in unknown:
        claim = map_handoff(row)
        assert claim["tc_definition"] == "unknown"
        assert claim["validity_status"] == "pending"
        assert (
            claim["extraction_metadata"]["result_classification"]["knowledge_origin"]
            == row["record"]["knowledge_origin"]
        )
        assert row["scientific_acceptance"] is False
        assert row["ml_training_approved"] is False
        assert row["public_release"] is False
        if row["record"]["pressure_state"] == "not_reported":
            assert claim["pressure_state"] == "not_reported"
            assert claim["pressure_gpa"] is None
    ysc = next(map_handoff(row) for row in rows if row["material_id"] == "mat:ysch10")
    assert ysc["value_kelvin"] == 116.0
    assert ysc["pressure_gpa"] == 140.0
    assert ysc["extraction_metadata"]["result_classification"]["knowledge_origin"] == "Unknown"


def test_handoff_preserves_candidate_identity_and_source_provenance():
    candidates = current_candidates()
    before = deepcopy(candidates)
    rows = enrich.pending_tc_records(candidates)
    assert candidates == before
    assert len(rows) == 9
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    for row in rows:
        record = row["record"]
        candidate = by_id[record["enrichment_candidate_id"]]
        assert record["tc_definition"] == record["tc_criterion"]
        assert record["tc_definition"] == candidate["subject"]["tc_criterion"]
        assert record["enrichment_provenance"]["source"] == candidate["source"]
        assert (
            record["enrichment_provenance"]["retained_result_refs"]
            == candidate["retained_result_refs"]
        )
        assert record["enrichment_provenance"]["source_content_checked"] is False
        assert record["enrichment_provenance"]["material_state_reviewed"] is False
        assert row["import_status"] == "requires_source_and_state_review"
