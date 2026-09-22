"""Public scientific lookup wire invariants; not a source-acceptance test.

The row's numerical projection comes from the real pure selector. Synthetic
binding IDs test envelope consistency only, never immutable-ledger authority.
The API conftest still requires the disposable native/Docker safety runner.
"""
from __future__ import annotations

import copy
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from models.scientific_lookup import ScientificLookupStatus, ScientificResultBinding
from models.search import AskResponse, SearchResponse
from services.scientific_query import interpret_scientific_query
from services.scientific_query_results import select_record_results

GENERATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EVENT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
EVIDENCE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PARENT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
SHA = "a" * 64


@pytest.fixture(params=[SearchResponse, AskResponse], ids=["search", "ask"])
def response_model(request):
    return request.param


def payload(model, *, tc="39 K", pressure="ambient pressure"):
    query = interpret_scientific_query("Tc > 20 K for MgB₂")
    assert query.status == "resolved"
    result, = select_record_results([{
        "formula": "MgB2", "tc_kelvin": tc, "pressure_condition": pressure,
        "knowledge_origin": "Observed", "source_role": "primary",
        "measurement_method": "resistivity", "result_status": "positive",
    }], query, scope_id="synthetic-wire-contract")
    base = ({"total": 0, "results": []} if model is SearchResponse else
            {"answer": "See qualified machine extraction records.", "sources": [], "tokens_used": 0})
    return {
        **base, "query_time_ms": 1,
        "retrieval_generation": {"version": "index-read/1.0.0", "mode": "generation_snapshot",
            "generation_id": GENERATION, "activation_event_id": EVENT, "manifest_sha256": SHA},
        "scientific_query": query.model_dump(mode="json"),
        "scientific_lookup": {"status": "completed", "reason_codes": [], "returned_count": 1,
            "has_more": False, "scope": "declared_generation_derived_extractions", "scientific_acceptance": False},
        "scientific_results": [{"result": result.model_dump(mode="json"), "binding": {
            "paper_id": "synthetic:wire-MgB2", "vector_id": f"ig62_{UUID(GENERATION).hex}_{'f' * 64}",
            "generation_id": GENERATION, "activation_event_id": EVENT, "manifest_sha256": SHA,
            "content_sha256": "1" * 64, "evidence_revision_id": EVIDENCE, "evidence_record_sha256": "2" * 64,
            "parent_result_revision_id": PARENT, "parent_result_sha256": "3" * 64,
            "association_scope": "derived_extraction_not_original_support",
        }}],
    }


def rejected(model, value):
    # Verify actual JSON wire decoding as well as Python-object construction.
    with pytest.raises(ValidationError):
        model.model_validate(value)
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(value))


def test_actual_selector_row_round_trips_without_scientific_or_training_authority(response_model):
    data = payload(response_model)
    value = response_model.model_validate_json(json.dumps(data))
    assert value.scientific_lookup.returned_count == 1
    row, = value.scientific_results
    assert row.result.tc.value == 39 and row.result.tc.unit == "K"
    assert row.result.pressure.pressure_state == "explicit_ambient"
    assert row.result.scientific_acceptance is False
    assert row.result.ml_training_eligible is False
    assert row.result.detection_adequacy_verified is False
    assert value.scientific_query.scientific_acceptance is False
    assert value.scientific_lookup.scientific_acceptance is False
    assert row.binding.association_scope == "derived_extraction_not_original_support"
    # Paper hits/citations need not be fabricated to publish qualified rows.
    assert (value.results if response_model is SearchResponse else value.sources) == []
    assert response_model.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("tc,relation,value,lower,upper,uncertainty", [
    (">20 K", "gt", None, 20, None, None),
    ("20-40 K", "interval", None, 20, 40, None),
    ("39 ± 1 K", "exact", 39, None, None, 1),
])
def test_actual_selector_preserves_quantity_relation_in_public_wire(response_model, tc, relation, value, lower, upper, uncertainty):
    # The interval case includes its lower endpoint, so use an unconstrained
    # resolved query when producing that row; the envelope only binds a report.
    data = payload(response_model)
    query = interpret_scientific_query("What is Tc of MgB₂?")
    result, = select_record_results([{"formula": "MgB2", "tc_kelvin": tc,
        "knowledge_origin": "Observed", "source_role": "primary", "measurement_method": "resistivity"}],
        query, scope_id="synthetic-wire-bound")
    data["scientific_query"] = query.model_dump(mode="json")
    data["scientific_results"][0]["result"] = result.model_dump(mode="json")
    actual = response_model.model_validate(data).scientific_results[0].result.tc
    assert (actual.relation, actual.value, actual.lower, actual.upper, actual.uncertainty) == (relation, value, lower, upper, uncertainty)


@pytest.mark.parametrize("count,rows", [(0, 1), (2, 1), (1, 0)])
def test_result_count_is_exact(response_model, count, rows):
    data = payload(response_model)
    data["scientific_lookup"]["returned_count"] = count
    data["scientific_results"] = data["scientific_results"][:rows]
    rejected(response_model, data)


@pytest.mark.parametrize("status", ["not_requested", "unavailable", "clarification_required"])
def test_noncompleted_lookup_cannot_publish_rows(response_model, status):
    data = payload(response_model)
    data["scientific_lookup"]["status"] = status
    rejected(response_model, data)


@pytest.mark.parametrize("pin", [None, {}, {"mode": "legacy_lexical_only"}])
def test_completed_lookup_requires_generation_even_when_empty(response_model, pin):
    data = payload(response_model)
    data["scientific_results"] = []
    data["scientific_lookup"]["returned_count"] = 0
    if pin is None:
        data.pop("retrieval_generation")
    else:
        data["retrieval_generation"] = pin
    rejected(response_model, data)


def test_empty_completed_lookup_is_valid_only_with_resolved_query_and_pin(response_model):
    data = payload(response_model)
    data["scientific_results"] = []
    data["scientific_lookup"]["returned_count"] = 0
    assert response_model.model_validate(data).scientific_lookup.status == "completed"
    data["scientific_lookup"]["has_more"] = True
    rejected(response_model, data)


@pytest.mark.parametrize("status", ["completed", "unavailable"])
@pytest.mark.parametrize("query", [None, "clarification"])
def test_executable_lookup_requires_resolved_interpretation(response_model, status, query):
    data = payload(response_model)
    data["scientific_lookup"].update(status=status, returned_count=0)
    data["scientific_results"] = []
    data["scientific_query"] = (None if query is None else
        interpret_scientific_query("Tc of 13C").model_dump(mode="json"))
    rejected(response_model, data)


def test_clarification_preserves_unresolved_clauses_without_rows_or_pin(response_model):
    data = payload(response_model)
    data.pop("retrieval_generation")
    data["scientific_query"] = interpret_scientific_query("Tc of 13C").model_dump(mode="json")
    assert data["scientific_query"]["status"] == "clarification_required"
    data["scientific_lookup"].update(status="clarification_required", returned_count=0)
    data["scientific_results"] = []
    assert response_model.model_validate(data).scientific_query.unresolved_clauses
    data["scientific_query"] = interpret_scientific_query("Tc > 20 K for MgB₂").model_dump(mode="json")
    rejected(response_model, data)


def test_unavailable_is_not_laundered_to_empty_completed_lookup(response_model):
    data = payload(response_model)
    data.pop("retrieval_generation")
    data["scientific_lookup"].update(status="unavailable", returned_count=0, reason_codes=["generation_unavailable"])
    data["scientific_results"] = []
    value = response_model.model_validate(data)
    assert value.scientific_lookup.status == "unavailable"
    assert value.retrieval_generation.mode == "legacy_lexical_only"
    data["scientific_lookup"]["has_more"] = True
    rejected(response_model, data)


def test_repeated_parent_is_not_two_independent_results(response_model):
    data = payload(response_model)
    second = copy.deepcopy(data["scientific_results"][0])
    second["binding"]["vector_id"] = f"ig62_{UUID(GENERATION).hex}_{'4' * 64}"
    second["result"]["record_index"] = 1
    second["result"]["result_id"] = "legacy-result:" + "5" * 64
    data["scientific_results"].append(second)
    data["scientific_lookup"]["returned_count"] = 2
    rejected(response_model, data)


@pytest.mark.parametrize("field,value", [
    ("generation_id", OTHER), ("activation_event_id", OTHER), ("manifest_sha256", "9" * 64),
    ("vector_id", f"ig62_{UUID(OTHER).hex}_{'f' * 64}"),
])
def test_bound_row_must_match_selected_generation_event_manifest_and_vector_namespace(response_model, field, value):
    data = payload(response_model)
    data["scientific_results"][0]["binding"][field] = value
    rejected(response_model, data)


@pytest.mark.parametrize("field", ["generation_id", "activation_event_id", "evidence_revision_id", "parent_result_revision_id"])
@pytest.mark.parametrize("value", ["not-a-uuid", GENERATION.upper(), UUID(GENERATION).hex, True, None])
def test_all_binding_uuids_are_canonical_strings(response_model, field, value):
    data = payload(response_model)
    data["scientific_results"][0]["binding"][field] = value
    rejected(response_model, data)


@pytest.mark.parametrize("field", ["manifest_sha256", "content_sha256", "evidence_record_sha256", "parent_result_sha256"])
@pytest.mark.parametrize("value", ["x" * 64, "A" * 64, "a" * 63, 1, None])
def test_all_binding_hashes_are_exact_lowercase_sha256_strings(response_model, field, value):
    data = payload(response_model)
    data["scientific_results"][0]["binding"][field] = value
    rejected(response_model, data)


@pytest.mark.parametrize("location,field", [
    ("lookup", "scientific_acceptance"), ("query", "scientific_acceptance"),
    ("result", "scientific_acceptance"), ("result", "ml_training_eligible"),
    ("result", "detection_adequacy_verified"),
])
@pytest.mark.parametrize("value", [True, 0, 0.0, "false", None])
def test_scientific_flags_require_literal_false_not_truthiness(response_model, location, field, value):
    data = payload(response_model)
    target = data["scientific_results"][0]["result"] if location == "result" else data["scientific_" + location]
    target[field] = value
    rejected(response_model, data)


@pytest.mark.parametrize("value", [True, "39", float("nan"), float("inf"), float("-inf")])
def test_quantities_reject_bool_string_and_nonfinite_values(response_model, value):
    data = payload(response_model)
    data["scientific_results"][0]["result"]["tc"]["value"] = value
    rejected(response_model, data)


@pytest.mark.parametrize("field,unit", [("tc", "K"), ("minimum_temperature", "K"), ("pressure", "GPa")])
def test_each_reported_quantity_keeps_its_declared_field_unit(response_model, field, unit):
    data = payload(response_model)
    data["scientific_results"][0]["result"][field]["unit"] = "GPa" if unit == "K" else "K"
    rejected(response_model, data)


@pytest.mark.parametrize("patch", [
    {"relation": "lt"}, {"relation": "lt", "value": None},
    {"relation": "exact", "lower": 1}, {"relation": "interval", "value": None, "lower": 40, "upper": 20},
    {"relation": "ge", "value": None, "lower": 20, "upper": 30},
    {"relation": "lt", "value": None, "upper": 100, "uncertainty": 1, "uncertainty_interpretation": "unspecified"},
    {"status": "unreported"}, {"uncertainty": -1, "uncertainty_interpretation": "unspecified"},
    {"uncertainty": 1}, {"uncertainty_interpretation": "unspecified"},
    {"unit": "GPa"}, {"unit": "C"}, {"approximate": 0},
])
def test_quantity_relations_units_and_uncertainty_cannot_be_reinterpreted(response_model, patch):
    data = payload(response_model)
    data["scientific_results"][0]["result"]["tc"].update(patch)
    rejected(response_model, data)


@pytest.mark.parametrize("patch", [
    {"returned_count": True}, {"returned_count": "1"}, {"returned_count": -1}, {"returned_count": 21},
    {"returned_count": float("nan")}, {"has_more": 1}, {"status": "succeeded"},
    {"reason_codes": ["same", "same"]}, {"reason_codes": ["raw quoted content"]},
    {"reason_codes": ["a" * 81]}, {"reason_codes": ["r" + str(i) for i in range(9)]},
    {"scope": "whole_corpus"}, {"approved": True},
])
def test_lookup_metadata_is_closed_bounded_and_strict(response_model, patch):
    data = payload(response_model)
    data["scientific_lookup"].update(patch)
    rejected(response_model, data)


@pytest.mark.parametrize("location", ["result", "binding", "linked"])
def test_nested_wire_records_cannot_add_an_authority_field(response_model, location):
    data = payload(response_model)
    target = data["scientific_results"][0]
    if location != "linked":
        target = target[location]
    target["scientifically_approved"] = True
    rejected(response_model, data)


def test_more_than_twenty_unique_linked_rows_are_rejected(response_model):
    data = payload(response_model)
    rows = []
    for i in range(21):
        row = copy.deepcopy(data["scientific_results"][0])
        row["binding"]["parent_result_revision_id"] = str(UUID(int=i + 1))
        rows.append(row)
    data["scientific_results"] = rows
    data["scientific_lookup"]["returned_count"] = 21
    rejected(response_model, data)


def test_public_binding_and_lookup_records_are_frozen_not_mutable_approvals():
    data = payload(SearchResponse)
    binding = ScientificResultBinding.model_validate(data["scientific_results"][0]["binding"])
    status = ScientificLookupStatus.model_validate(data["scientific_lookup"])
    with pytest.raises(ValidationError):
        binding.parent_result_revision_id = OTHER
    with pytest.raises(ValidationError):
        status.scientific_acceptance = True


def test_legacy_default_wire_is_explicitly_not_a_completed_lookup(response_model):
    value = response_model.model_validate({"total": 0, "results": [], "query_time_ms": 1}
        if response_model is SearchResponse else {"answer": "No source selected.", "sources": [], "tokens_used": 0, "query_time_ms": 1})
    assert value.scientific_query is None
    assert value.scientific_results == []
    assert value.scientific_lookup.status == "not_requested"
    assert value.scientific_lookup.returned_count == 0 and value.scientific_lookup.has_more is False
    assert value.retrieval_generation.mode == "legacy_lexical_only"
