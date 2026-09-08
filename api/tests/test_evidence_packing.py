"""Deterministic excerpt packing; no provider, DB writes or root adjudication."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from models.evidence_packing import (
    EvidencePackingPlan,
    EvidencePackingSelection,
    EvidencePackingSummary,
    PackingCandidate,
)
from services.evidence_packing import (
    EvidencePackingError,
    describe_selection,
    pack_evidence,
    packing_group_ids,
    public_summary,
)

WORK_A = "11111111-1111-4111-8111-111111111111"
WORK_B = "22222222-2222-4222-8222-222222222222"
SNAPSHOT = "a" * 64


def candidate(identifier, paper="paper-a", role="other", **changes):
    return {"chunk_id": identifier, "paper_id": paper, "role_hint": role, "chunk_kind": "original_passage",
            "source_snapshot_sha256": SNAPSHOT, "content_sha256": hashlib.sha256(identifier.encode()).hexdigest(), **changes}


def simple_cost(ids):
    return 10 + 100 * len(ids)


def pack(values, **kwargs):
    return pack_evidence(values, cost=kwargs.pop("cost", simple_cost), byte_budget=kwargs.pop("byte_budget", 10000), **kwargs)


def ids(plan):
    return [item.chunk_id for item in plan.selected]


def dispositions(plan):
    return {item.chunk_id: item.reason_code for item in plan.excluded}


def test_diversity_precedes_methods_results_table_complements_and_preserves_citations():
    values = [candidate("a-methods", role="methods"), candidate("a-results", role="results"),
              candidate("a-table", role="table"), candidate("b-results", paper="paper-b", role="results")]
    result = pack(values)
    assert ids(result) == ["a-methods", "b-results", "a-results", "a-table"]
    assert [item.position for item in result.selected] == [1, 2, 3, 4]
    assert [item.selection_reason for item in result.selected] == ["source_diversity", "source_diversity", "complementary_role", "complementary_role"]
    assert result.source_group_count == result.diversity_group_count == 2
    assert result.independent_support_count is None and result.scientific_acceptance is False
    assert result.independence_status == "independence_not_established"


def test_accepted_work_diversity_is_first_then_source_coverage_and_hard_work_cap():
    values = [candidate("a-methods", role="methods", accepted_work_id=WORK_A),
        candidate("a-results", role="results", accepted_work_id=WORK_A),
        candidate("a-preprint", paper="preprint", role="results", accepted_work_id=WORK_A),
        candidate("a-supplement", paper="supplement", role="table", accepted_work_id=WORK_A),
        candidate("a-fourth", paper="fourth-version", accepted_work_id=WORK_A),
        candidate("b-result", paper="paper-b", role="results", accepted_work_id=WORK_B)]
    result = pack(values)
    assert ids(result) == ["a-methods", "b-result", "a-preprint", "a-supplement"]
    assert result.diversity_group_count == 2 and result.source_group_count == 4
    assert [item.selection_reason for item in result.selected][-2:] == ["source_coverage", "source_coverage"]
    assert dispositions(result) == {"a-results": "work_limit", "a-fourth": "work_limit"}
    wire = result.model_dump_json()
    assert WORK_A not in wire and WORK_B not in wire
    assert all(item.group_basis == "accepted_work_mapping" for item in result.selected)


def test_same_paper_different_immutable_snapshots_never_share_source_group():
    values = [candidate("old", role="methods"), candidate("new", role="results", source_snapshot_sha256="b" * 64)]
    result = pack(values)
    assert result.source_group_count == 2
    assert result.selected[0].source_group_id != result.selected[1].source_group_id
    assert {item.source_snapshot_sha256 for item in result.selected} == {SNAPSHOT, "b" * 64}
    assert [item.selection_reason for item in result.selected] == ["source_diversity", "source_diversity"]


def test_legacy_without_snapshot_retains_one_per_paper_not_complementary_authority():
    values = [candidate("legacy-methods", role="methods", source_snapshot_sha256=None),
              candidate("legacy-results", role="results", source_snapshot_sha256=None),
              candidate("other-paper", paper="paper-b", source_snapshot_sha256=None)]
    result = pack(values)
    assert ids(result) == ["legacy-methods", "other-paper"]
    assert dispositions(result) == {"legacy-results": "source_limit"}
    assert all(item.source_snapshot_sha256 is None and item.source_group_basis == "legacy_paper"
               and item.group_basis == "legacy_paper" for item in result.selected)


@pytest.mark.parametrize("kind,role,reason", [
    ("original_passage", "methods", "role_already_represented"),
    ("original_passage", "other", "not_complementary_original"),
    ("abstract", "results", "not_complementary_original"),
    ("derived_fact", "results", "not_complementary_original"),
    ("legacy_unknown", "table", "not_complementary_original"),
])
def test_complementarity_is_new_original_role_not_a_second_generic_or_derived_excerpt(kind, role, reason):
    result = pack([candidate("first", role="methods"), candidate("next", role=role, chunk_kind=kind)])
    assert ids(result) == ["first"]
    assert dispositions(result) == {"next": reason}


def test_identical_text_is_not_counted_twice_even_across_papers():
    values = [candidate("first"), candidate("second", paper="paper-b", content_sha256=candidate("first")["content_sha256"])]
    result = pack(values)
    assert ids(result) == ["first"] and dispositions(result) == {"second": "duplicate_content"}


def test_duplicate_fallback_can_fit_when_earlier_same_text_has_oversized_metadata():
    values = [candidate("oversized"), candidate("small", paper="paper-b", content_sha256=candidate("oversized")["content_sha256"])]
    result = pack(values, byte_budget=200, cost=lambda proposed: 1000 if "oversized" in proposed else simple_cost(proposed))
    assert ids(result) == ["small"]


def test_exact_complete_serialized_cost_reindexes_each_proposed_list_and_never_changes_text():
    values = [candidate("m", role="methods"), candidate("r", role="results"), candidate("t", role="table")]
    text = {"m": "Original method λ and isotope D3S.", "r": "Original result ±2 K.", "t": "Table header | GPa\nrow | 150\nFootnote."}
    before = deepcopy(text)
    measured = []

    def serialize(proposed):
        metadata = describe_selection(values, proposed)
        body = {"system": "Do not invent missing conditions.", "question": "Explain the methods and results.",
                "sources": [{"packing_info": item.model_dump(), "index": item.position, "text": text[item.chunk_id]}
                            for item in metadata]}
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def cost(proposed):
        assert type(proposed) is tuple
        measured.append(proposed)
        return len(serialize(proposed))

    boundary = len(serialize(("m", "r")))
    result = pack(values, cost=cost, byte_budget=boundary)
    assert ids(result) == ["m", "r"]
    assert result.payload_bytes == boundary and dispositions(result) == {"t": "payload_budget"}
    assert measured[0] == () and len(measured) == len(set(measured))
    assert result.selected == describe_selection(values, tuple(ids(result)))
    assert text == before
    assert len(serialize(tuple(ids(result)) + ("t",))) > boundary


def test_budget_checks_baseline_before_attempting_any_source_and_public_empty_status():
    calls = []
    result = pack([candidate("x")], byte_budget=5, cost=lambda proposed: calls.append(proposed) or 10)
    assert calls == [()] and result.status == "base_budget_exceeded"
    assert result.payload_bytes == 10 and result.selected_count == 0
    assert dispositions(result) == {"x": "base_payload_budget"}
    summary = public_summary(result)
    assert summary.status == "base_budget_exceeded" and summary.reason_counts == {"base_payload_budget": 1}


def test_no_candidates_is_still_explicitly_measured_not_assumed_zero():
    result = pack([])
    assert result.status == "empty" and result.payload_bytes == 10
    assert public_summary(result).reason_codes == ["no_admitted_candidates"]


def test_small_candidate_fits_after_large_one_without_partial_source_truncation():
    values = [candidate("large-table", paper="a", role="table"), candidate("small-method", paper="b", role="methods")]
    result = pack(values, cost=lambda proposed: 10 + sum(10000 if item == "large-table" else 100 for item in proposed), byte_budget=110)
    assert ids(result) == ["small-method"] and result.payload_bytes == 110
    assert dispositions(result) == {"large-table": "payload_budget"}


@pytest.mark.parametrize("setting,value", [("max_chunks", 0), ("max_chunks", 21), ("max_per_source", 4),
    ("max_per_work", 0), ("byte_budget", 0), ("byte_budget", 16 * 1024 * 1024 + 1), ("max_chunks", True), ("byte_budget", "100")])
def test_strict_configuration_bounds(setting, value):
    with pytest.raises(EvidencePackingError):
        pack([], **{setting: value})


@pytest.mark.parametrize("bad_cost", [True, None, -1, 1.5, "100", 64 * 1024 * 1024 + 1])
def test_cost_is_bounded_actual_integer_bytes_not_flags_tokens_or_estimates(bad_cost):
    with pytest.raises(EvidencePackingError):
        pack([candidate("x")], cost=lambda _: bad_cost)


def test_callback_failure_and_non_monotone_cost_fail_closed_without_partial_plan():
    def failure(_):
        raise RuntimeError("Private context must not escape")
    with pytest.raises(EvidencePackingError, match="accounting is unavailable") as caught:
        pack([candidate("x")], cost=failure)
    assert "Private" not in str(caught.value)
    with pytest.raises(EvidencePackingError, match="did not increase"):
        pack([candidate("x")], cost=lambda proposed: 100 if not proposed else 10)
    with pytest.raises(EvidencePackingError, match="did not increase"):
        pack([candidate("x")], cost=lambda proposed: 10)


def test_all_candidate_and_total_selection_bounds_are_independently_enforced():
    values = [candidate(str(i), paper=str(i)) for i in range(300)]
    result = pack(values)
    assert result.candidate_count == 300 and result.selected_count == 20 and len(result.excluded) == 280
    assert set(dispositions(result).values()) == {"chunk_limit"}
    with pytest.raises(EvidencePackingError):
        pack(values + [candidate("overflow")])
    with pytest.raises(EvidencePackingError):
        pack(iter(values))


def test_stricter_work_and_source_limits_are_distinct_from_unmapped_source_caps():
    values = [candidate("m", role="methods", accepted_work_id=WORK_A),
              candidate("r", role="results", accepted_work_id=WORK_A)]
    assert dispositions(pack(values, max_per_work=1)) == {"r": "work_limit"}
    assert dispositions(pack(values, max_per_source=1)) == {"r": "source_limit"}
    unmapped = [{**value, "accepted_work_id": None} for value in values]
    assert ids(pack(unmapped, max_per_work=1)) == ["m", "r"]


@pytest.mark.parametrize("changes", [
    {"scientific_acceptance": True}, {"root_status": "resolved"}, {"permission_status": "allowed"},
    {"text": "Do not copy original text into this DTO"}, {"source_snapshot_sha256": "A" * 64},
    {"accepted_work_id": "not-a-work"}, {"accepted_work_id": True}, {"chunk_id": "\n"},
    {"paper_id": " "}, {"content_sha256": 1}, {"chunk_kind": "reviewed_original"}, {"role_hint": "verified_result"},
])
def test_private_candidate_does_not_accept_authority_flags_or_unbounded_identities(changes):
    with pytest.raises((ValidationError, ValueError)):
        pack([candidate("x", **changes)])


def test_conflicting_chunk_or_accepted_work_identity_is_not_silently_deduplicated():
    with pytest.raises(EvidencePackingError, match="Repeated"):
        pack([candidate("x"), candidate("x")])
    with pytest.raises(EvidencePackingError, match="Conflicting"):
        pack([candidate("x", accepted_work_id=WORK_A), candidate("y", accepted_work_id=WORK_B)])
    with pytest.raises(EvidencePackingError, match="Conflicting"):
        pack([candidate("x", accepted_work_id=WORK_A), candidate("y")])


def test_group_ids_are_domain_separated_stable_and_keep_source_snapshot_independent_of_work():
    first = packing_group_ids(candidate("x"))
    same_source = packing_group_ids(candidate("y"))
    linked = packing_group_ids(candidate("x", accepted_work_id=WORK_A))
    assert first == same_source
    assert linked["source_group_id"] == first["source_group_id"]
    assert linked["diversity_group_id"] != first["diversity_group_id"]
    assert first["source_group_id"][4:] != first["diversity_group_id"][4:]
    assert packing_group_ids(candidate("x", source_snapshot_sha256=None))["source_group_id"] != first["source_group_id"]
    assert packing_group_ids(candidate("x", paper="other"))["source_group_id"] != first["source_group_id"]


def test_public_summary_contains_no_selected_or_excluded_identity_or_raw_work():
    result = pack([candidate("selected-secret-id", accepted_work_id=WORK_A),
                   candidate("omitted-secret-id", accepted_work_id=WORK_A)])
    summary = public_summary(result)
    body = summary.model_dump_json()
    assert "selected-secret-id" not in body and "omitted-secret-id" not in body and WORK_A not in body
    assert summary.reason_counts == {"not_complementary_original": 1}
    assert summary.independent_support_count is None and summary.scientific_acceptance is False
    assert summary.byte_count_method == "utf8-full-payload/1"


@pytest.mark.parametrize("value", [0, 1, True, "false", None])
def test_false_authority_is_literal_boolean_not_numeric_alias(value):
    with pytest.raises(ValidationError):
        EvidencePackingSummary(scientific_acceptance=value)
    item = pack([candidate("x")]).selected[0].model_dump()
    with pytest.raises(ValidationError):
        EvidencePackingSelection.model_validate({**item, "scientific_acceptance": value})


@pytest.mark.parametrize("status", ["not_requested", "withheld", "unavailable"])
def test_unavailable_and_withheld_summaries_cannot_republish_old_selected_metadata(status):
    baseline = EvidencePackingSummary(status=status)
    assert baseline.payload_bytes is None and baseline.independent_support_count is None
    for changes in ({"selected_count": 1, "candidate_count": 1}, {"source_group_count": 1},
                    {"payload_bytes": 100}, {"reason_counts": {"payload_budget": 1}}):
        with pytest.raises(ValidationError):
            EvidencePackingSummary(status=status, **changes)


@pytest.mark.parametrize("changes", [
    {"unknown": True}, {"independent_support_count": 2}, {"reason_counts": {"unknown_reason": 1}},
    {"reason_counts": {"payload_budget": True}}, {"reason_counts": {"payload_budget": 0}},
    {"reason_codes": ["arbitrary source text"]}, {"reason_codes": ["packing_unavailable", "packing_unavailable"]},
    {"independence_status": "independent"}, {"payload_bytes": "100"},
])
def test_public_summary_is_closed_and_cannot_assert_independence(changes):
    with pytest.raises(ValidationError):
        EvidencePackingSummary(**changes)


def test_plan_rejects_tampered_positions_counts_snapshot_basis_and_old_summary():
    result = pack([candidate("m", role="methods"), candidate("r", role="results")])
    for mutate in (
        lambda value: value.update(selected_count=1),
        lambda value: value.update(payload_bytes=10001),
        lambda value: value["selected"][0].update(position=2),
        lambda value: value["selected"][1].update(selection_reason="source_diversity"),
        lambda value: value["selected"][1].update(role_hint="methods"),
        lambda value: value["selected"][1].update(source_snapshot_sha256="b" * 64),
        lambda value: value["selected"][0].update(source_snapshot_sha256=None),
        lambda value: value.update(independent_support_count=2),
    ):
        body = result.model_dump()
        mutate(body)
        with pytest.raises(ValidationError):
            EvidencePackingPlan.model_validate(body)


def test_describe_selection_is_exact_repeatable_and_rejects_unknown_or_repeated_ids():
    values = [PackingCandidate(**candidate("m", role="methods")), PackingCandidate(**candidate("r", role="results"))]
    result = pack(values)
    assert describe_selection(values, ids(result)) == result.selected
    assert pack(values).model_dump() == result.model_dump()
    for proposed in (["unknown"], ["m", "m"], "m", [True]):
        with pytest.raises(EvidencePackingError):
            describe_selection(values, proposed)
