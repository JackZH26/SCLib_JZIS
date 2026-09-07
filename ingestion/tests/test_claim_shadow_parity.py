"""Hard, offline parity contracts for the Phase-1 claim plan."""

from __future__ import annotations

import copy
import json
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.plan_typed_claim_backfill import build_backfill_plan

from ingestion.claims.shadow_parity import build_shadow_parity_report


def _rows(
    record: dict[str, object] | None = None,
    *,
    paper_status: str = "published",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    paper_id = "arxiv:2306.07275"
    papers: list[dict[str, object]] = [
        {
            "id": paper_id,
            "source": "arxiv",
            "arxiv_id": "2306.07275",
            "title": "A parity test work",
            "date_submitted": "2023-06-12",
            "status": paper_status,
        }
    ]
    material_record: dict[str, object] = {
        "paper_id": paper_id,
        "tc_kelvin": 39.0,
        "pressure_gpa": 0.0,
        "pressure_state": "explicit_ambient",
        "ambient_sc": True,
        "measurement": "resistivity",
        "source_role": "primary",
    }
    if record is not None:
        material_record = record
    materials: list[dict[str, object]] = [
        {
            "id": "mat:mgb2",
            "formula": "MgB2",
            "records": [material_record],
        }
    ]
    return materials, papers


def _plan(
    materials: list[dict[str, object]],
    papers: list[dict[str, object]],
    *,
    existing_paper_work: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return build_backfill_plan(
        materials,
        papers,
        source_snapshot_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        existing_paper_work=existing_paper_work or [],
    )


def _failure_codes(report: dict[str, object]) -> set[str]:
    return {
        row["code"]
        for row in report["gate_failures"]  # type: ignore[index]
    }


def test_empty_snapshot_is_deterministic_but_never_false_green() -> None:
    plan = _plan([], [])

    first = build_shadow_parity_report([], [], plan)
    second = build_shadow_parity_report([], [], copy.deepcopy(plan))

    assert first == second
    assert first["gate_status"] == "fail"
    assert _failure_codes(first) == {
        "empty_material_snapshot",
        "empty_source_record_snapshot",
    }
    assert first["reconciliation"]["unaccounted_records"] == 0
    assert first["deferred_parity"]["timeline"]["status"] == "deferred"
    assert first["deferred_parity"]["material_headlines"]["status"] == "deferred"
    # The report is directly suitable for a deterministic JSON artifact.
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_exact_observation_passes_all_hard_parity_checks() -> None:
    materials, papers = _rows()
    plan = _plan(materials, papers)

    report = build_shadow_parity_report(materials, papers, plan)

    assert report["gate_status"] == "pass"
    assert report["gate_failures"] == []
    assert report["reconciliation"] == {
        "independent_input_records": 1,
        "planner_input_records": 1,
        "unique_claims": 1,
        "exact_duplicate_records": 0,
        "record_failures": 0,
        "accounted_records": 1,
        "unaccounted_records": 0,
        "claim_raw_record_matches": 1,
        "unconsumed_source_records": 0,
    }
    assert report["hard_semantics"]["tc"]["preserved_values"] == 1
    assert report["hard_semantics"]["pressure"]["manufactured_values"] == 0
    assert report["distributions"]["evidence_role"] == {
        "primary_experimental": 1,
    }
    assert report["distributions"]["pressure_state"] == {
        "explicit_ambient": 1,
    }


def test_missing_tc_and_pressure_stay_missing_and_never_become_negative() -> None:
    materials, papers = _rows(
        {
            "paper_id": "arxiv:2306.07275",
            "measurement": "resistivity",
        }
    )
    plan = _plan(materials, papers)

    report = build_shadow_parity_report(materials, papers, plan)

    assert report["gate_status"] == "pass"
    assert report["hard_semantics"]["pressure"]["missing_source_values"] == 1
    assert report["hard_semantics"]["pressure"]["manufactured_values"] == 0
    assert report["hard_semantics"]["negative_results"]["claims"] == 0
    assert report["distributions"]["result_status"] == {"unknown": 1}
    assert report["distributions"]["value_relation"] == {"unreported": 1}
    assert report["distributions"]["pressure_state"] == {"not_reported": 1}


def test_legacy_zero_without_ambient_evidence_is_preserved_as_ambiguous() -> None:
    materials, papers = _rows(
        {
            "paper_id": "arxiv:2306.07275",
            "tc_kelvin": 39.0,
            "pressure_gpa": 0.0,
            "measurement": "resistivity",
        }
    )
    plan = _plan(materials, papers)

    report = build_shadow_parity_report(materials, papers, plan)

    assert report["gate_status"] == "pass"
    assert report["hard_semantics"]["pressure"]["ambiguous_zero_values"] == 1
    assert report["hard_semantics"]["pressure"]["preserved_finite_nonnegative_values"] == 1
    assert report["distributions"]["mapper_warnings"] == {
        "legacy_zero_pressure_not_explicitly_ambient": 1,
        "legacy_field_unit_assumed_gpa": 1,
        "result_availability_not_source_revision_verified": 1,
    }


def test_explicit_negative_is_valid_but_accepted_negative_requires_tmin() -> None:
    materials, papers = _rows(
        {
            "paper_id": "arxiv:2306.07275",
            "result_status": "not_detected",
            "minimum_temperature_k": 1.8,
            "pressure_gpa": 5.0,
            "measurement": "resistivity",
        }
    )
    plan = _plan(materials, papers)
    report = build_shadow_parity_report(materials, papers, plan)

    assert report["gate_status"] == "pass"
    assert report["hard_semantics"]["negative_results"] == {
        "claims": 1,
        "implicit_claims": 0,
        "missing_minimum_temperature": 0,
        "accepted_missing_minimum_temperature": 0,
    }

    tampered = copy.deepcopy(plan)
    tampered_claim = tampered["claims"][0]
    tampered_claim["minimum_temperature_k"] = None
    tampered_claim["validity_status"] = "accepted"
    failed = build_shadow_parity_report(materials, papers, tampered)

    assert failed["gate_status"] == "fail"
    assert "accepted_negative_missing_tmin" in _failure_codes(failed)


def test_tampering_detects_snapshot_work_retraction_tc_pressure_and_negative_errors() -> None:
    materials, papers = _rows(
        {
            "paper_id": "arxiv:2306.07275",
            "tc_kelvin": 39.0,
            "measurement": "resistivity",
        },
        paper_status="retracted",
    )
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    claim = tampered["claims"][0]
    claim.update(
        {
            "source_snapshot_id": uuid.uuid4(),
            "work_id": None,
            "value_kelvin": 40.0,
            "pressure_state": "explicit_ambient",
            "pressure_gpa": 0.0,
            "result_status": "not_detected",
            "property_type": "non_transition",
            "value_relation": "unreported",
            "validity_status": "pending",
        }
    )

    report = build_shadow_parity_report(materials, papers, tampered)
    codes = _failure_codes(report)

    assert report["gate_status"] == "fail"
    assert {
        "claim_snapshot_mismatch",
        "claim_paper_work_mismatch",
        "retraction_propagation_mismatch",
        "finite_source_tc_not_preserved",
        "missing_pressure_was_manufactured",
        "implicit_negative_claim",
    } <= codes


def test_planner_failure_is_accounted_but_still_blocks_the_gate() -> None:
    materials = [
        {
            "id": "mat:unknown-paper",
            "formula": "Nb",
            "records": [{"paper_id": "arxiv:missing", "tc_kelvin": 9.2}],
        }
    ]
    plan = _plan(materials, [])

    report = build_shadow_parity_report(materials, [], plan)

    assert report["reconciliation"]["accounted_records"] == 1
    assert report["reconciliation"]["unaccounted_records"] == 0
    assert report["gate_status"] == "fail"
    assert _failure_codes(report) == {"plan_failures_present"}


def test_distinct_claim_loss_cannot_be_hidden_as_an_exact_duplicate() -> None:
    materials, papers = _rows()
    materials[0]["records"] = [
        {
            "paper_id": "arxiv:2306.07275",
            "tc_kelvin": 39.0,
            "measurement": "resistivity",
        },
        {
            "paper_id": "arxiv:2306.07275",
            "tc_kelvin": 40.0,
            "measurement": "resistivity",
        },
    ]
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    tampered["claims"].pop()
    tampered["summary"]["unique_claims"] = 1
    tampered["summary"]["exact_duplicate_records"] = 1

    report = build_shadow_parity_report(materials, papers, tampered)

    assert report["gate_status"] == "fail"
    assert {
        "exact_duplicate_count_mismatch",
        "record_accounting_mismatch",
        "unconsumed_source_records",
    } <= _failure_codes(report)


def test_claim_identity_and_full_mapper_payload_are_recomputed() -> None:
    materials, papers = _rows()
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    claim = tampered["claims"][0]
    claim["id"] = uuid.uuid4()
    claim["source_record_hash"] = "f" * 64
    claim["semantic_fingerprint"] = "e" * 64
    claim["value_kelvin"] = 40.0

    report = build_shadow_parity_report(materials, papers, tampered)

    assert report["gate_status"] == "fail"
    assert {
        "claim_source_hash_mismatch",
        "claim_deterministic_id_mismatch",
        "claim_mapper_replay_mismatch",
        "finite_source_tc_not_preserved",
    } <= _failure_codes(report)


def test_claim_cannot_drop_source_paper_and_work_lineage() -> None:
    materials, papers = _rows()
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    tampered["claims"][0]["paper_id"] = None
    tampered["claims"][0]["work_id"] = None

    report = build_shadow_parity_report(materials, papers, tampered)

    assert report["gate_status"] == "fail"
    assert {
        "claim_paper_not_preserved_from_source",
        "claim_source_hash_mismatch",
        "claim_mapper_replay_mismatch",
    } <= _failure_codes(report)


def test_every_exported_paper_must_have_exactly_one_work_mapping() -> None:
    materials, papers = _rows()
    papers.append(
        {
            "id": "arxiv:2608.00001",
            "source": "arxiv",
            "arxiv_id": "2608.00001",
            "title": "No material claim is needed to require work identity",
            "date_submitted": "2026-08-01",
            "status": "published",
        }
    )
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    removed_map = tampered["paper_work_map"].pop()
    tampered["works"] = [row for row in tampered["works"] if row["id"] != removed_map["work_id"]]

    report = build_shadow_parity_report(materials, papers, tampered)

    assert report["gate_status"] == "fail"
    assert "source_paper_without_work_mapping" in _failure_codes(report)


def test_string_temperature_is_verified_by_mapper_replay() -> None:
    materials, papers = _rows(
        {
            "paper_id": "arxiv:2306.07275",
            "tc_kelvin": "39 K",
            "pressure_gpa": "0 GPa",
            "ambient_sc": True,
            "measurement": "resistivity",
        }
    )
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    tampered["claims"][0]["value_kelvin"] = 40.0

    report = build_shadow_parity_report(materials, papers, tampered)

    assert report["gate_status"] == "fail"
    assert "claim_mapper_replay_mismatch" in _failure_codes(report)


def test_composition_enrichment_is_recomputed_from_source_formula() -> None:
    materials, papers = _rows()
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    tampered["compositions"][0]["composition_data"]["formula_reduced"] = "MgB"

    report = build_shadow_parity_report(materials, papers, tampered)

    assert report["gate_status"] == "fail"
    assert "composition_enrichment_mismatch" in _failure_codes(report)


def test_coordinated_work_uuid_and_claim_lineage_tampering_cannot_pass() -> None:
    materials, papers = _rows()
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    forged_work_id = uuid.uuid4()
    tampered["works"][0]["id"] = forged_work_id
    tampered["paper_work_map"][0]["work_id"] = forged_work_id
    tampered["claims"][0]["work_id"] = forged_work_id

    report = build_shadow_parity_report(materials, papers, tampered)

    assert report["gate_status"] == "fail"
    assert "work_identity_replay_mismatch" in _failure_codes(report)
    assert report["lineage"]["work_identity_replay_mismatches"] >= 3


def test_every_work_and_mapping_field_is_checked_against_resolver_replay() -> None:
    materials, papers = _rows()
    plan = _plan(materials, papers)
    tampered = copy.deepcopy(plan)
    tampered["works"][0]["canonical_title"] = "A forged canonical title"
    tampered["works"][0]["identity_metadata"]["paper_ids"] = ["forged:paper"]
    tampered["paper_work_map"][0].update(
        {
            "relation_type": "supplement",
            "match_method": "manual",
            "review_status": "rejected",
        }
    )

    report = build_shadow_parity_report(materials, papers, tampered)
    replay_failure = next(
        row for row in report["gate_failures"] if row["code"] == "work_identity_replay_mismatch"
    )
    samples = "\n".join(replay_failure["samples"])

    assert report["gate_status"] == "fail"
    assert "field:canonical_title" in samples
    assert "field:identity_metadata" in samples
    assert "field:relation_type" in samples
    assert "field:match_method" in samples
    assert "field:review_status" in samples


def test_accepted_persisted_mapping_is_authoritative_in_resolver_replay() -> None:
    materials, papers = _rows()
    papers.append({"id": "legacy:second", "title": "Second paper"})
    persisted_work_id = uuid.uuid4()
    existing = [
        {
            "paper_id": paper["id"],
            "work_id": str(persisted_work_id),
            "review_status": "accepted",
            "match_method": "manual",
            "relation_type": "canonical_version",
        }
        for paper in papers
    ]
    plan = _plan(materials, papers, existing_paper_work=existing)

    report = build_shadow_parity_report(
        materials,
        papers,
        plan,
        existing_paper_work=existing,
    )

    assert report["gate_status"] == "pass"
    assert len(plan["works"]) == 1
    assert {row["work_id"] for row in plan["paper_work_map"]} == {persisted_work_id}


@pytest.mark.parametrize("review_status", ["pending", "rejected"])
def test_nonaccepted_persisted_mapping_is_not_an_identity_edge_in_replay(
    review_status: str,
) -> None:
    materials, papers = _rows()
    papers.append({"id": "legacy:second", "title": "Second paper"})
    old_work_id = uuid.uuid4()
    existing = [
        {
            "paper_id": paper["id"],
            "work_id": str(old_work_id),
            "review_status": review_status,
            "match_method": "manual",
            "relation_type": "canonical_version",
        }
        for paper in papers
    ]
    plan = _plan(materials, papers, existing_paper_work=existing)

    report = build_shadow_parity_report(
        materials,
        papers,
        plan,
        existing_paper_work=existing,
    )

    assert report["gate_status"] == "pass"
    assert len(plan["works"]) == 2
    assert old_work_id not in {row["id"] for row in plan["works"]}
