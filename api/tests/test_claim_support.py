"""Synthetic unit fixtures for a narrow parser, not a scientific gold set.

Every numerical material assertion here is invented for testing. Passing these
tests does not measure performance on research literature or establish truth.
"""
from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from services.claim_support import LIMITS, SUPPORT_POLICY_VERSION, assess_answer
from services.source_visibility import source_visibility


def _source(text="H3S has a Tc of 100 K at 2 GPa.", **changes):
    return SimpleNamespace(**{
        "index": 1, "paper_id": "synthetic:support", "title": "Synthetic test fixture",
        "section": "Results", "text": text, "material_evidence": [],
        "source_visibility": source_visibility("published"), "visibility_resolved": True,
        **changes,
    })


def _check(answer="H3S has a Tc of 100 K at 2 GPa [1].", source=None):
    return assess_answer(answer, [source or _source()])


@pytest.mark.parametrize("source,answer", [
    ("H3S has a Tc of 100 K at 20 kbar.", "H3S has a Tc of 100 K at 2 GPa [1]."),
    ("H3S has a Tc of 100 mK at 2 GPa.", "H3S has a Tc of 0.1 K at 2 GPa [1]."),
    ("H₃S has a Tc of 100 K at 2 GPa.", "H3S has a Tc of 100 K at 2 GPa [1]."),
    ("H3S 的 Tc 为 100 K，压力为 2 GPa。", "H₃S 的 Tc 为 100 K，压力为 20 kbar [1]。"),
    ("H3S的Tc为100 K，压力为2 GPa。", "H3S的Tc为100 K，压力为2 GPa [1]。"),
    ("H3S 的临界温度为 100 K，压力为 2 GPa。", "H3S 的 Tc 为 100 K，压力为 2 GPa [1]。"),
    ("Nb has a Tc of 30 mK at ambient pressure.", "Nb has a Tc of 0.03 K at ambient pressure [1]."),
    ("H3S has an onset Tc of 100 K at 2 GPa.", "H3S has an onset Tc of 100 K at 2 GPa [1]."),
    ("H3S sample B has a Tc of 100 K at 2 GPa.", "H3S sample B has a Tc of 100 K at 2 GPa [1]."),
    ("Bulk H3S has a computed Tc of 100 K at 2 GPa.", "Bulk H3S has a computed Tc of 100 K at 2 GPa [1]."),
    ("Prior work reported H3S with Tc of 100 K at 2 GPa.", "Prior work reported H3S with Tc of 100 K at 2 GPa [1]."),
])
def test_explicit_complete_report_tuples_and_exact_unit_equivalences_can_match(source, answer):
    result = _check(answer, _source(source))
    assert result["status"] == "supported", result
    assert result["policy_version"] == SUPPORT_POLICY_VERSION
    assert result["claims"][0]["evidence"][0]["source_index"] == 1
    assert result["claims"][0]["evidence"][0]["paper_id"] == "synthetic:support"
    assert result["claims"][0]["reason_codes"] == ["explicit_same_source_tuple_match"]


@pytest.mark.parametrize("quantity", ["< 100 K", "> 100 K", "≤ 100 K", "90–100 K", "100 ± 5 K", "about 100 K", "≈100 K"])
def test_equally_reported_relations_and_uncertainties_are_preserved(quantity):
    result = _check(f"H3S has a Tc of {quantity} at 2 GPa [1].", _source(f"H3S has a Tc of {quantity} at 2 GPa."))
    assert result["status"] == "supported", result
    tuple_quantity = result["claims"][0]["quantities"]["tc_kelvin"]
    assert tuple_quantity["relation"] != "exact" or tuple_quantity["uncertainty"] is not None or tuple_quantity["approximate"]


@pytest.mark.parametrize("source,answer", [
    ("H3S showed no superconducting transition at 100 K and ambient pressure.", "H3S showed a superconducting transition at 100 K and ambient pressure [1]."),
    ("H3S showed a superconducting transition at 100 K and ambient pressure.", "H3S showed no superconducting transition at 100 K and ambient pressure [1]."),
    ("H3S has a Tc of 100 K at 2 GPa.", "H3S has a Tc of 300 K at 2 GPa [1]."),
    ("H3S 的 Tc 为 100 K，压力为 2 GPa。", "H3S 的 Tc 为 300 K，压力为 2 GPa [1]。"),
])
def test_complete_bound_report_with_opposite_polarity_or_different_exact_value_conflicts(source, answer):
    result = _check(answer, _source(source))
    assert result["status"] == "contradicted", result
    assert result["claims"][0]["evidence"]


@pytest.mark.parametrize("source", [
    "H3S has a Tc of 100 K.",
    "H3S has a Tc of 100 K at 0 GPa.",
    "H3S has a Tc of 100 K at 2 GPa and zero magnetic field.",
    "H3S was measured at 100 K and 2 GPa.",
    "H3S Tc was measured at 100 K and 2 GPa.",
    "H3S and LaH10 have Tc of 100 K at 2 GPa.",
    "H3S has a Tc of 100 K at 2 GPa or 5 GPa.",
    "H3S has a Tc of 100 K at 2 GPa and 200 K at 3 GPa.",
    "H3S may have a Tc of 100 K at 2 GPa.",
    "H3S has a Tc of 100 K at 2 GPa. This was an illustrative example.",
])
def test_incomplete_ambiguous_or_nonassertive_context_is_not_support(source):
    result = _check(source=_source(source))
    assert result["status"] == "undetermined", result


@pytest.mark.parametrize("answer", [
    "H3S has a Tc of 100 K at 150 GPa [1].",
    "H3S sample A has a Tc of 100 K at 2 GPa [1].",
    "H3S has an observed Tc of 100 K at 2 GPa [1].",
    "H3S has an onset Tc of 100 K at 2 GPa [1].",
    "Prior work reported H3S with Tc of 100 K at 2 GPa [1].",
    "H3S has a Tc of 100 K at 2 GPa and is suitable for commercial use [1].",
    "H3S has a Tc of 100 K at 2 GPa [1]. It superconducts due to spin fluctuations [1].",
    "H3S has a Tc of 100 K at 2 GPa [1]. I cannot verify it but H3S is a superconductor [1].",
    "H3S has a Tc of 100 K at 2 GPa [1]. 证据不足但它已被证实为超导体 [1]。",
    "H3SのTcは100 Kで圧力は2 GPaです [1]。",
])
def test_unbound_qualifiers_and_unsupported_assertions_never_disappear(answer):
    result = _check(answer)
    assert result["status"] == "undetermined", result
    assert any(claim["status"] == "undetermined" for claim in result["claims"])


@pytest.mark.parametrize("answer", ["Insufficient evidence.", "I cannot answer from the supplied sources.", "证据不足。", ""])
def test_exact_refusals_are_not_checked_and_never_supported(answer):
    result = _check(answer)
    assert result["status"] == "not_checked"
    assert result["coverage"]["assessed_claims"] == 0


def test_no_sources_are_not_checked_even_when_answer_contains_an_assertion():
    result = assess_answer("H3S has a Tc of 100 K at 2 GPa [1].", [])
    assert result["status"] == "not_checked"
    assert result["coverage"]["total_claims"] == 1
    assert result["coverage"]["assessed_claims"] == 0


@pytest.mark.parametrize("change", [
    {"visibility_resolved": False},
    {"source_visibility": {}},
    {"source_visibility": {**source_visibility("published"), "version": "future-or-forged"}},
    {"source_visibility": {**source_visibility("published"), "warning_codes": "unknown"}},
    {"source_visibility": {**source_visibility("published"), "warning_codes": [True]}},
    {"source_visibility": source_visibility("retracted")},
    {"source_visibility": source_visibility(None)},
    {"section": "derived_facts"},
    {"material_evidence": [{"evidence_kind": {"bad": "shape"}}]},
    {"material_evidence": [{"needs_review": True}]},
    {"material_evidence": [{"formula": "H3S", "knowledge_origin": "Computed"}]},
    {"material_evidence": [{"formula": "H3S", "result_classification": {"classification_status": "conflicted"}}]},
])
def test_metadata_never_overrides_a_hold_or_promotes_an_unknown_context(change):
    assert _check(source=_source(**change))["status"] == "undetermined"


def test_metadata_and_sources_remain_unchanged_after_assessment():
    item = _source()
    before = deepcopy(vars(item))
    _check(source=item)
    assert vars(item) == before


def test_multiple_citations_require_separate_complete_support_and_do_not_borrow_uncited_sources():
    wrong = _source("H3S has a Tc of 200 K at 2 GPa.")
    right = _source(index=2, paper_id="synthetic:second")
    assert assess_answer("H3S has a Tc of 100 K at 2 GPa [1].", [wrong, right])["status"] == "contradicted"
    assert assess_answer("H3S has a Tc of 100 K at 2 GPa [1] [2].", [wrong, right])["status"] == "undetermined"
    assert assess_answer("H3S has a Tc of 100 K at 2 GPa [1].", [_source(), _source()])["status"] == "undetermined"


@pytest.mark.parametrize("bound", ["answer", "claims", "claim", "source", "source_sentences", "source_clause", "source_count", "material_evidence"])
def test_bound_exhaustion_is_explicit_and_cannot_approve_a_partial_check(bound):
    answer = "H3S has a Tc of 100 K at 2 GPa [1]."
    sources = [_source()]
    if bound == "answer":
        answer += " " * LIMITS["answer_chars"] + "New unexamined assertion."
    elif bound == "claims":
        answer = " ".join([answer] * (LIMITS["claims"] + 1))
    elif bound == "claim":
        answer = " " * 2 + "word " * LIMITS["claim_chars"] + answer
    elif bound == "source":
        sources[0].text += "x" * LIMITS["source_chars"]
    elif bound == "source_sentences":
        sources[0].text += " Sentence." * LIMITS["source_sentences"]
    elif bound == "source_clause":
        sources[0].text += " " + "x" * (LIMITS["claim_chars"] + 1)
    elif bound == "source_count":
        sources.extend(_source(index=i) for i in range(2, LIMITS["sources"] + 2))
    elif bound == "material_evidence":
        sources[0].material_evidence = [{}] * (LIMITS["material_evidence"] + 1)
    result = assess_answer(answer, sources)
    assert result["status"] != "supported", result
    assert result["coverage"]["truncated"] is True
    assert "assessment_coverage_incomplete" in result["warning_codes"]


def test_coverage_counts_are_consistent_and_public_values_are_json_serializable():
    result = _check("H3S has a Tc of 100 K at 2 GPa [1]. H3S has a Tc of 300 K at 2 GPa [1]. Some mechanism is unknown [1].")
    coverage = result["coverage"]
    assert coverage["total_claims"] == coverage["assessed_claims"] == 3
    assert coverage["supported_claims"] == coverage["contradicted_claims"] == coverage["undetermined_claims"] == 1
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_whole_source_caution_is_not_discarded_when_a_positive_clause_matches():
    result = _check(source=_source("H3S has a Tc of 100 K at 2 GPa. This result was not confirmed."))
    assert result["status"] == "undetermined"
    assert "source_context_caution_or_uncertainty" in result["claims"][0]["reason_codes"]


def test_checked_long_excerpt_is_visibly_clipped_without_claiming_incomplete_evaluation():
    source = _source("H3S has a Tc of 100 K" + " " * 510 + "at 2 GPa.")
    result = _check(source=source)
    assert result["status"] == "supported", result
    assert "evidence_excerpt_display_truncated" in result["warning_codes"]
    assert result["claims"][0]["evidence"][0]["excerpt"].endswith("…")
    assert len(result["claims"][0]["evidence"][0]["excerpt"]) == LIMITS["excerpt_chars"]
    assert result["coverage"]["truncated"] is False


@pytest.mark.parametrize("sentence,role,key", [
    ("H3S showed no superconducting transition at 100 K and ambient pressure", "transition_test_temperature", "tested_temperature_k"),
    ("H3S has no Tc of 100 K at ambient pressure", "negated_tc_value", "negated_tc_value_k"),
])
def test_supported_negative_reports_do_not_produce_a_positive_tc_label(sentence, role, key):
    result = _check(sentence + " [1].", _source(sentence + "."))
    assert result["status"] == "supported", result
    quantities = result["claims"][0]["quantities"]
    assert quantities["temperature_role"] == role
    assert quantities[key]["value"] == 100
    assert "tc_kelvin" not in quantities


def test_negative_observation_cannot_support_negation_of_a_specific_tc_value():
    result = _check("H3S has no Tc of 100 K at ambient pressure [1].", _source(
        "H3S showed no superconducting transition at 100 K and ambient pressure.",
    ))
    assert result["status"] == "undetermined"
    assert "negative_temperature_semantics_mismatch" in result["claims"][0]["reason_codes"]
    assert "tc_kelvin" not in result["claims"][0]["quantities"]


def test_contradicted_negative_draft_retains_test_temperature_not_tc():
    result = _check("H3S showed no superconducting transition at 100 K and ambient pressure [1].", _source(
        "H3S showed a superconducting transition at 100 K and ambient pressure.",
    ))
    assert result["status"] == "contradicted"
    quantities = result["claims"][0]["quantities"]
    assert quantities["temperature_role"] == "transition_test_temperature"
    assert "tested_temperature_k" in quantities and "tc_kelvin" not in quantities
