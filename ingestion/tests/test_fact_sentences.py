"""Unit tests for ingestion.extract.fact_sentences.

Pure rendering — no network/DB. Verifies the NER-record → sentence
mapping, the noise filter, primary-before-cited ordering, the chunk cap,
and that build_authorized_chunks combines abstract + fact chunks (and
never the body).
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from ingestion.extract.fact_sentences import (
    _MAX_FACT_CHUNKS,
    build_authorized_chunks,
    build_fact_chunks,
    fact_sentence,
)
from ingestion.extract.material_ner import normalize_material_records
from ingestion.extract.scientific_values import parse_scientific_value
from ingestion.models import ApsArticleMeta


def _meta() -> ApsArticleMeta:
    return ApsArticleMeta(
        doi="10.1103/PhysRevB.104.014501",
        title="Test", authors=["A B"],
        abstract="We report superconductivity near 14 K.",
    )


def test_fact_sentence_full():
    s = fact_sentence({
        "formula": "MgB2", "tc_kelvin": 39, "method": "experimental",
        "measurement": "resistivity", "family": "iron-based",
        "pressure_condition": "ambient pressure",
    })
    assert s == ("For MgB2, the source lists a reported observation: Tc = 39 K "
                 "(reported method: experimental, resistivity) at ambient pressure. "
                 "[origin: Observed; origin status: resolved; source role: unknown; iron-based; "
                 "Tc unit follows the legacy field schema]")


def test_fact_sentence_trims_trailing_zero():
    s = fact_sentence({"formula": "FeSe", "tc_kelvin": 8.0})
    assert "Tc = 8 K" in s  # not "8.0 K"


def test_fact_sentence_pressure_gpa():
    s = fact_sentence({"formula": "H3S", "tc_kelvin": 203, "pressure_gpa": 155})
    assert "at 155 GPa" in s


def test_fact_sentence_no_tc_but_has_context():
    s = fact_sentence({"formula": "LaH10", "family": "hydride",
                       "crystal_structure": "Fm-3m"})
    assert s is not None
    assert "LaH10 is reported" in s
    assert "hydride" in s and "Fm-3m" in s


def test_fact_sentence_doping_type_and_level():
    s = fact_sentence({"formula": "LSCO", "tc_kelvin": 38,
                       "doping_type": "hole", "doping_level": 0.15})
    assert "doping: hole x=0.15" in s


def test_fact_sentence_regime_does_not_manufacture_pressure():
    # Regime alone (no Tc, no other context) is still noise.
    assert fact_sentence({"formula": "X", "tc_regime": "bulk_equilibrium"}) is None
    # A coarse regime is not same-result pressure evidence, even with Tc.
    s = fact_sentence({"formula": "H3S", "tc_kelvin": 203,
                       "tc_regime": "high_pressure"})
    assert "under high pressure" not in s


def test_fact_sentence_bare_formula_is_noise():
    # Just a formula, nothing else → skipped (abstract already mentions it).
    assert fact_sentence({"formula": "Cu"}) is None
    assert fact_sentence({"formula": ""}) is None
    assert fact_sentence({}) is None


def test_freeform_comments_and_evidence_quotes_are_not_republished_as_facts():
    s = fact_sentence({"formula": "YBCO", "tc_kelvin": 92, "comment": "PRIVATE SOURCE PROSE",
                       "evidence_text": "PRIVATE SOURCE PROSE", "source_quote": "PRIVATE SOURCE PROSE"})
    assert "PRIVATE SOURCE PROSE" not in s
    assert fact_sentence({"formula": "YBCO", "comment": "PRIVATE SOURCE PROSE"}) is None


@pytest.mark.parametrize("value,expected", [
    ("<100 K", "Tc < 100 K"), ("<=100 K", "Tc ≤ 100 K"),
    (">100 K", "Tc > 100 K"), (">=100 K", "Tc ≥ 100 K"),
    ("90-100 K", "Tc in [90, 100] K"), (["90 K", "100 K"], "Tc in [90, 100] K"),
    ("~100 K", "Tc = approximately 100 K"), ("100 ± 2 K", "Tc = 100 ± 2 K"),
    ("900 mK", "Tc = 0.9 K"),
])
def test_quantity_relation_survives_direct_and_real_normalization(value, expected):
    raw = {"formula": "FeSe", "tc_kelvin": value, "measurement": "resistivity", "source_role": "primary"}
    normalized = normalize_material_records([raw], paper_type="experimental")[0]
    for record in (raw, normalized):
        before = deepcopy(record)
        assert expected in fact_sentence(record)
        assert record == before


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), {"value": 100}, "invalid Tc"])
def test_invalid_tc_cannot_be_rendered_as_a_number(value):
    assert fact_sentence({"formula": "FeSe", "tc_kelvin": value}) is None


@pytest.mark.parametrize("origin,phrase", [
    ("Observed", "reported observation"), ("Computed", "computed result"),
    ("Inferred", "inferred result"), ("AI-Proposed", "AI-proposed hypothesis"),
    ("Unknown", "result of unresolved origin"),
])
@pytest.mark.parametrize("role", ["primary", "cited", "unknown"])
def test_origin_and_role_never_become_unconditional_material_properties(origin, phrase, role):
    sentence = fact_sentence({"formula": "H3S", "tc_kelvin": 100, "knowledge_origin": origin, "source_role": role})
    assert phrase in sentence and f"source role: {role}" in sentence
    assert "has a critical temperature" not in sentence
    assert "pressure not reported" in sentence
    if role == "cited":
        assert "cites a prior" in sentence


@pytest.mark.parametrize("marker", [
    {"result_status": "not_detected"}, {"outcome": "not_observed"},
    {"outcome_state": "no_transition"}, {"not_detected": True},
    {"is_superconducting": False}, {"transition_observed": False},
])
def test_non_detection_survives_normalization_and_never_reuses_tc_as_minimum_temperature(marker):
    raw = {"formula": "FeSe", "tc_kelvin": 100, "minimum_temperature_k": "1500 mK",
           "measurement_method": "resistivity", **marker}
    normalized = normalize_material_records([raw], paper_type="experimental")[0]
    for record in (raw, normalized, {"formula": "FeSe", "tc_kelvin": 100, "raw_extraction": raw}):
        sentence = fact_sentence(record)
        assert "superconductivity not detected" in sentence
        assert "minimum test temperature = 1.5 K" in sentence
        assert "Tc = 100" not in sentence and "no positive Tc is inferred" in sentence


@pytest.mark.parametrize("marker", [
    {"result_status": "unknown"}, {"result_status": "inconclusive"},
    {"result_status": {}}, {"is_superconducting": "false"},
    {"result_status": "invalid-output"}, {"validation_flags": ["result_status:explicit_text_required"]},
])
def test_unknown_or_malformed_outcomes_never_become_positive(marker):
    raw = {"formula": "FeSe", "tc_kelvin": 100, **marker}
    sentence = fact_sentence(raw)
    assert "outcome is unresolved" in sentence and "Tc = 100" not in sentence


def test_raw_negative_cannot_be_hidden_by_positive_top_level_or_conflicting_alias():
    raw = {"result_status": "not_detected"}
    for record in ({"raw_extraction": raw, "result_status": "observed"},
                   {"result_status": "observed", "outcome": "not_detected"}):
        sentence = fact_sentence({"formula": "FeSe", "tc_kelvin": 100, **record})
        assert "outcome is conflicted" in sentence and "Tc = 100" not in sentence


def test_raw_quantity_and_invalid_or_conflicting_typed_proposals_do_not_trust_compatibility_scalar():
    record = {"formula": "FeSe", "tc_kelvin": 100, "raw_extraction": {"tc_kelvin": "<100 K"}}
    assert "Tc < 100 K" in fact_sentence(record)
    record["scientific_values"] = {"tc_kelvin": parse_scientific_value("<100 K", "tc_kelvin")}
    assert "Tc < 100 K" in fact_sentence(record)
    record["scientific_values"]["tc_kelvin"]["raw_value"] = "99 K"
    assert fact_sentence(record) is None
    assert fact_sentence({"formula": "FeSe", "tc_kelvin": 100, "scientific_values": {"tc_kelvin": {"value": 100}}}) is None


def test_origin_and_role_conflicts_across_raw_and_derived_copies_remain_explicit():
    sentence = fact_sentence({"formula": "FeSe", "tc_kelvin": 10, "knowledge_origin": "Observed", "source_role": "primary",
                              "raw_extraction": {"knowledge_origin": "Computed", "source_role": "cited"}})
    assert "origin: Unknown" in sentence and "origin status: conflicted" in sentence
    assert "source role: conflicted" in sentence and "reported observation" not in sentence


def test_state_quantities_and_criterion_remain_bound_to_one_record():
    sentence = fact_sentence({"formula": "FeSe", "tc_kelvin": "8 ± 1 K", "pressure_gpa": "1-2 GPa",
        "magnetic_field_t": "<=100 mT", "sample_form": "thin_film", "substrate": "SrTiO3", "tc_criterion": "onset"})
    assert "at pressure in [1, 2] GPa" in sentence
    assert "magnetic field ≤ 0.1 T" in sentence
    assert "Tc criterion: onset" in sentence and "substrate: SrTiO3" in sentence and "thin_film" in sentence


def test_pressure_conflict_is_not_silently_resolved_and_legacy_raw_pressure_is_retained():
    record = {"formula": "FeSe", "tc_kelvin": 8, "raw_extraction": {"pressure_gpa": 3}}
    assert "at 3 GPa" in fact_sentence(record)
    record["pressure_condition"] = "ambient pressure"
    sentence = fact_sentence(record)
    assert "pressure unresolved" in sentence and "at ambient pressure" not in sentence


@pytest.mark.parametrize("value", [True, False, float("inf"), float("nan")])
def test_doping_and_detection_minimum_reject_boolean_and_nonfinite_values(value):
    sentence = fact_sentence({"formula": "FeSe", "tc_kelvin": 8, "doping_level": value})
    assert "doping:" not in sentence
    negative = fact_sentence({"formula": "FeSe", "result_status": "not_detected", "minimum_temperature_k": value})
    assert "minimum test temperature not reported" in negative


def test_build_fact_chunks_ids_and_metadata():
    mats = [
        {"formula": "MgB2", "tc_kelvin": 39},
        {"formula": "FeSe", "tc_kelvin": 8},
    ]
    chunks = build_fact_chunks(_meta(), mats, start_index=1)
    assert [c.chunk_index for c in chunks] == [1, 2]
    assert chunks[0].id == "aps:10.1103/PhysRevB.104.014501_fact_001"
    assert chunks[0].section == "Facts"
    assert chunks[0].materials_mentioned == [mats[0]]
    assert "Section: Facts" in chunks[0].text


def test_build_fact_chunks_primary_before_cited():
    mats = [
        {"formula": "CITED", "tc_kelvin": 1, "evidence_type": "cited"},
        {"formula": "PRIMARY", "tc_kelvin": 2, "evidence_type": "primary"},
    ]
    chunks = build_fact_chunks(_meta(), mats, start_index=0)
    assert "PRIMARY" in chunks[0].text
    assert "CITED" in chunks[1].text


def test_build_fact_chunks_respects_cap():
    mats = [{"formula": f"M{i}", "tc_kelvin": i} for i in range(_MAX_FACT_CHUNKS + 10)]
    chunks = build_fact_chunks(_meta(), mats, start_index=0)
    assert len(chunks) == _MAX_FACT_CHUNKS


def test_build_authorized_chunks_combines_abstract_and_facts():
    mats = [{"formula": "MgB2", "tc_kelvin": 39}]
    chunks = build_authorized_chunks(_meta(), mats)
    sections = [c.section for c in chunks]
    assert "Abstract" in sections
    assert "Facts" in sections
    # ids are unique.
    assert len({c.id for c in chunks}) == len(chunks)
    blob = " ".join(c.text for c in chunks)
    assert "14 K" in blob          # abstract
    assert "Tc = 39 K" in blob     # fact sentence
def test_malformed_origin_flag_cannot_be_lost_when_raw_record_is_absent():
    sentence = fact_sentence({"formula": "Nb", "tc_kelvin": "9 K", "evidence_role": "primary_experimental",
                              "validation_flags": ["result_origin:explicit_text_required"]})
    assert "origin: Unknown" in sentence and "origin status: conflicted" in sentence
    assert "reported observation" not in sentence
