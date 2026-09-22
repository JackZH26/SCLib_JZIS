"""SC10 synthetic writer regressions; no model, network or production data."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from ingestion.extract.material_ner import normalize_material_records
from ingestion.extract.materials_aggregator import (
    _derive_summary,
    _material_upsert_statement,
    _RefutedEntry,
)
from ingestion.index.indexer import materials_table
from ingestion.property_evidence import build_property_evidence


def _record(**changes):
    return {"formula": "YBa2Cu3O7", "paper_id": "synthetic:sc10-1",
            "tc_kelvin": 90, "year": 2026, "measurement": "resistivity",
            "pressure_gpa": 0, "pressure_state": "explicit_ambient",
            "evidence_type": "primary_experimental", "confidence": 0.95, **changes}


@pytest.mark.parametrize("formula", ("YBa2Cu3O7", "Hg", "MgB2"))
def test_silent_records_do_not_create_false_flags_or_family_observations(formula):
    summary = _derive_summary(formula, [_record(formula=formula)])
    assert summary["has_competing_order"] is None
    assert summary["is_unconventional"] is None
    assert summary["pairing_symmetry"] is None
    assert summary["material_semantics"]["properties"]["has_competing_order"]["status"] != "reported"


@pytest.mark.parametrize("field", ("has_competing_order", "is_unconventional"))
def test_unqualified_raw_false_is_preserved_but_not_a_summary_absence(field):
    record = _record(**{field: False})
    before = deepcopy(record)
    summary = _derive_summary(record["formula"], [record])
    assert summary[field] is None
    assert record == before and summary["records"] == [before]


@pytest.mark.parametrize("field", ("has_competing_order", "is_unconventional"))
def test_explicit_negative_with_same_source_method_and_detection_conditions_is_retained(field):
    row = _record(**{field: False, "measurement_method": "x-ray diffraction",
                    "detection_conditions": {"temperature_min_k": 2, "temperature_max_k": 300}})
    summary = _derive_summary(row["formula"], [row])
    assert summary[field] is False
    assert summary["material_semantics"]["properties"][field]["status"] == "reported"
    assert summary["records"] == [row]


def test_order_temperature_does_not_establish_competing_order():
    summary = _derive_summary("YBa2Cu3O7", [_record(t_cdw_k=100)])
    assert summary["t_cdw_k"] == 100
    assert summary["has_competing_order"] is None


def test_explicit_order_label_is_a_reported_indicator_not_a_family_prior():
    summary = _derive_summary("YBa2Cu3O7", [_record(competing_order="CDW")])
    assert summary["has_competing_order"] is True
    assert summary["material_semantics"]["properties"]["has_competing_order"]["status"] == "reported"


def test_explicit_pairing_is_not_overwritten_by_cuprate_prior():
    summary = _derive_summary("YBa2Cu3O7", [_record(pairing_symmetry="p-wave")])
    assert summary["pairing_symmetry"] == "p-wave"


def test_conflicting_reported_pairings_are_not_resolved_by_confidence_voting():
    summary = _derive_summary("YBa2Cu3O7", [
        _record(pairing_symmetry="d-wave"),
        _record(paper_id="synthetic:sc10-2", pairing_symmetry="s-wave", confidence=0.2),
    ])
    assert summary["pairing_symmetry"] is None


def test_final_classification_hints_cannot_resurrect_conflicting_atomic_selections():
    records = [_record(pairing_symmetry="d-wave", is_unconventional=False),
               _record(paper_id="synthetic:sc10-2", pairing_symmetry="s-wave", confidence=0.2)]
    summary = _derive_summary("YBa2Cu3O7", records)
    evidence = build_property_evidence(
        summary["records"], scope_id="mat:synthetic", legacy_summary=summary,
        property_fields=("pairing_symmetry", "is_unconventional"), include_joint_epc=False,
    )
    assert "property_evidence" not in summary  # Atomic envelopes are read-time projections.
    for field in ("pairing_symmetry", "is_unconventional"):
        assert summary[field] is None
        assert evidence["properties"][field]["selected"] is None
        assert evidence["properties"][field]["evidence"]  # Alternatives remain recoverable.


def test_enum_derived_classification_does_not_fabricate_an_atomic_boolean():
    summary = _derive_summary("YBa2Cu3O7", [_record(competing_order="CDW")])
    evidence = build_property_evidence(
        summary["records"], scope_id="mat:synthetic", legacy_summary=summary,
        property_fields=("has_competing_order",), include_joint_epc=False,
    )
    assert summary["has_competing_order"] is True
    assert evidence["properties"]["has_competing_order"]["selected"] is None
    assert evidence["properties"]["has_competing_order"]["evidence"] == []


def test_current_source_hold_prevents_reported_property_projection():
    summary = _derive_summary("YBa2Cu3O7", [_record(pairing_symmetry="d-wave", competing_order="CDW")],
                              source_statuses={"synthetic:sc10-1": "retracted"})
    assert summary["pairing_symmetry"] is None
    assert summary["has_competing_order"] is None


def test_tc_spread_across_samples_does_not_create_disputed_flag():
    summary = _derive_summary("YBa2Cu3O7", [
        _record(sample_id="A", tc_kelvin=90),
        _record(paper_id="synthetic:sc10-2", sample_id="B", tc_kelvin=40),
    ])
    assert summary["disputed"] is False


def test_explicit_dispute_cannot_be_voted_away_by_other_records():
    summary = _derive_summary("YBa2Cu3O7", [
        _record(disputed=True, confidence=0.2),
        _record(paper_id="synthetic:sc10-2", disputed=False),
        _record(paper_id="synthetic:sc10-3", disputed=False),
    ])
    assert summary["disputed"] is True


def test_existing_dispute_hold_and_curated_refutation_remain_sticky():
    assert _derive_summary("YBa2Cu3O7", [_record()], legacy_summary={"disputed": True})["disputed"] is True
    assert _derive_summary("YBa2Cu3O7", [_record()], refuted=_RefutedEntry("YBa2Cu3O7", "synthetic", 90, None))["disputed"] is True
    statement = _material_upsert_statement("mat:synthetic", _derive_summary("YBa2Cu3O7", [_record()]))
    sql = str(statement)
    assert "disputed = CASE WHEN (materials.disputed IS true)" in sql
    assert "materials.admin_decision IS NOT NULL" in sql


def test_driver_carries_current_source_status_and_old_dispute_into_derived_metadata(monkeypatch):
    from ingestion.extract import materials_aggregator as aggregator

    raw = _record(competing_order="CDW")
    before = deepcopy(raw)

    class Result:
        def __init__(self, rows): self.rows = rows
        def first(self): return self.rows[0] if self.rows else None
        def all(self): return self.rows

    class Database:
        def __init__(self): self.inserts = []
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def commit(self): pass
        async def execute(self, statement):
            if statement.is_insert:
                self.inserts.append(statement.compile().params)
                return Result([])
            sql = str(statement)
            if "FROM pipeline_state" in sql:
                return Result([(str(aggregator.NORMALIZE_SCHEMA_VERSION),)])
            if "FROM papers" in sql:
                return Result([("arxiv:sc10-driver", "arxiv", None, None, [raw], "T1", "published")])
            if "materials.has_competing_order" in sql:
                return Result([(aggregator._material_id(aggregator.normalize_formula(raw["formula"])),
                                "d-wave", True, False, True)])
            return Result([])

    database = Database()
    monkeypatch.setattr(aggregator, "_session_factory", lambda: lambda: database)
    assert asyncio.run(aggregator.aggregate_from_papers()) == 1
    stored = database.inserts[0]
    assert stored["disputed"] is True
    assert stored["pairing_symmetry"] is None
    assert stored["is_unconventional"] is None
    assert stored["has_competing_order"] is True
    assert stored["material_semantics"]["conflicts"]["scientific_dispute"]["status"] == "reported_unadjudicated"
    assert raw == before


def test_writer_schema_has_unknown_default_and_separate_rebuildable_metadata():
    assert materials_table.c.has_competing_order.nullable is True
    assert materials_table.c.has_competing_order.server_default is None
    assert materials_table.c.material_semantics.nullable is False


def test_ner_preserves_optional_negative_evidence_without_manufacturing_status():
    raw = {"formula": "YBa2Cu3O7", "has_competing_order": False,
           "measurement_method": "x-ray diffraction",
           "detection_conditions": {"temperature_min_k": 2, "temperature_max_k": 300},
           "has_competing_order_status": "accepted"}
    before = deepcopy(raw)
    record = normalize_material_records([raw], paper_type="experimental", paper_id="synthetic:sc10")[0]
    assert record["has_competing_order"] is False
    assert record["measurement_method"] == raw["measurement_method"]
    assert record["detection_conditions"] == raw["detection_conditions"]
    assert "has_competing_order_status" not in record
    assert record["raw_extraction"] == before and raw == before


@pytest.mark.parametrize("value", (0, 1, "false", "true", [], {}))
def test_ner_new_scientific_boolean_requires_explicit_json_boolean(value):
    record = normalize_material_records([{"formula": "MgB2", "has_competing_order": value}],
                                        paper_type="experimental", paper_id="synthetic:sc10")[0]
    assert "has_competing_order" not in record
    assert "has_competing_order:explicit_boolean_required" in record["validation_flags"]


def test_ner_silence_does_not_add_false_or_negative_evidence():
    record = normalize_material_records([{"formula": "MgB2"}], paper_type="experimental", paper_id="synthetic:sc10")[0]
    assert not {"has_competing_order", "measurement_method", "detection_conditions"} & record.keys()
