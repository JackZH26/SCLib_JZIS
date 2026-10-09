"""Narrow ranking must select the same occurrence as full scientific evidence."""
from __future__ import annotations

from collections import UserDict
from copy import deepcopy

import pytest

from ingestion import anomaly_review as anomalies
from ingestion import property_evidence as evidence


def record(**changes):
    return {"paper_id": "test:one", "formula": "Nb", "tc_kelvin": 9.2,
            "pressure_gpa": 0, "pressure_condition": "ambient pressure",
            "knowledge_origin": "Observed", "measurement": "resistivity", "year": 2025,
            **changes}


CONTEXT = {"family": "elemental", "current_year": 2026}


def reference(records, field, legacy=None, context=None):
    binding = evidence.build_property_evidence(records, scope_id="mat:test", property_fields=[field],
        include_joint_epc=False, legacy_summary=legacy, anomaly_context=context or CONTEXT)["properties"][field]
    chosen = binding["selected"]
    return {"status": binding["status"], "has_evidence": bool(binding["total_evidence_count"]),
            "selected": {key: chosen[key] for key in ("result_id", "value")} if chosen else None}


@pytest.mark.parametrize("field", ["tc_max", "tc_ambient"])
@pytest.mark.parametrize("records", [
    [], [record()], [record(), record()],
    [record(paper_id="test:second"), record(paper_id="test:first")],
    [record(knowledge_origin="Computed", measurement="dft"), record(tc_kelvin=5)],
    [record(knowledge_origin="Unknown", measurement=None)], [record(knowledge_origin="Observed", evidence_type="theory")],
    [record(tc_kelvin=0)], [record(tc_kelvin=-2)], [record(tc_kelvin=9999)],
    [record(result_status="no_transition")], [record(pressure_gpa=10)],
    [record(pressure_gpa=None, pressure_condition=None)],
    [record(tc_kelvin="8–10 K")], [record(tc_kelvin="9.2 ± 0.1 K")],
    [record(tc_kelvin="<9.2 K")], [record(tc_kelvin=True)], [record(tc_kelvin=float("nan"))],
    [record(scientific_values={"tc_kelvin": {"raw_value": "9.2 K"}})],
    [record(lattice_params={"a": "bad"})], [record(lattice_a=-1)],
    [record(temperature_k=300, doping_level=0.1, lattice_a=3.2)],
])
@pytest.mark.parametrize("legacy", [None, {"tc_max": 9.2, "tc_ambient": 9.2, "tc_max_experimental": 9.2},
                                      {"tc_max": None, "tc_ambient": None},
                                      {"tc_max": 99, "tc_ambient": 99, "tc_max_theoretical": 99}])
def test_exact_status_identity_and_value_parity(field, records, legacy):
    original = deepcopy(records)
    expected = reference(records, field, legacy)
    actual = evidence.build_tc_selection(records, scope_id="mat:test", field=field,
                                         legacy_summary=legacy, anomaly_context=CONTEXT)
    assert actual == expected
    # NaN is deliberately a fallback case, not normalized into an exact value.
    assert repr(records) == repr(original)


def test_atomic_and_legacy_origin_policies_remain_the_authority():
    records = [record(tc_kelvin=10), record(tc_kelvin=20, knowledge_origin="Computed",
                                         measurement="dft", paper_id="test:calc")]
    legacy = {"tc_max": 20, "tc_max_experimental": 10, "tc_max_theoretical": 20}
    for policy in (None, evidence.ATOMIC_SELECTION_POLICY):
        context = {**CONTEXT, "selection_policy": policy}
        actual = evidence.build_tc_selection(records, scope_id="mat:test", field="tc_max",
                                             legacy_summary=legacy, anomaly_context=context)
        assert actual == reference(records, "tc_max", legacy, context)
        assert actual["selected"] is None  # Never replace an untraceable headline with a new maximum.
    unknown = [record(knowledge_origin="Unknown", measurement=None)]
    value = evidence.build_tc_selection(unknown, scope_id="mat:test", field="tc_max",
                                        legacy_summary={"tc_max": 9.2}, anomaly_context=CONTEXT)
    assert value["selected"]["value"] == 9.2  # Preserve legacy semantics; scoped origin rules differ.


def test_display_only_parse_is_removed_but_full_anomaly_assessment_remains(monkeypatch):
    structures, assessed = [], []
    original_structure, original_assess = evidence._structure, anomalies.assess_record_anomalies

    def structure(value):
        structures.append(1)
        return original_structure(value)

    def assess(*args, **kwargs):
        assessed.append(1)
        return original_assess(*args, **kwargs)

    monkeypatch.setattr(evidence, "_structure", structure)
    monkeypatch.setattr(anomalies, "assess_record_anomalies", assess)
    records = [record(lattice_a=3.2, temperature_k=300, doping_level=0.1)]
    expected = reference(records, "tc_max")
    assert len(structures) == 1 and len(assessed) == 1
    structures.clear()
    assessed.clear()
    assert evidence.build_tc_selection(records, scope_id="mat:test", field="tc_max", anomaly_context=CONTEXT) == expected
    assert structures == [] and len(assessed) == 1


@pytest.mark.parametrize("records,context", [
    ([UserDict(record())], CONTEXT), ([record(tc_kelvin="9.2 K")], CONTEXT),
    ([record(tc_kelvin_unit="K")], CONTEXT), ([record(source_locator={"page": 1})], CONTEXT),
    ([record(scientific_values={"tc_kelvin": {"raw_value": 9.2}})], CONTEXT),
    ([record(extra="x" * 4097)], CONTEXT), ([record(extra=[1, 2])], CONTEXT),
    ([record()], {**CONTEXT, "compound_thresholds": [{"field": "tc_max", "threshold": 5, "reference_id": "test:ref"}]}),
])
def test_uncertain_inputs_call_original_full_projector(monkeypatch, records, context):
    expected = reference(records, "tc_max", context=context)
    original, calls = evidence.build_property_evidence, []

    def full(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Uncertain input must not take narrow base path")

    monkeypatch.setattr(evidence, "build_property_evidence", full)
    monkeypatch.setattr(evidence, "_tc_selection_base", forbidden)
    assert evidence.build_tc_selection(records, scope_id="mat:test", field="tc_max", anomaly_context=context) == expected
    assert len(calls) == 1


def test_fallback_exceptions_are_not_swallowed_or_turned_into_missing_data(monkeypatch):
    def full(*args, **kwargs):
        raise ValueError("existing_full_projector_error")

    monkeypatch.setattr(evidence, "build_property_evidence", full)
    with pytest.raises(ValueError, match="existing_full_projector_error"):
        evidence.build_tc_selection([record(source_locator={"page": 1})], scope_id="mat:test", field="tc_max")


def test_context_and_raw_changes_are_evaluated_again():
    records = [record()]
    for year, family, value in [(2026, "elemental", 9.2), (2020, "elemental", 9.2), (2026, "kagome", 20)]:
        records[0]["tc_kelvin"] = value
        context = {"current_year": year, "family": family}
        assert evidence.build_tc_selection(records, scope_id="mat:test", field="tc_max", anomaly_context=context) == reference(records, "tc_max", context=context)
