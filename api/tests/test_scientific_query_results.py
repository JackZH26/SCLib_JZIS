"""Adversarial same-occurrence scientific reports; no model or source calls."""
from __future__ import annotations

import copy

import pytest

from models.scientific_query import ScientificQueryInterpretation
from models.scientific_query_result import ScientificQueryResult
from services.scientific_filters import ResultFilters
from services.scientific_query_results import ScientificResultSelectionError, select_record_results


def constraint(field="tc_kelvin", relation="ge", value=20, *, ambient=False):
    key = "value" if relation == "exact" else "lower" if relation in {"gt", "ge"} else "upper"
    fields = {key: value} if relation != "interval" else {"lower": value[0], "upper": value[1]}
    return {"field": field, "relation": relation, "unit": "K" if field == "tc_kelvin" else "GPa",
            "unit_basis": "explicit_ambient_reference" if ambient else "explicit", **fields,
            "raw_text": "Tc", "start": 0, "end": 2}


def interpretation(*constraints, evidence=(), formula=None):
    raw = "Tc" if formula is None else "Tc " + formula
    formulas = []
    if formula is not None:
        from services.scientific_query import normalize_query_formula
        formulas = [{"raw_text": formula, "start": 3, "end": 3 + len(formula),
                     "normalization": normalize_query_formula(formula)}]
    return ScientificQueryInterpretation(raw_query=raw, normalized_query=raw, language="en", intent="numerical", status="resolved",
        requested_fields=["tc_kelvin"], constraints=list(constraints), formulas=formulas,
        evidence_constraints=[{"field": field, "value": value, "raw_text": "Tc", "start": 0, "end": 2} for field, value in evidence])


def record(**changes):
    return {"formula": "MgB2", "tc_kelvin": "39 K", "pressure_condition": "ambient pressure",
            "knowledge_origin": "Observed", "source_role": "primary", "measurement_method": "resistivity", **changes}


def select(records, query=None, *, filters=None):
    return select_record_results(records, query or interpretation(constraint()), scope_id="synthetic-generation-member", filters=filters)


def test_never_combine_tc_pressure_origin_or_formula_across_records():
    query = interpretation(constraint(value=100), constraint("pressure_gpa", "le", 1), evidence=(("knowledge_origin", "Observed"),))
    records = [record(tc_kelvin="150 K", pressure_gpa="150 GPa", pressure_condition=None),
               record(tc_kelvin="10 K", pressure_condition="ambient pressure")]
    assert select(records, query) == []
    records[0]["knowledge_origin"] = "Computed"
    records[0]["measurement_method"] = "DFT"
    assert select(records, interpretation(constraint(value=100), evidence=(("knowledge_origin", "Observed"),))) == []


@pytest.mark.parametrize("raw,relation,limit,expected", [
    ("20 K", "gt", 20, False), ("20 K", "ge", 20, True), (">20 K", "gt", 20, True),
    (">=20 K", "gt", 20, False), ("<20 K", "lt", 20, True), ("<=20 K", "lt", 20, False),
    ("10-30 K", "ge", 20, False), ("20-30 K", "ge", 20, True),
    ("25 ± 5 K", "ge", 20, True), ("25 ± 5 K", "gt", 20, False),
    ("25 ± 6 K", "ge", 20, False), ("~30 K", "ge", 20, False),
    ("30 K", "interval", (20, 40), True), ("10-30 K", "interval", (20, 40), False),
    ("30 ± 2 K", "exact", 30, False), ("30 K", "exact", 30, True),
    ("<50 K", "ge", 20, False), (">50 K", "le", 100, False),
])
def test_full_extent_and_strict_endpoint_semantics(raw, relation, limit, expected):
    result = select([record(tc_kelvin=raw)], interpretation(constraint(relation=relation, value=limit)))
    assert bool(result) is expected


def test_raw_units_bounds_and_uncertainty_are_preserved_not_cached_scalars():
    value = record(tc_kelvin=25.0, raw_extraction={"tc_kelvin": "25 ± 5 K"})
    result, = select([value], interpretation(constraint(value=20)))
    assert result.tc.uncertainty == 5 and result.tc.value == 25
    assert result.tc.uncertainty_interpretation == "unspecified"
    assert result.tc.unit_basis == "explicit"
    assert select([value], interpretation(constraint(relation="gt", value=20))) == []
    assert select([record(tc_kelvin=0.025, raw_extraction={"tc_kelvin": "25 mK"})], interpretation(constraint(value=0.02)))


@pytest.mark.parametrize("changes", [
    {"raw_extraction": {"tc_kelvin": "10 K"}}, {"tc": "10 K"},
    {"scientific_values": {"tc_kelvin": {"value": 500, "status": "parsed"}}},
    {"scientific_values": {"tc_kelvin": {"raw_value": "39 K"}}, "raw_extraction": {"tc_kelvin": "50 K"}},
    {"tc_kelvin": True}, {"tc_kelvin": "-3 K"}, {"tc_kelvin": "NaN"},
    {"validation_flags": ["tc_kelvin:invalid_type"]},
    {"raw_extraction": {"knowledge_origin": "Computed"}},
    {"raw_extraction": {"source_role": "cited"}},
    {"knowledge_origin": ["Observed"]}, {"validation_flags": ["knowledge_origin:invalid_type"]},
    {"result_status": True}, {"result_status": "unknown"},
    {"result_status": "positive", "raw_extraction": {"result_status": "not_detected"}},
    {"result_status": "positive", "transition_observed": False},
    {"tc_relation": "lt"}, {"raw_extraction": {"value_relation": "lt"}},
    {"validation_flags": "tc_kelvin:invalid_type"},
])
def test_conflicting_or_malformed_copies_never_pass_tc_predicate(changes):
    assert select([record(**changes)]) == []


@pytest.mark.parametrize("changes,expected", [
    ({"pressure_gpa": None, "pressure_condition": None}, False),
    ({"pressure_gpa": 0, "pressure_condition": None}, False),
    ({"pressure_gpa": "0 GPa", "pressure_condition": None}, False),
    ({"pressure_gpa": 0, "pressure_condition": None, "raw_extraction": {"pressure_gpa": "ambient"}}, True),
    ({"pressure_gpa": 10}, False),
    ({"pressure_gpa": True}, False),
    ({"pressure_condition": True}, False),
    ({"raw_extraction": {"pressure_gpa": "10 GPa"}}, False),
    ({"pressure": "10 GPa"}, False),
    ({}, True),
])
def test_ambient_requires_direct_same_occurrence_assertion(changes, expected):
    query = interpretation(constraint("pressure_gpa", "exact", 0, ambient=True))
    assert bool(select([record(**changes)], query)) is expected


def test_pressure_unit_conversion_and_uncertainty_use_entire_extent():
    value = record(pressure_gpa=10.0, pressure_condition=None, raw_extraction={"pressure_gpa": "100 ± 10 kbar"},
                   scientific_values={"pressure_gpa": {"raw_value": "100 ± 10 kbar"}})
    result, = select([value], interpretation(constraint("pressure_gpa", "interval", (9, 11))))
    assert result.pressure.value == 10 and result.pressure.uncertainty == 1
    assert select([value], interpretation(constraint("pressure_gpa", "gt", 9))) == []
    assert select([value], interpretation(constraint("pressure_gpa", "lt", 11))) == []


def test_not_detected_tmin_is_not_tc_or_universal_negative_label():
    value = record(result_status="not_detected", tc_kelvin=None, minimum_temperature_k="2 K")
    assert select([value], interpretation(constraint(value=1))) == []
    result, = select([value], interpretation(evidence=(("experimental_outcome", "not_detected"),)))
    assert result.tc.status == "unreported" and result.minimum_temperature.value == 2
    assert result.outcome_state == "not_detected"
    assert result.scientific_acceptance is result.ml_training_eligible is result.detection_adequacy_verified is False
    assert result.reported_context.measurement_method == "resistivity"
    assert "non_detection_is_condition_specific_not_negative_training_label" in result.warning_codes


def test_incomplete_negative_remains_report_only_and_does_not_display_positive_tc():
    value = record(result_status="not_detected", tc_kelvin=999, measurement_method=None)
    result, = select([value], interpretation(evidence=(("experimental_outcome", "not_detected"),)))
    assert result.tc.status == "invalid" and result.tc.value is None
    assert "minimum_test_temperature_unreported_or_invalid" in result.warning_codes
    assert "non_detection_measurement_method_unreported" in result.warning_codes


def test_explicit_positive_constraint_not_satisfied_by_tc_or_paper_genre():
    query = interpretation(evidence=(("experimental_outcome", "positive_reported"),))
    assert select([record()], query) == []
    assert select([record(result_status="positive")], query)
    value = {"formula": "MgB2", "tc_kelvin": 39, "paper_type": "experimental", "credibility_tier": "T1"}
    assert select([value], interpretation(evidence=(("knowledge_origin", "Observed"),))) == []


def test_formula_typography_only_never_casefolds_or_reorders_composition():
    query = interpretation(formula="MgB₂")
    result, = select([record()], query)
    assert result.formula == "MgB2"
    assert select([record(formula="B2Mg")], query) == []
    assert select([record(formula="CO")], interpretation(formula="Co")) == []
    assert select([record(raw_extraction={"formula": "Nb"})], query) == []
    assert select([record(raw_extraction={"formula": "MgB₂"})], query)


def test_context_ambiguity_is_reported_without_resolving_sample_or_phase():
    result, = select([record(tc_type="onset", tc_criterion="zero_resistance", sample_label="S1",
                             raw_extraction={"sample_label": "S2"}, structure_phase="alpha")])
    assert result.reported_context.tc_criterion is None and result.reported_context.sample_label is None
    assert result.reported_context.structure_phase == "alpha"
    assert "tc_criterion_ambiguous" in result.warning_codes and "sample_label_ambiguous" in result.warning_codes


def test_closed_projection_never_exports_private_raw_fields_or_mutates_input():
    records = [record(source_quote="PRIVATE QUOTE", evidence_text="PRIVATE SOURCE TEXT", reviewer_email="PRIVATE EMAIL",
                      source_locator={"section": "PRIVATE SECTION"}, raw_extraction={"private": "PRIVATE PAYLOAD"})]
    before = copy.deepcopy(records)
    result, = select(records)
    body = result.model_dump_json()
    assert "PRIVATE" not in body and records == before
    assert result.result_id == select(records)[0].result_id
    assert result.record_index == 0
    assert ScientificQueryResult.model_validate(result.model_dump()) == result
    with pytest.raises(ValueError):
        ScientificQueryResult.model_validate({**result.model_dump(), "scientific_acceptance": True})


@pytest.mark.parametrize("records", [[{}] * 1001, [{"formula": "Nb", "private": "x" * (1024 * 1024)}], [{"formula": "Nb", "tc_kelvin": float("nan")}], "not records"])
def test_closed_inventory_resource_bounds(records):
    with pytest.raises(ScientificResultSelectionError):
        select(records)


@pytest.mark.parametrize("value", [True, "20", float("inf")])
def test_untrusted_interpretation_numbers_do_not_coerce(value):
    query = interpretation(constraint()).model_dump()
    query["constraints"][0]["lower"] = value
    with pytest.raises(ScientificResultSelectionError):
        select([record()], query)


@pytest.mark.parametrize("changes", [
    {"tc_kelvin": "300 K"}, {"family": "mgb2", "tc_kelvin": "60 K"},
    {"pressure_gpa": "600 GPa", "pressure_condition": None},
])
def test_local_anomaly_review_not_bypassed_by_numeric_queries_or_forged_approvals(changes):
    value = record(**changes)
    field = "pressure_gpa" if "pressure_gpa" in changes else "tc_kelvin"
    query = interpretation(constraint(field, "ge", 20 if field == "tc_kelvin" else 1))
    assert select([value], query) == []
    value.update(review_status="approved", scientific_acceptance=True,
                 anomaly_review={"status": "approved", "review_required_properties": []})
    assert select([value], query) == []
    result, = select([value], interpretation())
    assert "local_anomaly_review_required" in result.warning_codes
    assert any(code.startswith("local_review_rule_") for code in result.warning_codes)
    assert result.scientific_acceptance is False


def test_raw_family_and_raw_quantity_determine_review_not_normalized_cache():
    value = record(tc_kelvin=60.0, raw_extraction={"tc_kelvin": "60 ± 5 K", "family": "mgb2"})
    assert select([value], interpretation(constraint(value=50))) == []
    result, = select([value], interpretation())
    assert result.tc.uncertainty == 5 and "local_review_rule_tc_family_reference_review" in result.warning_codes


def test_ambient_constraint_preserves_existing_ambient_review_admission():
    value = record(tc_kelvin="160 K")
    assert select([value], interpretation(constraint("pressure_gpa", "exact", 0, ambient=True))) == []
    result, = select([value], interpretation())
    assert "local_review_rule_tc_ambient_reference_review" in result.warning_codes


@pytest.mark.parametrize("question", ["MgB2 Tc > 30 K at ambient pressure", "MgB₂ 的 Tc 大于 30 K，常压"])
def test_actual_bilingual_interpreter_feeds_same_occurrence_selector(question):
    from services.scientific_query import interpret_scientific_query
    query = interpret_scientific_query(question)
    assert query.status == "resolved"
    result, = select([record(), record(tc_kelvin="29 K"), record(formula="Nb")], query)
    assert result.formula == "MgB2" and result.record_index == 0


def test_unsupported_criterion_remains_clarification_not_relaxed_numeric_query():
    from services.scientific_query import interpret_scientific_query
    query = interpret_scientific_query("MgB2 Tc onset > 30 K")
    assert query.status == "clarification_required"
    assert select([record(tc_type="onset")], query) == []


@pytest.mark.parametrize("fault", ["wrong_unit", "interval_shape", "nan", "private_warning"])
def test_response_dto_fails_closed_on_inconsistent_quantity_shapes(fault):
    body = select([record()])[0].model_dump()
    if fault == "wrong_unit":
        body["tc"]["unit"] = "GPa"
    elif fault == "interval_shape":
        body["tc"]["relation"] = "interval"
    elif fault == "nan":
        body["tc"]["value"] = float("nan")
    else:
        body["warning_codes"] = ["Private arbitrary source prose must not fit this field"]
    with pytest.raises(ValueError):
        ScientificQueryResult.model_validate(body)


def test_external_tc_filter_uses_original_uncertainty_not_cached_point():
    value = record(tc_kelvin=39, raw_extraction={"tc_kelvin": "39 ± 5 K"})
    query = interpretation(formula="MgB2")
    assert select([value], query, filters=ResultFilters(tc_min=38)) == []
    result, = select([value], query, filters=ResultFilters(tc_min=34))
    assert result.tc.value == 39 and result.tc.uncertainty == 5


def test_external_filters_enable_occurrence_selection_without_parsed_scientific_terms():
    from services.scientific_query import interpret_scientific_query
    query = interpret_scientific_query("superconductivity")
    assert query.status == "resolved" and query.requested_fields == [] and query.formulas == []
    value = record(tc_kelvin=39, raw_extraction={"tc_kelvin": "39 ± 5 K"})
    assert select([value], query) == []
    assert select([value], query, filters=ResultFilters(tc_min=38)) == []
    result, = select([value], query, filters=ResultFilters(tc_min=34))
    assert result.tc.uncertainty == 5


@pytest.mark.parametrize("original,scalar,lower,upper", [
    ("100 ± 10 kbar", 10, 9, 11), ("90-110 kbar", 9, 9, 11),
])
def test_external_pressure_filters_use_original_extent_not_cached_point(original, scalar, lower, upper):
    value = record(pressure_gpa=scalar, pressure_condition=None, raw_extraction={"pressure_gpa": original})
    query = interpretation()
    assert select([value], query, filters=ResultFilters(pressure_min=lower + 0.5)) == []
    assert select([value], query, filters=ResultFilters(pressure_max=upper - 0.5)) == []
    result, = select([value], query, filters=ResultFilters(pressure_min=lower, pressure_max=upper))
    assert result.pressure.status == "parsed"
    assert result.pressure.uncertainty == 1 if "±" in original else result.pressure.lower == 9


def test_external_all_filters_match_one_raw_resolved_occurrence():
    filters = ResultFilters(families=("mgb2",), tc_min=30, pressure_min=9, pressure_max=11,
                            origins=("Observed",), source_role="primary", experimental_only=True)
    good = record(knowledge_origin=None, source_role=None, pressure_condition=None, tc_kelvin=39, pressure_gpa=10,
        raw_extraction={"family": "mgb2", "tc_kelvin": "39 ± 5 K", "pressure_gpa": "100 ± 10 kbar",
                        "knowledge_origin": "Observed", "source_role": "primary"})
    lower_tc = {**good, "tc_kelvin": 29, "raw_extraction": {**good["raw_extraction"], "tc_kelvin": "29 ± 5 K"}}
    wrong_pressure = {**good, "pressure_gpa": 20, "raw_extraction": {**good["raw_extraction"], "pressure_gpa": "200 kbar"}}
    wrong_family = {**good, "raw_extraction": {**good["raw_extraction"], "family": "elemental"}}
    assert select([lower_tc, wrong_pressure, wrong_family], interpretation(), filters=filters) == []
    result, = select([lower_tc, good, wrong_pressure], interpretation(), filters=filters)
    assert result.record_index == 1 and result.family == "mgb2"
    assert result.result_classification.knowledge_origin == "Observed"
    for changes in ({"knowledge_origin": "Computed"}, {"source_role": "cited"}, {"family": "elemental"}):
        assert select([{**good, **changes}], interpretation(), filters=filters) == []


@pytest.mark.parametrize("changes", [
    {"pressure_condition": None}, {"pressure_condition": None, "pressure_gpa": 0},
    {"pressure_condition": None, "pressure_gpa": "0 GPa"},
    {"pressure_condition": None, "pressure_gpa": "~0.1 GPa"},
])
def test_external_unknown_or_approximate_pressure_never_proves_bounds(changes):
    value = record(**changes)
    assert select([value], interpretation(), filters=ResultFilters(pressure_max=1, include_unknown_pressure=True)) == []
    assert select([value], interpretation(), filters=ResultFilters(ambient_only=True, include_unknown_pressure=True)) == []
    assert select([value], interpretation(), filters=ResultFilters(include_unknown_pressure=True))


def test_external_ambient_requires_direct_source_and_respects_review_hold():
    assert select([record()], interpretation(), filters=ResultFilters(ambient_only=True))
    assert select([record(pressure_gpa=0, pressure_condition=None, raw_extraction={"pressure_condition": "ambient pressure"})],
                  interpretation(), filters=ResultFilters(ambient_only=True))
    assert select([record(tc_kelvin="160 K")], interpretation(), filters=ResultFilters(ambient_only=True)) == []


@pytest.mark.parametrize("filters,changes", [
    (ResultFilters(tc_min=20), {"tc_kelvin": "300 K"}),
    (ResultFilters(tc_min=20), {"tc_kelvin": "60 K", "family": "mgb2"}),
    (ResultFilters(pressure_min=1), {"pressure_condition": None, "pressure_gpa": "600 GPa"}),
    (ResultFilters(tc_min=1), {"result_status": "not_detected"}),
    (ResultFilters(positive_tc=True), {"result_status": "not_detected"}),
    (ResultFilters(positive_tc=True), {"tc_kelvin": "0 K"}),
])
def test_external_predicates_keep_anomaly_and_negative_admission(filters, changes):
    assert select([record(**changes)], interpretation(), filters=filters) == []


def test_external_positive_tc_respects_strict_reported_lower_endpoint():
    assert select([record(tc_kelvin=">0 K")], interpretation(), filters=ResultFilters(positive_tc=True))
    assert select([record(tc_kelvin=">=0 K")], interpretation(), filters=ResultFilters(positive_tc=True)) == []


@pytest.mark.parametrize("filters", [
    {"tc_min": 30}, ResultFilters(tc_min=True), ResultFilters(tc_min="30"),
    ResultFilters(pressure_max=float("inf")), ResultFilters(pressure_min=10, pressure_max=1),
    ResultFilters(ambient_only=1), ResultFilters(families=["mgb2"]), ResultFilters(origins=("experimental",)),
    ResultFilters(source_role=["primary"]), ResultFilters(only_aps=True), ResultFilters(min_tier="T1"),
])
def test_external_filter_contract_never_coerces_or_infers_source_authority(filters):
    with pytest.raises(ScientificResultSelectionError):
        select([record(paper_id="aps:forged", credibility_tier="T1")], interpretation(), filters=filters)
