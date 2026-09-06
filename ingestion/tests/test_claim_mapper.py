"""Phase-1 typed-claim and conservative work-identity regressions."""

from __future__ import annotations

import uuid
from datetime import date
from functools import partial

import pytest

from ingestion.claims.mapper import map_record_to_claim as _map_record_to_claim
from ingestion.claims.work_identity import (
    WorkIdentityConflict,
    canonicalize_arxiv_id,
    canonicalize_doi,
    plan_work_identities,
)

SOURCE_SNAPSHOT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
map_record_to_claim = partial(
    _map_record_to_claim,
    source_snapshot_id=SOURCE_SNAPSHOT_ID,
)


def test_source_snapshot_is_required_and_must_be_a_uuid() -> None:
    with pytest.raises(TypeError, match="source_snapshot_id"):
        _map_record_to_claim({}, material_id="mat:x")
    with pytest.raises(ValueError, match="valid UUID"):
        _map_record_to_claim(
            {},
            material_id="mat:x",
            source_snapshot_id="not-a-uuid",
        )


def test_observed_claim_keeps_missing_pressure_missing_and_adds_provenance() -> None:
    record = {
        "formula": "MgB2",
        "paper_id": "arxiv:0101446",
        "tc_kelvin": 39.0,
        "tc_type": "onset",
        "pressure_gpa": None,
        "measurement": "resistivity",
        "evidence_type": "primary_experimental",
        "confidence": 0.94,
    }
    claim = map_record_to_claim(
        record,
        material_id="mat:mgb2",
        paper={"id": "arxiv:0101446", "date_submitted": "2001-01-29"},
    )

    assert claim["property_type"] == "tc"
    assert claim["evidence_role"] == "primary_experimental"
    assert claim["result_status"] == "observed"
    assert claim["value_relation"] == "exact"
    assert claim["value_kelvin"] == 39.0
    assert claim["tc_definition"] == "onset"
    assert claim["pressure_state"] == "not_reported"
    assert claim["pressure_gpa"] is None
    assert claim["available_at"] == date(2001, 1, 29)
    assert claim["source_locator"] == {"locator_quality": "paper_only"}
    assert claim["source_kind"] == "legacy"
    assert claim["validity_status"] == "pending"
    assert claim["raw_record"] == record
    assert claim["source_snapshot_id"] == SOURCE_SNAPSHOT_ID
    assert isinstance(claim["id"], uuid.UUID)
    assert len(claim["source_record_hash"]) == 64
    assert len(claim["semantic_fingerprint"]) == 64


def test_missing_tc_is_unknown_not_a_negative_example() -> None:
    claim = map_record_to_claim(
        {"formula": "Nb", "measurement": "resistivity"},
        material_id="mat:nb",
    )

    assert claim["property_type"] == "tc"
    assert claim["result_status"] == "unknown"
    assert claim["value_relation"] == "unreported"
    assert claim["value_kelvin"] is None
    assert claim["minimum_temperature_k"] is None


def test_unrepresentable_numeric_values_do_not_abort_mapping() -> None:
    huge = 10**400
    claim = map_record_to_claim(
        {
            "tc_kelvin": huge,
            "pressure_gpa": huge,
            "confidence": huge,
        },
        material_id="mat:huge-number",
    )

    assert claim["value_relation"] == "unreported"
    assert claim["value_kelvin"] is None
    assert claim["pressure_state"] == "ambiguous"
    assert claim["pressure_gpa"] is None
    assert claim["extraction_confidence"] is None
    assert claim["raw_record"]["tc_kelvin"] == huge
    assert "nonfinite_pressure" in claim["extraction_metadata"]["warnings"]


@pytest.mark.parametrize(
    ("tc_value", "warning"),
    [
        ("1e10000 K", "nonfinite_tc_value"),
        ("1e10000-2e10000 K", "nonfinite_tc_range"),
        ("<1e10000 K", "nonfinite_tc_threshold"),
    ],
)
def test_nonfinite_temperature_text_is_never_emitted(
    tc_value: str,
    warning: str,
) -> None:
    claim = map_record_to_claim(
        {"tc_kelvin": tc_value},
        material_id="mat:nonfinite-temperature",
    )

    assert claim["value_relation"] == "unreported"
    assert claim["value_kelvin"] is None
    assert claim["value_lower_kelvin"] is None
    assert claim["value_upper_kelvin"] is None
    assert warning in claim["extraction_metadata"]["warnings"]


@pytest.mark.parametrize("tc_value", ["39 K", "39 Kelvin", "39"])
def test_temperature_scalar_accepts_only_temperature_or_bare_value(tc_value: str) -> None:
    claim = map_record_to_claim(
        {"tc_kelvin": tc_value},
        material_id="mat:temperature-unit",
    )

    assert claim["value_relation"] == "exact"
    assert claim["value_kelvin"] == 39.0


@pytest.mark.parametrize("tc_value", ["155 GPa", "9 T", "3 tesla"])
def test_non_temperature_unit_in_tc_field_is_rejected(tc_value: str) -> None:
    claim = map_record_to_claim(
        {"tc_kelvin": tc_value},
        material_id="mat:wrong-tc-unit",
    )

    assert claim["value_relation"] == "unreported"
    assert claim["value_kelvin"] is None
    assert "invalid_tc_unit" in claim["extraction_metadata"]["warnings"]


def test_condition_and_confidence_fields_reject_cross_dimension_units() -> None:
    claim = map_record_to_claim(
        {
            "pressure_gpa": "39 K",
            "minimum_temperature_k": "155 GPa",
            "magnetic_field_t": "39 kelvin",
            "extraction_confidence": "0.9 GPa",
            "relation_confidence": "0.8 K",
            "doping_level": "2 tesla",
        },
        material_id="mat:cross-dimension",
    )

    assert claim["pressure_state"] == "ambiguous"
    assert claim["pressure_gpa"] is None
    assert claim["minimum_temperature_k"] is None
    assert claim["magnetic_field_t"] is None
    assert claim["extraction_confidence"] is None
    assert claim["relation_confidence"] is None
    assert claim["doping_raw"] is None
    warnings = set(claim["extraction_metadata"]["warnings"])
    assert {
        "pressure_unit_mismatch",
        "minimum_temperature_unit_mismatch",
        "magnetic_field_unit_mismatch",
        "extraction_confidence_unit_mismatch",
        "relation_confidence_unit_mismatch",
        "doping_level_unit_mismatch",
    } <= warnings


@pytest.mark.parametrize("confidence", [-0.001, 1.001, 2, 70])
def test_out_of_range_confidence_is_rejected_not_clamped(confidence: float) -> None:
    claim = map_record_to_claim(
        {"extraction_confidence": confidence},
        material_id="mat:invalid-confidence",
    )

    assert claim["extraction_confidence"] is None
    assert "extraction_confidence_out_of_range" in claim["extraction_metadata"]["warnings"]


@pytest.mark.parametrize("confidence", [0, 0.5, 1])
def test_boundary_confidence_values_are_preserved(confidence: float) -> None:
    claim = map_record_to_claim(
        {"extraction_confidence": confidence},
        material_id="mat:valid-confidence",
    )

    assert claim["extraction_confidence"] == confidence


def test_explicit_negative_requires_explicit_flag_and_preserves_tmin() -> None:
    claim = map_record_to_claim(
        {
            "formula": "Example",
            "result_status": "not_detected",
            "down_to_k": "1.8 K",
            "measurement": "resistivity",
        },
        material_id="mat:example",
    )

    assert claim["property_type"] == "non_transition"
    assert claim["result_status"] == "not_detected"
    assert claim["minimum_temperature_k"] == 1.8
    assert claim["value_relation"] == "unreported"


def test_negative_without_tmin_cannot_remain_accepted() -> None:
    claim = map_record_to_claim(
        {
            "outcome_state": "no_transition",
            "validity_status": "accepted",
        },
        material_id="mat:no-transition",
    )

    assert claim["result_status"] == "not_detected"
    assert claim["validity_status"] == "pending"
    assert "negative_result_missing_minimum_temperature" in claim["extraction_metadata"]["warnings"]


def test_accepted_observed_claim_without_tc_is_downgraded_to_pending() -> None:
    claim = map_record_to_claim(
        {
            "result_status": "observed",
            "validity_status": "accepted",
        },
        material_id="mat:missing-observed-tc",
    )

    assert claim["result_status"] == "observed"
    assert claim["value_relation"] == "unreported"
    assert claim["validity_status"] == "pending"
    assert "observed_result_missing_tc_value" in claim["extraction_metadata"]["warnings"]


def test_legacy_accepted_claim_with_valid_tc_still_requires_typed_qc() -> None:
    claim = map_record_to_claim(
        {
            "tc_kelvin": 12.0,
            "validity_status": "accepted",
        },
        material_id="mat:legacy-accepted",
    )

    assert claim["result_status"] == "observed"
    assert claim["validity_status"] == "pending"
    assert (
        "legacy_accepted_status_requires_revalidation" in claim["extraction_metadata"]["warnings"]
    )


@pytest.mark.parametrize(
    ("tc_value", "relation", "value", "lower", "upper"),
    [
        ("80-95 K", "interval", None, 80.0, 95.0),
        ("< 5 K", "lt", None, None, 5.0),
        ("≤ 5 K", "le", None, None, 5.0),
        ("> 12 K", "gt", None, 12.0, None),
        ("≥ 12 K", "ge", None, 12.0, None),
    ],
)
def test_tc_relations_are_lossless(
    tc_value: str,
    relation: str,
    value: float | None,
    lower: float | None,
    upper: float | None,
) -> None:
    claim = map_record_to_claim({"tc_kelvin": tc_value}, material_id="mat:x")

    assert claim["value_relation"] == relation
    assert claim["value_kelvin"] == value
    assert claim["value_lower_kelvin"] == lower
    assert claim["value_upper_kelvin"] == upper


def test_numeric_zero_pressure_is_ambiguous_without_an_explicit_ambient_signal() -> None:
    claim = map_record_to_claim(
        {"tc_kelvin": 10, "pressure_gpa": 0.0},
        material_id="mat:x",
    )

    assert claim["pressure_state"] == "ambiguous"
    assert claim["pressure_gpa"] == 0.0
    assert "legacy_zero_pressure_not_explicitly_ambient" in claim["extraction_metadata"]["warnings"]


@pytest.mark.parametrize(
    "pressure_value",
    [
        "ambient",
        "ambient pressure",
        "at atmospheric pressure",
        "zero pressure",
        "p=0",
        "p = 0.0 GPa",
    ],
)
def test_explicit_ambient_pressure_phrases_are_accepted(pressure_value: str) -> None:
    claim = map_record_to_claim(
        {"pressure_gpa": pressure_value},
        material_id="mat:ambient-pressure",
    )

    assert claim["pressure_state"] == "explicit_ambient"
    assert claim["pressure_gpa"] == 0.0


@pytest.mark.parametrize(
    "pressure_value",
    ["zero kelvin", "zero tesla", "zero field", "ambient temperature"],
)
def test_non_pressure_ambient_phrases_are_not_misclassified(
    pressure_value: str,
) -> None:
    claim = map_record_to_claim(
        {"pressure_gpa": pressure_value},
        material_id="mat:wrong-ambient-dimension",
    )

    assert claim["pressure_state"] == "ambiguous"
    assert claim["pressure_gpa"] is None
    assert "unparseable_pressure" in claim["extraction_metadata"]["warnings"]


def test_invalid_interval_bound_is_discarded_without_breaking_typed_shape() -> None:
    claim = map_record_to_claim(
        {"tc_kelvin": [-1, 10]},
        material_id="mat:invalid-range",
    )

    assert claim["value_relation"] == "unreported"
    assert claim["value_kelvin"] is None
    assert claim["value_lower_kelvin"] is None
    assert claim["value_upper_kelvin"] is None
    assert "invalid_tc_interval_discarded" in claim["extraction_metadata"]["warnings"]


def test_explicit_ambient_signal_allows_zero_but_null_is_never_filled() -> None:
    explicit = map_record_to_claim(
        {"tc_kelvin": 10, "pressure_gpa": 0.0, "pressure_state": "explicit_ambient"},
        material_id="mat:x",
    )
    missing = map_record_to_claim(
        {"tc_kelvin": 10, "pressure_gpa": None, "pressure_state": "explicit_ambient"},
        material_id="mat:x",
    )

    assert (explicit["pressure_state"], explicit["pressure_gpa"]) == (
        "explicit_ambient",
        0.0,
    )
    assert (missing["pressure_state"], missing["pressure_gpa"]) == (
        "ambiguous",
        None,
    )


def test_nims_aliases_are_mapped_without_inventing_paper_provenance() -> None:
    claim = map_record_to_claim(
        {
            "tc": 7.2,
            "pressure": 2.0,
            "structure": "bcc",
            "doping": "none",
            "reference": "NIMS SuperCon row 42",
        },
        material_id="nims:pb",
        material_formula="Pb",
    )

    assert claim["value_kelvin"] == 7.2
    assert claim["pressure_state"] == "reported"
    assert claim["pressure_gpa"] == 2.0
    assert claim["structure_phase_raw"] is None  # structure != phase
    assert claim["doping_raw"] == "none"
    assert claim["paper_id"] is None
    assert claim["source_locator"] == {
        "reference": "NIMS SuperCon row 42",
        "locator_quality": "reference_only",
    }


def test_source_hash_is_order_independent_and_mapper_does_not_mutate_input() -> None:
    first = {"paper_id": "arxiv:2401.00001", "tc_kelvin": 12.0, "confidence": 0.8}
    second = {"confidence": 0.8, "tc_kelvin": 12.0, "paper_id": "arxiv:2401.00001"}
    before = dict(first)

    claim_a = map_record_to_claim(first, material_id="mat:x")
    claim_b = map_record_to_claim(second, material_id="mat:x")

    assert claim_a["source_record_hash"] == claim_b["source_record_hash"]
    assert claim_a["id"] == claim_b["id"]
    assert first == before


def test_uuid_ingestion_run_id_is_serialized_for_varchar_storage() -> None:
    run_id = uuid.uuid4()
    claim = map_record_to_claim(
        {"tc_kelvin": 12.0},
        material_id="mat:x",
        ingestion_run_id=run_id,
    )

    assert claim["ingestion_run_id"] == str(run_id)


def test_independent_sources_share_semantics_but_not_source_identity() -> None:
    base = {
        "tc_kelvin": 12.0,
        "measurement": "resistivity",
        "ambient_sc": True,
        "pressure_gpa": 0.0,
        "evidence_type": "primary_experimental",
    }
    first = map_record_to_claim({**base, "paper_id": "arxiv:2401.00001"}, material_id="mat:x")
    second = map_record_to_claim(
        {**base, "paper_id": "aps:10.1103/PhysRevB.1.1"}, material_id="mat:x"
    )

    assert first["source_record_hash"] != second["source_record_hash"]
    assert first["semantic_fingerprint"] == second["semantic_fingerprint"]


def test_source_locator_and_retraction_are_propagated() -> None:
    claim = map_record_to_claim(
        {
            "tc_kelvin": 175,
            "source_section": "Results",
            "source_page": 3,
            "source_quote": "A transition is reported.",
        },
        material_id="mat:c60",
        paper={"id": "arxiv:cond-mat/0109251", "status": "retracted"},
    )

    assert claim["source_locator"]["section"] == "Results"
    assert claim["source_locator"]["page"] == 3
    assert claim["source_locator"]["locator_quality"] == "span"
    assert claim["validity_status"] == "retracted"


def test_identifier_canonicalizers_are_exact_and_version_stable() -> None:
    assert canonicalize_doi("https://doi.org/10.1103/PhysRevB.108.054515.") == (
        "10.1103/physrevb.108.054515"
    )
    assert canonicalize_doi("not a DOI") is None
    assert canonicalize_arxiv_id("https://arxiv.org/abs/2306.07275v3") == "2306.07275"
    assert canonicalize_arxiv_id("arXiv:cond-mat/0109251v2") == "cond-mat/0109251"


def test_exact_doi_and_related_arxiv_build_one_work_without_title_matching() -> None:
    papers = [
        {
            "id": "arxiv:2306.07275",
            "source": "arxiv",
            "title": "Preprint title",
            "date_submitted": "2023-06-12",
        },
        {
            "id": "aps:10.1103/PhysRevB.108.054515",
            "source": "aps",
            "doi": "10.1103/PhysRevB.108.054515",
            "related_paper_id": "arxiv:2306.07275",
            "title": "Published title",
            "date_published": "2023-12-01",
            "status": "published",
        },
    ]

    plan = plan_work_identities(papers)

    assert len(plan["works"]) == 1
    work = plan["works"][0]
    assert work["canonical_arxiv_id"] == "2306.07275"
    assert work["canonical_doi"] == "10.1103/physrevb.108.054515"
    assert work["canonical_title"] == "Published title"
    assert work["available_at"] == date(2023, 6, 12)
    assert work["identity_metadata"]["title_used_for_matching"] is False
    assert {row["work_id"] for row in plan["paper_work_map"]} == {work["id"]}


def test_identical_titles_do_not_auto_merge() -> None:
    plan = plan_work_identities(
        [
            {"id": "local:one", "title": "Same title"},
            {"id": "local:two", "title": "Same title"},
        ]
    )

    assert len(plan["works"]) == 2
    assert len({row["work_id"] for row in plan["paper_work_map"]}) == 2
    assert {row["match_method"] for row in plan["paper_work_map"]} == {"singleton"}


def test_exact_canonical_arxiv_id_merges_and_missing_title_has_safe_fallback() -> None:
    plan = plan_work_identities(
        [
            {"id": "legacy:preprint-a", "arxiv_id": "2306.07275v1"},
            {"id": "mirror:preprint-a", "arxiv_id": "2306.07275v3"},
        ]
    )

    assert len(plan["works"]) == 1
    assert plan["works"][0]["canonical_arxiv_id"] == "2306.07275"
    assert plan["works"][0]["canonical_title"] in {
        "legacy:preprint-a",
        "mirror:preprint-a",
    }
    assert "exact_arxiv" in plan["works"][0]["identity_metadata"]["auto_merge_signals"]
    assert {row["match_method"] for row in plan["paper_work_map"]} == {"exact_arxiv"}


def test_persisted_work_conflict_requires_manual_resolution() -> None:
    papers = [
        {"id": "arxiv:2306.07275", "doi": "10.1103/example.1"},
        {"id": "aps:10.1103/example.1", "doi": "10.1103/example.1"},
    ]

    with pytest.raises(WorkIdentityConflict):
        plan_work_identities(
            papers,
            existing_work_ids={
                papers[0]["id"]: uuid.uuid4(),
                papers[1]["id"]: uuid.uuid4(),
            },
        )


def test_disconnected_papers_in_one_persisted_work_emit_one_work() -> None:
    work_id = uuid.uuid4()
    papers = [
        {"id": "nims:row-one", "title": "First imported title"},
        {"id": "nims:row-two", "title": "Second imported title"},
    ]

    plan = plan_work_identities(
        papers,
        existing_work_ids={paper["id"]: work_id for paper in papers},
    )

    assert len(plan["works"]) == 1
    assert plan["works"][0]["id"] == work_id
    assert plan["works"][0]["identity_metadata"]["auto_merge_signals"] == ["existing_mapping"]
    assert len(plan["paper_work_map"]) == 2
    assert {row["work_id"] for row in plan["paper_work_map"]} == {work_id}
    assert {row["match_method"] for row in plan["paper_work_map"]} == {"manual"}
    assert {row["review_status"] for row in plan["paper_work_map"]} == {"accepted"}


def test_conflicting_work_identifiers_are_retained_but_require_review() -> None:
    plan = plan_work_identities(
        [
            {
                "id": "aps:10.1103/example.1",
                "doi": "10.1103/example.1",
                "related_paper_id": "aps:10.1103/example.2",
            },
            {
                "id": "aps:10.1103/example.2",
                "doi": "10.1103/example.2",
            },
        ]
    )

    assert len(plan["works"]) == 1
    assert {row["review_status"] for row in plan["paper_work_map"]} == {"pending"}
    assert any(item["code"] == "multiple_dois_in_work_component" for item in plan["warnings"])


def test_external_related_paper_reuses_its_persisted_work_id() -> None:
    existing_work_id = uuid.uuid4()
    plan = plan_work_identities(
        [
            {
                "id": "aps:10.1103/example.3",
                "doi": "10.1103/example.3",
                "related_paper_id": "arxiv:2306.07275",
            }
        ],
        existing_work_ids={"arxiv:2306.07275": existing_work_id},
    )

    assert plan["works"][0]["id"] == existing_work_id
