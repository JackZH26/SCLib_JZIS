"""Synthetic result-known-by contract tests. No source access or approval."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ingestion.claims.mapper import map_record_to_claim
from ingestion.temporal_provenance import (
    SourceAvailabilityWitness,
    result_temporal_provenance,
    utc_datetime,
)


def witness(**changes):
    item = SourceAvailabilityWitness(
        claim_id="synthetic-claim", paper_id="synthetic-paper", work_id="synthetic-work",
        source_revision_id="synthetic-v2", source_version="v2", capture_id="synthetic-capture",
        source_version_public_at=datetime(2024, 5, 1, tzinfo=UTC), captured_at=datetime(2026, 9, 1, tzinfo=UTC),
        bytes_sha256="a" * 64, representation="pdf", locator={"page": 2},
        review_reference="internal-review-only", version_resolved=True, binding_verified=True, public_time_verified=True,
    )
    return replace(item, **changes)


def test_work_first_date_and_extracted_dates_do_not_backdate_v2_result():
    record = {"tc_kelvin": 20, "available_at": "2001-01-01", "result_available_at": "2001-01-01", "temporal_provenance": {"status": "known_by"}}
    paper = {"date_submitted": "2000-01-01", "date_published": "2002-01-01"}
    before = deepcopy((record, paper))
    unknown = result_temporal_provenance(claim_id="synthetic-claim", record=record, paper=paper)
    assert unknown["status"] == "unknown" and unknown["result_available_at"] is None
    assert unknown["work_first_public_at"] == "2000-01-01"
    known = result_temporal_provenance(claim_id="synthetic-claim", record=record, paper=paper, witnesses=[witness()])
    assert known["result_available_at"] == "2024-05-01T00:00:00Z"
    assert known["captured_at"] == "2026-09-01T00:00:00Z"
    assert not known["first_appearance_established"] and not known["scientific_acceptance"]
    assert (record, paper) == before


@pytest.mark.parametrize("change", [
    {"claim_id": "another-claim"}, {"version_resolved": False}, {"binding_verified": False},
    {"public_time_verified": False}, {"public_time_verified": 1}, {"source_version": ""},
    {"bytes_sha256": "bad"}, {"locator": {"quote": "SECRET"}}, {"locator": {"char_start": 10, "char_end": 1}},
    {"locator": {"char_start": 10}}, {"representation": "assembled_ner_prefix"},
    {"representation": []}, {"representation": {"value": "pdf"}},
    {"source_version_public_at": "2024-05-01T00:00:00." + "0" * 80 + "+00:00"},
    {"source_version_public_at": datetime(2024, 5, 1)}, {"captured_at": None},  # noqa: DTZ001 -- invalid fixture
    {"captured_at": datetime(2023, 5, 1, tzinfo=UTC)},
])
def test_incomplete_or_invalid_witness_never_populates_an_available_time(change):
    result = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[witness(**change)])
    assert result["status"] == "uncertain" and result["result_available_at"] is None


def test_plain_dictionary_is_not_a_resolver_witness():
    result = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[asdict(witness())])
    assert result["status"] == "uncertain"
    assert "untrusted_witness_type" in result["warnings"]


def test_multiple_version_occurrences_one_claim_keep_earliest_witness_not_work_date():
    v1 = witness(source_revision_id="synthetic-v1", source_version="v1", capture_id="capture1", source_version_public_at=datetime(2022, 1, 1, tzinfo=UTC))
    later = witness()
    before = deepcopy([v1, later])
    left = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[later, v1, v1])
    right = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[v1, later])
    assert left == right and len(left["witnesses"]) == 2
    assert left["result_available_at"] == "2022-01-01T00:00:00Z"
    assert [v1, later] == before


def test_conflicting_capture_identity_or_work_does_not_choose_an_easy_witness():
    for other in (witness(bytes_sha256="b" * 64), witness(capture_id="another", work_id="another-work")):
        result = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[witness(), other])
        assert result["status"] == "uncertain" and result["result_available_at"] is None


def test_one_capture_can_contain_multiple_distinct_locations_of_same_claim():
    table, figure = witness(locator={"table": "2", "row": 1}), witness(locator={"figure": "3"})
    left = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[table, figure, table])
    right = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[figure, table])
    assert left == right and left["status"] == "known_by" and len(left["witnesses"]) == 2
    changed_capture = replace(figure, captured_at=datetime(2026, 9, 2, tzinfo=UTC))
    conflict = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[table, changed_capture])
    assert conflict["status"] == "uncertain"
    assert "source_capture_identity_conflict" in conflict["warnings"]


def test_exact_timezone_precision_and_subseconds_are_not_lexical_ordered():
    assert utc_datetime("2024-05-01T02:00:00+02:00") == datetime(2024, 5, 1, tzinfo=UTC)
    assert utc_datetime("2024-05-01") is None
    assert utc_datetime(date(2024, 5, 1)) is None
    assert utc_datetime("2024-05-01T00:00:00." + "0" * 80 + "+00:00") is None
    subsecond = witness(capture_id="subsecond", source_version_public_at=datetime(2024, 5, 1, microsecond=1, tzinfo=UTC))
    result = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[subsecond, witness()])
    assert result["result_available_at"] == "2024-05-01T00:00:00Z"


def test_public_witness_never_exports_review_reference_or_context_text():
    result = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[witness(locator={"page": 2, "excerpt": "SECRET", "reviewer_email": "private@example.invalid"})])
    assert result["status"] == "known_by"
    assert result["witnesses"][0]["locator"] == {"page": 2}
    assert "SECRET" not in str(result) and "internal-review-only" not in str(result)


def test_witness_bounds_are_explicit_not_silent_source_sampling():
    result = result_temporal_provenance(claim_id="synthetic-claim", witnesses=[witness()] * 101)
    assert result["status"] == "uncertain" and not result["assessment_complete"]


def test_mapper_keeps_raw_dates_but_requires_explicit_separate_witness():
    raw = {"formula": "Nb", "tc_kelvin": 9, "available_at": "2001-01-01", "paper_id": "synthetic-paper"}
    args = {"material_id": "mat:nb", "source_snapshot_id": "11111111-1111-4111-8111-111111111111"}
    unknown = map_record_to_claim(raw, **args)
    known = map_record_to_claim(raw, **args, temporal_witnesses=[witness(claim_id=str(unknown["id"]))])
    assert unknown["available_at"] is None
    assert known["available_at"] == date(2024, 5, 1)
    assert known["id"] == unknown["id"] and known["source_record_hash"] == unknown["source_record_hash"]
    assert known["raw_record"] == unknown["raw_record"] == raw
    assert known["validity_status"] == "pending"


def test_shared_contract_bytes_match():
    root = Path(__file__).resolve().parents[2]
    assert (root / "api/services/temporal_provenance.py").read_bytes() == (root / "ingestion/ingestion/temporal_provenance.py").read_bytes()


@pytest.mark.parametrize("key", ["ingestion_capture", "temporal_provenance"])
def test_new_derived_diagnostics_do_not_mint_claim_identities_or_authorize_dates(key):
    raw = {"formula": "Nb", "tc_kelvin": 9, "paper_id": "synthetic-paper"}
    args = {"material_id": "mat:nb", "source_snapshot_id": "11111111-1111-4111-8111-111111111111"}
    original = map_record_to_claim(raw, **args)
    changed = map_record_to_claim({**raw, key: {"status": "known_by", "result_available_at": "2001-01-01T00:00:00Z"}}, **args)
    assert changed["id"] == original["id"]
    assert changed["source_record_hash"] == original["source_record_hash"]
    assert changed["available_at"] is None
    assert key in changed["raw_record"]
