"""SC06 pure occurrence identity and honest chronology regression contract."""
from __future__ import annotations

import itertools
import json
from copy import deepcopy
from datetime import UTC, date, datetime

import pytest

from services.timeline_points import (
    TIMELINE_RESULT_CONTRACT_VERSION,
    extract_timeline_points,
    missing_year_paper_ids,
    referenced_paper_ids,
)


def _record(**overrides):
    return {
        "tc_kelvin": 20.03, "year": 2025, "pressure_gpa": 1.02,
        "paper_id": "arxiv:fixture", "measurement": "resistivity",
        "source_role": "primary", **overrides,
    }


def _points(records, paper_years=None):
    return extract_timeline_points("mat:identity", records, paper_years or {}, current_year=2026)


@pytest.mark.parametrize("difference", [
    {"paper_id": "aps:fixture"}, {"sample_id": "sample:second"},
    {"state_id": "state:second"}, {"structure_id": "structure:second"},
    {"run_id": "run:second"}, {"tc_criterion": "zero"},
    {"tc_kelvin": 20.04}, {"pressure_gpa": 1.03},
    {"source_locator": {"table": "II", "row": 2}},
    {"source_version": "v2"}, {"structure_phase": "beta"},
    {"state": {"sample_id": "nested:sample"}},
])
def test_close_numerical_results_retain_distinct_provenance(difference):
    records = [_record(tc_criterion="onset"), _record(tc_criterion="onset", **difference)] if "tc_criterion" not in difference else [
        _record(tc_criterion="onset"), _record(**difference),
    ]
    points = _points(records)
    assert len(points) == 2
    assert len({point.id for point in points}) == 2
    assert points == _points(list(reversed(records)))


def test_permutations_and_source_filter_order_preserve_ids_and_occurrences():
    records = [_record(), _record(paper_id="aps:a"), _record(paper_id="aps:b")]
    expected = _points(records)
    for permutation in itertools.permutations(records):
        assert _points(list(permutation)) == expected
        before = _points([record for record in permutation if record["paper_id"].startswith("aps:")])
        after = [point for point in _points(list(permutation)) if point.is_aps]
        assert before == after


def test_exact_duplicates_consolidate_count_without_changing_identity():
    original = _record()
    single = _points([original])[0]
    repeated = _points([deepcopy(original), original, deepcopy(original)])
    assert len(repeated) == 1
    assert repeated[0].id == single.id
    assert repeated[0].result_metadata["occurrence_count"] == 3
    assert single.result_metadata["occurrence_count"] == 1
    assert "result_metadata" not in original


@pytest.mark.parametrize("annotation", [
    {"visibility": {"state": "pending", "reviewer_email": "private@example.test"}},
    {"anomaly_review": {"status": "no_findings"}},
    {"result_classification": {"knowledge_origin": "Computed"}},
    {"pressure_semantics": {"pressure_state": "explicit_ambient"}},
    {"property_evidence": {"selection": "made_up"}},
    {"result_metadata": {"result_id": "fake", "review_status": "approved"}},
    {"reviewer_email": "private@example.test", "review_status": "approved", "reviewed_at": "2026-01-01"},
    {"admin_decision": {"approved": True}, "needs_review": False},
    {"retracted": True, "disputed": True, "corrected": True, "source_status": "retracted", "validity_status": "accepted"},
])
def test_derived_or_governance_annotations_do_not_change_scientific_identity(annotation):
    base = _points([_record()])[0]
    annotated = _points([_record(**annotation)])[0]
    assert annotated.id == base.id
    assert annotated.result_metadata == base.result_metadata
    assert annotated.result_metadata["review_status"] == "legacy_unreviewed"


def test_explicit_result_id_revision_is_retained_without_claiming_adjudication():
    point = _points([_record(result_id="result:real", result_revision=3, review_status="accepted")])[0]
    metadata = point.result_metadata
    assert metadata["version"] == TIMELINE_RESULT_CONTRACT_VERSION
    assert metadata["result_id"] == "result:real"
    assert metadata["result_revision"] == 3
    assert metadata["identity_basis"] == "result_revision_content"
    assert metadata["review_status"] == "legacy_unreviewed"
    assert len(point.id) == 64


def test_conflicting_canonical_identity_payloads_are_never_first_wins():
    first = _record(result_id="result:shared", revision="r1", tc_criterion="onset")
    second = {**first, "tc_kelvin": 20.04}
    points = _points([first, second, first])
    assert len(points) == 2
    assert {point.result_metadata["result_id"] for point in points} == {"result:shared"}
    assert {point.result_metadata["result_revision"] for point in points} == {"r1"}
    assert sorted(point.result_metadata["occurrence_count"] for point in points) == [1, 2]
    assert all(point.result_metadata["identity_conflict"] is True for point in points)
    assert all(point.result_metadata["identity_warnings"] == ["supplied_result_revision_has_conflicting_occurrences"] for point in points)
    assert points == _points([second, first, first])


def test_result_revisions_are_distinct_even_when_numbers_are_equal():
    points = _points([_record(result_id="result:real", result_revision=1), _record(result_id="result:real", result_revision=2)])
    assert len(points) == 2
    assert len({point.id for point in points}) == 2


def test_low_temperature_is_not_rounded_to_a_numeric_deduplication_bucket():
    points = _points([_record(tc_kelvin=0.03), _record(tc_kelvin=0.031)])
    assert [point.tc_kelvin for point in points] == [0.031, 0.03]


@pytest.mark.parametrize("record_fields,paper_value,year,basis,source_date", [
    ({"year": 2023}, None, 2023, "legacy_record_year_unspecified", None),
    ({"year": "2023"}, None, 2023, "legacy_record_year_unspecified", None),
    ({"year": 2023, "year_basis": "measurement"}, None, 2023, "explicit_measurement_year", None),
    ({"year": 2023, "year_basis": "publication_year"}, None, 2023, "source_publication_year", None),
    ({"measurement_year": 2022}, {"date_published": "2024-02-01"}, 2022, "explicit_measurement_year", "2024-02-01"),
    ({"measurement_date": "2022-12-01"}, None, 2022, "explicit_measurement_date", None),
    ({"report_year": 2022}, None, 2022, "explicit_report_year", None),
    ({"report_date": "2022-12-01"}, None, 2022, "explicit_report_date", None),
    ({}, 2020, 2020, "legacy_source_year", None),
    ({}, {"date_published": date(2020, 2, 3)}, 2020, "source_publication_date", "2020-02-03"),
    ({}, {"date_published": datetime(2020, 2, 3, tzinfo=UTC)}, 2020, "source_publication_date", "2020-02-03"),
    ({}, {"date_published": "2020-02-03T11:22:33Z"}, 2020, "source_publication_date", "2020-02-03"),
    ({}, {"date_submitted": "2019-12-31", "updated_at": "2026-01-01"}, 2019, "source_submission_date", "2019-12-31"),
    ({"publication_date": "2020-02-03"}, None, 2020, "source_publication_date", "2020-02-03"),
])
def test_chronology_basis_is_explicit(record_fields, paper_value, year, basis, source_date):
    record = {key: value for key, value in _record().items() if key != "year"}
    record.update(record_fields)
    points = _points([record], {record["paper_id"]: paper_value})
    assert len(points) == 1
    assert points[0].year == year
    assert points[0].result_metadata["year_basis"] == basis
    assert points[0].result_metadata["source_date"] == source_date


def test_measurement_year_precedes_other_year_but_conflict_is_exposed():
    point = _points([_record(measurement_year=2023, report_year=2024)])[0]
    assert point.year == 2023
    assert point.result_metadata["year_basis"] == "explicit_measurement_year"
    assert point.result_metadata["chronology_warnings"] == ["chronology_fields_disagree"]


def test_unknown_record_basis_does_not_become_a_discovery_date():
    point = _points([_record(year_basis="discovered_and_verified")])[0]
    assert point.result_metadata["year_basis"] == "legacy_record_year_unspecified"
    assert point.result_metadata["chronology_warnings"] == ["year_basis_unrecognized"]


def test_missing_date_does_not_use_ingestion_update_timestamp():
    assert _points([_record(year=None)], {"arxiv:fixture": {"updated_at": "2025-01-01"}}) == []
    assert _points([_record(year=None)], {"arxiv:fixture": {"date_published": "2025"}}) == []


def test_bibliographic_update_and_review_status_do_not_change_point_id():
    first = {"date_published": "2025-02-01", "updated_at": "2025-03-01", "status": "published"}
    second = {**first, "updated_at": "2026-01-01", "status": "corrected"}
    assert _points([_record()], {"arxiv:fixture": first}) == _points([_record()], {"arxiv:fixture": second})


def test_source_version_is_not_invented_from_dates_and_is_preserved_when_reported():
    first = _points([_record()], {"arxiv:fixture": {"date_published": "2025-02-01"}})[0]
    second = _points([_record(source_version="v2")], {"arxiv:fixture": {"source_version": "v3"}})[0]
    assert first.result_metadata["source_version"] is None
    assert second.result_metadata["source_version"] == "v2"


def test_malformed_source_date_can_use_documented_submission_fallback():
    point = _points([_record(year=None)], {"arxiv:fixture": {
        "date_published": "not-a-date", "date_submitted": "2024-03-02",
    }})[0]
    assert point.year == 2024
    assert point.result_metadata["year_basis"] == "source_submission_date"
    assert point.result_metadata["chronology_warnings"] == ["invalid_source_publication_date"]


@pytest.mark.parametrize("invalid_year", [True, False, 2025.0, 2025.5, "2025.0", "NaN", "Infinity", float("nan"), float("inf"), [], {}, 0])
def test_invalid_explicit_chronology_is_not_replaced_by_a_valid_paper_date(invalid_year):
    assert _points([_record(year=invalid_year)], {"arxiv:fixture": {"date_published": "2024-01-01"}}) == []


@pytest.mark.parametrize("bad_record", [
    None, True, 1, "not structured", [],
    {"tc_kelvin": float("nan"), "year": 2025},
    {"tc_kelvin": float("inf"), "year": 2025},
    {"tc_kelvin": -float("inf"), "year": 2025},
    {"tc_kelvin": [1, 2], "year": 2025},
    {"tc_kelvin": {"not": "a scalar"}, "year": 2025},
    {"tc_kelvin": 20, "year": 2025, "pressure_gpa": float("nan")},
    {"tc_kelvin": 20, "year": 2025, "scientific_values": {"tc_kelvin": {"raw_value": {"malformed": []}}}},
    {"tc_kelvin": 20, "measurement_year": "2025.1"},
    {"tc_kelvin": 20, "measurement_date": "2025-99-99"},
    {"tc_kelvin": 20, "year": 2025, "paper_id": "aps:" + "x" * 101},
    {"tc_kelvin": 20, "year": 2025, "paper_id": {"not": "an identifier"}},
])
def test_malformed_occurrence_does_not_fail_good_siblings(bad_record):
    good = _record(tc_kelvin=0.03)
    assert _points([bad_record, good, bad_record]) == _points([good])


@pytest.mark.parametrize("invalid_container", [None, True, 1, {}, "not a list"])
def test_malformed_records_container_is_safely_empty(invalid_container):
    assert _points(invalid_container) == []
    assert referenced_paper_ids(invalid_container) == set()
    assert missing_year_paper_ids(invalid_container) == set()


def test_public_metadata_is_bounded_and_does_not_copy_private_source_prose():
    record = _record(
        result_id="i" * 501, result_revision={"reviewer_email": "private@example.test"},
        sample_id="s" * 161, state={"sample_id": "nested sample", "private_note": "PRIVATE"},
        tc_criterion="c" * 121, source_version="v" * 161,
        source_locator={"table": "II", "row": 2, "section": "x" * 121, "reviewer_email": "private@example.test", "quote": "PRIVATE"},
        evidence_text="PRIVATE source passage", reviewer_email="private@example.test",
    )
    point = _points([record])[0]
    metadata = point.result_metadata
    assert metadata["result_id"].startswith("legacy-timeline-result:")
    assert metadata["result_revision"] is None
    assert metadata["tc_criterion"] == "unknown"
    assert metadata["source_version"] is None
    assert "sample_id" not in metadata["state"]
    assert metadata["source_locator"] == {"table": "II", "row": 2}
    public = json.dumps({"result_metadata": metadata, "pressure_semantics": point.pressure_semantics})
    assert "PRIVATE" not in public
    assert "private@example.test" not in public


def test_referenced_papers_include_sources_with_explicit_years():
    records = [_record(), _record(paper_id="aps:with-date", year=None), None, {"paper_id": True}]
    assert referenced_paper_ids(records) == {"arxiv:fixture", "aps:with-date"}
    assert referenced_paper_ids(records, only_aps=True) == {"aps:with-date"}
    assert missing_year_paper_ids(records) == {"aps:with-date"}


def test_raw_records_remain_unchanged():
    records = [_record(tc_criterion="onset"), _record(tc_criterion="zero")]
    snapshot = deepcopy(records)
    _points(records)
    assert records == snapshot
