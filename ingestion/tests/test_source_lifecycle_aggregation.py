"""SC08 synthetic source-lifecycle propagation; no database or network."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from ingestion.extract import materials_aggregator as aggregator


def record(paper_id="synthetic:held", **changes):
    return {"formula": "YBa2Cu3O7", "paper_id": paper_id,
            "tc_kelvin": 90.0, "pressure_gpa": 0.0,
            "pressure_state": "explicit_ambient", "measurement": "resistivity",
            "evidence_type": "primary_experimental", "confidence": 0.95,
            "year": 2024, **changes}


@pytest.mark.parametrize("status", ("retracted", "withdrawn", "corrected", "disputed", " RETRACTED "))
def test_only_held_source_retains_archive_records_but_cannot_supply_derived_values(status):
    rows = [record(hc2_tesla=20, t_cdw_k=100, lambda_eph=1.5,
                   pairing_symmetry="d-wave", competing_order="CDW", gap_structure="nodal")]
    before = deepcopy(rows)
    result = aggregator._derive_summary("YBa2Cu3O7", rows,
        source_statuses={"synthetic:held": status}, current_year=2026)
    for key in ("tc_max", "tc_ambient", "tc_max_conditions", "tc_max_experimental",
                "tc_max_theoretical", "ambient_sc", "hc2_tesla", "t_cdw_k",
                "lambda_eph", "arxiv_year", "pairing_symmetry", "has_competing_order",
                "gap_structure", "competing_order", "dominant_evidence"):
        assert result[key] is None, key
    assert result["total_papers"] == 0
    assert result["needs_review"] is True
    assert result["review_reason"].startswith("source_support_unavailable:")
    assert result["disputed"] is False  # Source status is not a material adjudication.
    assert "retracted" not in result
    assert result["records"] == rows == before


@pytest.mark.parametrize("status", ("retracted", "corrected", "disputed"))
def test_mixed_source_recomputes_selected_value_conditions_and_support(status):
    held = record(tc_kelvin=130, pressure_gpa=2, pressure_state="reported", t_cdw_k=100)
    independent = record("synthetic:independent", tc_kelvin=80, t_cdw_k=70,
                         year=2025, pairing_symmetry="d-wave")
    result = aggregator._derive_summary("YBa2Cu3O7", [held, independent],
        source_statuses={held["paper_id"]: status, independent["paper_id"]: "published"},
        current_year=2026)
    assert result["tc_max"] == result["tc_ambient"] == 80
    assert result["t_cdw_k"] == 70
    assert result["total_papers"] == 1 and result["arxiv_year"] == 2025
    assert "synthetic:independent" in result["tc_max_conditions"]
    assert "synthetic:held" not in result["tc_max_conditions"]
    assert result["needs_review"] is False and result["disputed"] is False
    assert result["records"] == [held, independent]


@pytest.mark.parametrize("rows,statuses", (
    ([], {}), (None, {}), ([{}], {}), ([record()], {}),
    ([record()], {"synthetic:held": "published"}),
    ([record()], {"synthetic:held": None}),
    ([record(), record("missing")], {"synthetic:held": "retracted"}),
    ([record(), None], {"synthetic:held": "retracted"}),
))
def test_only_source_invalidation_requires_positive_hold_for_every_explicit_record(rows, statuses):
    assert aggregator._only_held_source_support(rows, statuses) is False


def test_upsert_preserves_history_but_new_hold_precedes_legacy_positive_override():
    summary = aggregator._derive_summary("YBa2Cu3O7", [record()],
        source_statuses={"synthetic:held": "retracted"}, current_year=2026)
    statement = aggregator._material_upsert_statement("mat:original-stable-id", summary)
    sql = str(statement)
    assert "needs_review = CASE WHEN (materials.needs_review IS true OR" in sql
    assert "WHEN (excluded.needs_review IS true)" in sql
    assert "WHEN (materials.admin_decision IS NOT NULL) THEN materials.needs_review" in sql
    assert "updated_at = now()" in sql
    assert "WHERE materials.formula IS DISTINCT FROM excluded.formula" in sql
    assert "admin_decision =" not in sql and "retracted =" not in sql


def test_upsert_existing_hold_precedes_all_other_review_decisions_without_admin_requirement():
    summary = aggregator._derive_summary("YBa2Cu3O7", [record()], current_year=2026)
    assert summary["needs_review"] is False
    sql = str(aggregator._material_upsert_statement("mat:held", summary))
    assert "review_reason = CASE WHEN (materials.needs_review IS true OR" in sql
    assert "lower(ltrim(materials.review_reason)) LIKE" in sql
    assert sql.index("materials.needs_review IS true") < sql.index("materials.admin_decision IS NOT NULL")


def test_orphan_upsert_preserves_formula_family_and_structural_relationships():
    summary = aggregator._derive_summary("YBa2Cu3O7", [record()],
        source_statuses={"synthetic:held": "retracted"}, current_year=2026)
    sql = str(aggregator._material_upsert_statement("mat:original-stable-id", summary,
                                                   preserve_identity=True))
    updates = sql.split("DO UPDATE SET", 1)[1].split(" WHERE ", 1)[0]
    for field in ("formula", "formula_normalized", "family", "formula_substrate", "formula_overlayer",
                  "parent_material_id", "variant_count", "mp_id", "retracted", "admin_decision"):
        assert f"{field} =" not in updates
    assert "tc_max = excluded.tc_max" in updates


class Result:
    def __init__(self, rows): self.rows = rows
    def first(self): return self.rows[0] if self.rows else None
    def all(self): return self.rows


class Database:
    def __init__(self, papers, materials):
        self.papers, self.materials, self.inserts = papers, materials, []
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
            return Result(self.papers)
        if "materials.has_competing_order" in sql:
            return Result([(row[0], None, None, None, False, row[3]) for row in self.materials])
        if "materials.admin_decision" in sql and "FROM materials" in sql:
            return Result(self.materials)
        return Result([])


@pytest.mark.parametrize("status", ("retracted", "withdrawn", "corrected", "disputed"))
def test_driver_rebuilds_held_only_orphan_even_after_historical_manual_approval(monkeypatch, status):
    raw = record()
    old_id = "mat:preserved-historical-id"
    db = Database(
        [(raw["paper_id"], "arxiv", None, None, [raw], "T1", status)],
        [(old_id, raw["formula"], None, [raw], False, {"approved": True})],
    )
    monkeypatch.setattr(aggregator, "_session_factory", lambda: lambda: db)
    # This reports current-source aggregates, not newly added archive rows.
    assert asyncio.run(aggregator.aggregate_from_papers()) == 0
    stored = db.inserts[0]
    assert stored["id"] == old_id and stored["records"] == [raw]
    assert stored["tc_max"] is None and stored["total_papers"] == 0
    assert stored["needs_review"] is True
    assert "admin_decision" not in stored and "retracted" not in stored
    first = deepcopy(stored)
    asyncio.run(aggregator.aggregate_from_papers())
    assert db.inserts[-1] == first  # deterministic derivation on repeat delivery


def test_driver_preserves_unrelated_existing_provenance_hold(monkeypatch):
    raw = record()
    db = Database(
        [(raw["paper_id"], "arxiv", None, None, [raw], "T1", "retracted")],
        [("mat:held", raw["formula"], "provenance_quarantine: restricted", [raw], True, None)],
    )
    monkeypatch.setattr(aggregator, "_session_factory", lambda: lambda: db)
    asyncio.run(aggregator.aggregate_from_papers())
    assert db.inserts[0]["review_reason"] == "provenance_quarantine: restricted"


def test_driver_keeps_independent_fresh_support_and_does_not_restore_held_extractions(monkeypatch):
    held = record(tc_kelvin=130)
    independent = record("synthetic:independent", tc_kelvin=80)
    db = Database(
        [(held["paper_id"], "arxiv", None, None, [held], "T1", "retracted"),
         (independent["paper_id"], "arxiv", None, None, [independent], "T1", "published")],
        [],
    )
    monkeypatch.setattr(aggregator, "_session_factory", lambda: lambda: db)
    assert asyncio.run(aggregator.aggregate_from_papers()) == 1
    stored = db.inserts[0]
    assert stored["tc_max"] == 80 and stored["total_papers"] == 1
    assert [item["paper_id"] for item in stored["records"]] == [independent["paper_id"]]
    assert stored["needs_review"] is False


def test_driver_preserves_existing_mixed_source_archive_records_without_counting_their_support(monkeypatch):
    held = record(tc_kelvin=130)
    independent = record("synthetic:independent", tc_kelvin=80)
    mat_id = aggregator._material_id(aggregator.normalize_formula(held["formula"]))
    db = Database(
        [(held["paper_id"], "arxiv", None, None, [held, record(tc_kelvin=140)], "T1", "retracted"),
         (independent["paper_id"], "arxiv", None, None, [independent], "T1", "published")],
        [(mat_id, held["formula"], None, [held, independent], False, None)],
    )
    monkeypatch.setattr(aggregator, "_session_factory", lambda: lambda: db)
    assert asyncio.run(aggregator.aggregate_from_papers()) == 1
    stored = db.inserts[0]
    assert stored["tc_max"] == 80 and stored["total_papers"] == 1
    assert held in stored["records"]
    assert [item["tc_kelvin"] for item in stored["records"]] == [80, 130]
    # The newly present 140 K held extraction was never retained, so this run
    # does not synthesize a new historical audit record from it.
    assert len(stored["records"]) == 2


@pytest.mark.parametrize("mat_id,records,papers", (
    ("nims:independent", [record()], [("synthetic:held", "arxiv", None, None, [], "T1", "retracted")]),
    ("mat:temporarily-empty", [record()], [("synthetic:held", "arxiv", None, None, [], "T1", "published")]),
    ("mat:unknown-source", [record()], []),
    ("mat:no-records", [], []),
))
def test_driver_preserves_nims_and_temporary_source_absence(monkeypatch, mat_id, records, papers):
    db = Database(papers, [(mat_id, "YBa2Cu3O7", None, records, False, None)])
    monkeypatch.setattr(aggregator, "_session_factory", lambda: lambda: db)
    assert asyncio.run(aggregator.aggregate_from_papers()) == 0
    assert db.inserts == []
