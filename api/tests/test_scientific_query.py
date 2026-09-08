"""Pure bounded grammar tests: preserve meaning, never grant result authority."""
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from models.scientific_query import ScientificQueryInterpretation
from services.scientific_query import (
    find_formula_mentions,
    interpret_scientific_query,
    match_source_formulas,
    normalize_query_formula,
)


@pytest.mark.parametrize("raw,expected", [
    ("MgB₂", "MgB2"), ("MgB2", "MgB2"), ("LaH_{10}", "LaH10"),
    ("LaH10", "LaH10"), ("LaH_10", "LaH10"), ("$LaH_{10}$", "LaH10"),
    (" FeSe ", "FeSe"), ("Ca(Fe0.5Co0.5)2As2", "Ca(Fe0.5Co0.5)2As2"),
    ("H3S", "H3S"), ("Fe[Se0.5Te0.5]", "Fe[Se0.5Te0.5]"), ("In", "In"),
    ("MgP2", "MgP2"), ("FeTc20K", "FeTc20K"),
])
def test_only_safe_formula_typography_is_normalized(raw, expected):
    value = normalize_query_formula(raw)
    assert value.version == "formula-query/1.0.0"
    assert value.status == "normalized" and value.normalized_formula == expected
    assert value.raw_formula == raw and value.reason_codes == []


@pytest.mark.parametrize("raw", [
    "D3S", "T3S", "¹⁰B", "10B", "[10B]", "^{10}B", "B^{10}", "Fe2+", "Fe²⁺",
    "Fe₂₊", "2H-NbSe2", "α-FeSe", "FeSe/SrTiO3", "FeSe@SrTiO3",
    "La2-xSrxCuO4", "La2−xSrxCuO4", "YBa2Cu3O7-δ", "FeSe_x", "FeSe_{x}",
    "YBCO", "BSCCO", "LSCO", "Mg B2", "(FeSe", "FeSe)", "Mg()B2",
    "LaH0", "0MgB2", "MgB2$", "Xx2", "NaCl·H2O", "Fe(Se,Te)",
])
def test_isotope_state_variable_charge_and_shorthand_are_never_merged(raw):
    value = normalize_query_formula(raw)
    assert value.status == "unresolved" and value.normalized_formula is None
    assert value.raw_formula == raw and value.reason_codes


def test_no_element_reordering_composition_reduction_or_isotope_aliasing():
    assert normalize_query_formula("B2Mg").normalized_formula == "B2Mg"
    assert normalize_query_formula("Mg2B4").normalized_formula == "Mg2B4"
    assert normalize_query_formula("H3S").normalized_formula != normalize_query_formula("D3S").normalized_formula
    assert normalize_query_formula("FeSe").normalized_formula != normalize_query_formula("2H-FeSe").normalized_formula


def test_source_mentions_keep_exact_offsets_beyond_query_limit_and_do_not_nfkc():
    text = "x " * 1500 + "MgB₂ and LaH_{10}; D3S and ¹⁰B."
    values = find_formula_mentions(text)
    assert [v.raw_text for v in values] == ["MgB₂", "LaH_{10}", "D3S", "¹⁰B"]
    assert values[0].start > 2000
    assert [v.normalization.normalized_formula for v in values] == ["MgB2", "LaH10", None, None]
    assert all(text[v.start:v.end] == v.raw_text for v in values)
    assert find_formula_mentions("ＭｇＢ２") == []


def test_source_membership_uses_full_retained_text_without_query_span_limits():
    assert match_source_formulas(" " * 21000 + "MgB₂", {"MgB2"}) == {"MgB2"}
    assert match_source_formulas("LaH10 " * 300 + "MgB₂", {"MgB2", "LaH10"}) == {"MgB2", "LaH10"}
    assert match_source_formulas("LaH10 " * 300, {"MgB2"}) == set()
    with pytest.raises(ValueError):
        find_formula_mentions("LaH10 " * 300)


@pytest.mark.parametrize("text", [
    "D3S ¹⁰B FeSe/SrTiO3 2H-NbSe2", "MgB2" + "x" * 1000,
    "MgB2/" + "SrTiO3" * 1000, "In this work. No superconductivity. As a result.",
    "PrefixMgB2Suffix", "ＭｇＢ２", "LaH_{10-x}",
])
def test_source_membership_does_not_split_unsafe_qualified_tokens_or_element_words(text):
    assert match_source_formulas(text, {"H3S", "B", "FeSe", "NbSe2", "MgB2", "In", "No", "As", "LaH10"}) == set()


def test_source_membership_element_context_and_unicode_boundaries():
    assert match_source_formulas("Tc of In; MgB₂和LaH_{10}。", {"In", "MgB2", "LaH10"}) == {"In", "MgB2", "LaH10"}
    assert match_source_formulas("In", {"In"}) == {"In"}
    assert match_source_formulas("nothing relevant", set()) == set()
    for wanted in ({"D3S"}, {"MgB₂"}, "MgB2", ["MgB2"] * 33):
        with pytest.raises(ValueError):
            match_source_formulas("MgB2", wanted)
    with pytest.raises(ValueError):
        match_source_formulas("x" * (16 * 1024 * 1024 + 1), {"MgB2"})
    with pytest.raises(ValueError):
        match_source_formulas("氢" * (6 * 1024 * 1024), {"MgB2"})


def test_english_articles_do_not_become_elemental_candidates_or_erase_negation():
    query = interpret_scientific_query("In experimental reports, what is the Tc of MgB2?")
    assert query.status == "resolved" and [f.raw_text for f in query.formulas] == ["MgB2"]
    assert [f.raw_text for f in interpret_scientific_query("What is Tc of In?").formulas] == ["In"]
    assert [f.raw_text for f in find_formula_mentions("In")] == ["In"]
    negative = interpret_scientific_query("No computed MgB2 Tc")
    assert negative.status == "clarification_required"
    assert any(u.raw_text == "No" and u.reason_code == "unsupported_negation" for u in negative.unresolved_clauses)


def test_property_regex_does_not_match_inside_a_formula():
    for formula in ("MgP2", "FeTc20K"):
        result = interpret_scientific_query(formula)
        assert result.status == "resolved" and result.intent == "general"
        assert result.formulas[0].normalization.normalized_formula == formula
        assert result.constraints == []


@pytest.mark.parametrize("query,field,relation,value,lower,upper", [
    ("MgB2 Tc = 39 K", "tc_kelvin", "exact", 39, None, None),
    ("MgB2 Tc above 30 K", "tc_kelvin", "gt", None, 30, None),
    ("MgB2 Tc at least 30 K", "tc_kelvin", "ge", None, 30, None),
    ("MgB2 Tc ≤ 40 K", "tc_kelvin", "le", None, None, 40),
    ("MgB2 Tc below 40 K", "tc_kelvin", "lt", None, None, 40),
    ("Tc between 30 K and 40 K", "tc_kelvin", "interval", None, 30, 40),
    ("Tc 30-40 K", "tc_kelvin", "interval", None, 30, 40),
    ("Tc 30000 mK", "tc_kelvin", "exact", 30, None, None),
    ("MgB2 临界温度大于30开尔文", "tc_kelvin", "gt", None, 30, None),
    ("MgB2 临界温度从30K到40K", "tc_kelvin", "interval", None, 30, 40),
    ("FeSe pressure between 100 MPa and 1 GPa", "pressure_gpa", "interval", None, 0.1, 1),
    ("pressure = 1000 MPa", "pressure_gpa", "exact", 1, None, None),
    ("pressure at most 10 kbar", "pressure_gpa", "le", None, None, 1),
    ("LaH10 压力至少150吉帕", "pressure_gpa", "ge", None, 150, None),
    ("MgB2 压力低于100兆帕", "pressure_gpa", "lt", None, None, 0.1),
])
def test_numerical_units_comparisons_and_bounds(query, field, relation, value, lower, upper):
    result = interpret_scientific_query(query)
    assert result.status == "resolved", result.unresolved_clauses
    assert result.intent == "numerical"
    quantity, = result.constraints
    assert (quantity.field, quantity.relation, quantity.value, quantity.lower, quantity.upper) == (field, relation, value, lower, upper)
    assert quantity.unit == {"tc_kelvin": "K", "pressure_gpa": "GPa"}[field]
    assert quantity.unit_basis == "explicit"
    assert query[quantity.start:quantity.end] == quantity.raw_text


@pytest.mark.parametrize("query", ["What is Tc of LaH10 at 150 GPa?", "LaH10 Tc at 150 GPa", "LaH10 的Tc在150吉帕是多少？"])
def test_tc_at_pressure_is_context_not_a_temperature_unit_mismatch(query):
    result = interpret_scientific_query(query)
    assert result.status == "resolved" and result.intent == "numerical"
    assert result.requested_fields == ["pressure_gpa", "tc_kelvin"]
    constraint, = result.constraints
    assert constraint.field == "pressure_gpa" and constraint.value == 150


def test_ambient_is_explicit_and_not_inferred_from_numeric_zero_or_missing():
    ambient = interpret_scientific_query("MgB2 Tc at ambient pressure")
    zero = interpret_scientific_query("MgB2 Tc at 0 GPa")
    missing = interpret_scientific_query("What is Tc of MgB2?")
    assert ambient.status == zero.status == missing.status == "resolved"
    assert ambient.constraints[0].unit_basis == "explicit_ambient_reference"
    assert ambient.constraints[0].value == 0
    assert zero.constraints[0].unit_basis == "explicit"
    assert missing.constraints == [] and missing.evidence_constraints == []


@pytest.mark.parametrize("query,field,value", [
    ("experimental MgB2 Tc", "knowledge_origin", "Observed"),
    ("computed MgB2 Tc", "knowledge_origin", "Computed"),
    ("inferred MgB2 Tc", "knowledge_origin", "Inferred"),
    ("AI-proposed MgB2 Tc", "knowledge_origin", "AI-Proposed"),
    ("unknown origin MgB2 Tc", "knowledge_origin", "Unknown"),
    ("primary MgB2 Tc", "source_role", "primary"),
    ("cited MgB2 Tc", "source_role", "cited"),
    ("MgB2 实验 Tc", "knowledge_origin", "Observed"),
    ("MgB2 理论计算 Tc", "knowledge_origin", "Computed"),
    ("MgB2 一手 Tc", "source_role", "primary"),
    ("MgB2 二手 Tc", "source_role", "cited"),
    ("MgB2 未检测到超导", "experimental_outcome", "not_detected"),
    ("MgB2 superconductivity was not detected", "experimental_outcome", "not_detected"),
    ("MgB2 did not detect superconductivity", "experimental_outcome", "not_detected"),
    ("MgB2 superconductivity was observed", "experimental_outcome", "positive_reported"),
    ("MgB2 观察到超导", "experimental_outcome", "positive_reported"),
])
def test_explicit_evidence_categories_retain_condition_specific_polarity(query, field, value):
    result = interpret_scientific_query(query)
    assert result.status == "resolved", result.unresolved_clauses
    assert result.intent == "numerical"
    category, = result.evidence_constraints
    assert (category.field, category.value) == (field, value)
    assert result.raw_query[category.start:category.end] == category.raw_text
    assert result.scientific_acceptance is False


@pytest.mark.parametrize("query", [
    "What is the role of pressure in high-Tc hydrides?", "Explain phonon pairing",
    "Explain the pressure dependence of Tc in MgB2", "Why is Tc high in hydrides?",
    "压力如何影响氢化物的Tc？", "解释声子配对机制", "How does MgB2 superconduct?",
])
def test_explanatory_content_remains_opaque_not_fake_numerical_constraints(query):
    result = interpret_scientific_query(query)
    assert result.status == "resolved", result.unresolved_clauses
    assert result.intent == "mechanism"
    assert result.raw_query == query and result.requested_fields == []
    assert result.constraints == [] and result.evidence_constraints == []


def test_mixed_comparison_and_formula_only_intents():
    assert interpret_scientific_query("What is Tc of MgB2 and why?").intent == "mixed"
    assert interpret_scientific_query("Explain MgB2 pairing at 150 GPa").intent == "mixed"
    shared = interpret_scientific_query("Compare MgB2 and LaH10 at 150 GPa")
    assert shared.intent == "comparison" and shared.status == "resolved"
    assert shared.constraints[0].value == 150
    assert interpret_scientific_query("What is superconductivity?").intent == "general"
    for raw, normalized in (("MgB₂", "MgB2"), ("LaH_{10}", "LaH10")):
        result = interpret_scientific_query(raw)
        assert result.intent == "general" and result.status == "resolved"
        assert result.raw_query == raw and result.normalized_query == normalized


@pytest.mark.parametrize("query", ["Compare MgB2 and Nb Tc and explain why", "比较 MgB2 和 Nb 的临界温度，为什么？"])
def test_explanation_does_not_erase_numerical_fields_from_a_comparison(query):
    result = interpret_scientific_query(query)
    assert result.status == "resolved" and result.intent == "comparison"
    assert result.requested_fields == ["tc_kelvin"]
    assert len(result.formulas) == 2 and result.raw_query == query


def test_pure_mechanism_comparison_does_not_invent_numerical_fields():
    result = interpret_scientific_query("Compare the pairing mechanisms of MgB2 and Nb")
    assert result.status == "resolved" and result.intent == "comparison"
    assert result.requested_fields == [] and result.constraints == []


@pytest.mark.parametrize("query", ["Synthetic superconductivity", "old snapshot", "unmatchedqueryneedle", "strong coupling", "custom_search_keyword", "Synthetic MgB₂ superconductivity.", "Tell me about superconductivity", "synthetic structure disclosure", "hydride pressure result"])
def test_ordinary_fulltext_keywords_are_preserved_not_rejected_as_bad_filters(query):
    result = interpret_scientific_query(query)
    assert result.status == "resolved" and result.intent == "general"
    assert result.raw_query == query and result.constraints == [] and result.evidence_constraints == []


@pytest.mark.parametrize("query", ["Tc", "pressure", "MgB2 pressure", "Show pressure data", "What is the pressure?"])
def test_actual_value_requests_do_not_turn_into_keyword_bags(query):
    result = interpret_scientific_query(query)
    assert result.intent == "numerical" and result.requested_fields


@pytest.mark.parametrize("query,reason", [
    ("MgB2 Tc onset", "criterion_constraint_unresolved"),
    ("MgB2 零电阻 Tc", "criterion_constraint_unresolved"),
    ("MgB2 bulk Tc", "state_constraint_unresolved"),
    ("Explain MgB2 pairing in a thin film", "state_constraint_unresolved"),
    ("Explain isotope effects in MgB2", "isotope_constraint_unresolved"),
    ("MgB2 doped Tc", "doping_constraint_unresolved"),
    ("MgB2 Tc before 2020", "temporal_constraint_unresolved"),
    ("MgB2 Tc not computed", "unsupported_negation"),
    ("MgB2 Tc computed or experimental", "unsupported_disjunction"),
    ("MgB2 Tc predicted", "ambiguous_origin"),
    ("MgB2 Tc approximately 39 K", "approximation_unresolved"),
    ("MgB2 Tc 39 ± 1 K", "quantity_uncertainty_unresolved"),
    ("MgB2 Tc > 100", "quantity_unit_or_syntax_unresolved"),
    ("MgB2 Tc < 150 GPa", "quantity_unit_or_syntax_unresolved"),
    ("MgB2 Tc 30 °C", "quantity_unit_or_syntax_unresolved"),
    ("MgB2 Tc 40-30 K", "quantity_unit_or_syntax_unresolved"),
    ("MgB2 Tc -1 K", "quantity_domain_unresolved"),
    ("MgB2 pressure -1 GPa", "quantity_domain_unresolved"),
    ("MgB2 Tc > 40 K and Tc < 30 K", "contradictory_quantity_constraints"),
    ("MgB2 Tc > 30 K and Tc <= 30 K", "contradictory_quantity_constraints"),
    ("MgB2 computed experimental Tc", "conflicting_evidence_constraints"),
    ("Compare MgB2 Tc", "comparison_targets_unresolved"),
    ("MgB2 and LaH10 Tc > 20 K", "material_constraint_scope_unresolved"),
    ("Compare MgB2 Tc 39 K and LaH10 pressure 150 GPa", "material_constraint_scope_unresolved"),
    ("Compare computed MgB2 and LaH10 Tc", "material_constraint_scope_unresolved"),
    ("primary MgB2 and LaH10 Tc", "material_constraint_scope_unresolved"),
])
def test_unsupported_or_ambiguous_conditions_require_clarification(query, reason):
    result = interpret_scientific_query(query)
    assert result.status == "clarification_required"
    assert reason in {item.reason_code for item in result.unresolved_clauses}
    assert result.clarification_questions and result.raw_query == query
    assert all(query[item.start:item.end] == item.raw_text for item in result.unresolved_clauses)


@pytest.mark.parametrize("query", [
    "MgB2 Tc magical ", "MgB2 Tc 39 K at 2 T", "MgB2 Tc >100 K below200 K",
    "MgB2 Tc 39 K except LaH10", "MgB2 not detected down to 2 K",
    "Explain MgB2 pairing below 50 kOe", "Explain MgB2 pairing x=0.2", "Explain MgB2 at low pressure",
    "Explain pairing in D", "Explain pairing in T",
    "MgB2 Tc at zero field", "MgB2 Tc after 2020-01-01", "MgB2 Tc unknown-unit=20",
])
def test_unknown_tail_detection_limit_or_unsupported_quantifier_never_disappears(query):
    result = interpret_scientific_query(query)
    assert result.status == "clarification_required"
    assert result.raw_query == query and result.unresolved_clauses
    assert result.scientific_acceptance is False


def test_request_and_scan_hard_bounds_do_not_silently_truncate():
    for raw in (None, True, "", "   ", "x" * 2001):
        with pytest.raises(ValueError):
            interpret_scientific_query(raw)
    with pytest.raises(ValueError):
        find_formula_mentions("x" * 20001)
    with pytest.raises(ValueError):
        find_formula_mentions("MgB2 " * 257)
    with pytest.raises(ValueError):
        normalize_query_formula("MgB2" * 51)
    result = interpret_scientific_query(" and ".join(["MgB2"] * 33))
    assert result.status == "clarification_required"
    assert result.unresolved_clauses[0].reason_code == "query_scope_limit"


def test_query_mention_overflow_is_complete_clarification_not_http_exception():
    raw = "Nb " * 257
    assert len(raw) < 2000
    result = interpret_scientific_query(raw)
    assert result.status == "clarification_required"
    assert result.formulas == [] and result.normalized_query == result.raw_query == raw
    assert result.unresolved_clauses[0].raw_text == raw
    assert result.unresolved_clauses[0].reason_code == "query_complexity_unresolved"


@pytest.mark.parametrize("raw", ["Nb " * 33, "Tc > 30 K and " * 33])
def test_formula_and_quantity_scope_limits_do_not_publish_a_partial_parse(raw):
    result = interpret_scientific_query(raw)
    assert result.status == "clarification_required"
    assert result.formulas == [] and result.constraints == []
    assert result.unresolved_clauses[0].raw_text == raw
    assert result.unresolved_clauses[0].reason_code == "query_scope_limit"


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(unknown=True),
    lambda d: d.update(scientific_acceptance=True),
    lambda d: d["constraints"][0].update(lower=True),
    lambda d: d["constraints"][0].update(lower="30"),
    lambda d: d["constraints"][0].update(lower=float("nan")),
    lambda d: d["constraints"][0].update(start=True),
    lambda d: d["constraints"][0].update(raw_text="wrong"),
    lambda d: d["constraints"][0].update(unit="GPa"),
    lambda d: d["constraints"][0].update(value=40.0),
    lambda d: d["constraints"][0].update(unit_basis="explicit_ambient_reference"),
    lambda d: d["formulas"][0]["normalization"].update(raw_formula="LaH10"),
    lambda d: d["formulas"][0]["normalization"].update(reason_codes=["arbitrary prose"]),
    lambda d: d.update(status="clarification_required"),
    lambda d: d.update(requested_fields=["tc_kelvin", "tc_kelvin"]),
])
def test_dto_is_closed_strict_finite_and_raw_span_faithful(mutate):
    value = copy.deepcopy(interpret_scientific_query("MgB2 Tc > 30 K").model_dump())
    mutate(value)
    with pytest.raises(ValidationError):
        ScientificQueryInterpretation.model_validate(value)
