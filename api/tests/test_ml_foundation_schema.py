"""Contract tests for the additive ML Foundation v1 database schema."""

from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from models.db import Base

PHASE1_TABLES = {
    "source_snapshots",
    "works",
    "paper_work_map",
    "material_claims",
    "claim_qc",
    "ml_dataset_snapshots",
    "ml_examples",
}


def _check_sql(table_name: str, constraint_name: str) -> str:
    table = Base.metadata.tables[table_name]
    constraint = next(
        item
        for item in table.constraints
        if isinstance(item, CheckConstraint) and item.name == constraint_name
    )
    return str(constraint.sqltext)


def _foreign_key(table_name: str, column_name: str) -> ForeignKeyConstraint:
    table = Base.metadata.tables[table_name]
    return next(
        item
        for item in table.constraints
        if isinstance(item, ForeignKeyConstraint)
        and [column.name for column in item.columns] == [column_name]
    )


def test_phase1_tables_and_composition_columns_are_additive() -> None:
    assert PHASE1_TABLES <= set(Base.metadata.tables)

    materials = Base.metadata.tables["materials"]
    for name in ("composition_status", "composition_data", "composition_enriched_at"):
        assert name in materials.c
        assert materials.c[name].nullable is True

    status_check = _check_sql("materials", "ck_materials_composition_status")
    assert all(
        value in status_check for value in ("exact", "variable", "interface", "mixture", "invalid")
    )


def test_work_mapping_is_one_paper_to_one_work() -> None:
    mapping = Base.metadata.tables["paper_work_map"]
    assert [column.name for column in mapping.primary_key.columns] == ["paper_id"]
    assert _foreign_key("paper_work_map", "paper_id").ondelete == "CASCADE"
    assert _foreign_key("paper_work_map", "work_id").ondelete == "CASCADE"

    match_check = _check_sql("paper_work_map", "ck_paper_work_map_match_method")
    assert "exact_doi" in match_check
    assert "related_paper" in match_check
    assert "singleton" in match_check


def test_material_claim_preserves_conditions_and_missing_semantics() -> None:
    claims = Base.metadata.tables["material_claims"]
    required = {
        "material_id",
        "paper_id",
        "work_id",
        "source_snapshot_id",
        "evidence_role",
        "result_status",
        "value_relation",
        "pressure_state",
        "pressure_gpa",
        "minimum_temperature_k",
        "source_record_hash",
        "semantic_fingerprint",
        "available_at",
        "extractor_version",
    }
    assert required <= set(claims.c.keys())
    assert claims.c.material_id.nullable is False
    assert claims.c.source_snapshot_id.nullable is False
    assert claims.c.source_record_hash.nullable is False
    assert claims.c.pressure_gpa.nullable is True

    pressure_check = _check_sql(
        "material_claims",
        "ck_material_claims_pressure_semantics",
    )
    assert "explicit_ambient" in pressure_check
    assert "pressure_gpa = 0" in pressure_check
    assert "not_reported" in pressure_check
    assert "pressure_gpa IS NULL" in pressure_check

    negative_check = _check_sql(
        "material_claims",
        "ck_material_claims_accepted_negative_tmin",
    )
    assert "not_detected" in negative_check
    assert "minimum_temperature_k IS NOT NULL" in negative_check

    relation_check = _check_sql("material_claims", "ck_material_claims_value_relation")
    assert all(value in relation_check for value in ("interval", "lt", "le", "gt", "ge"))

    value_bounds = _check_sql("material_claims", "ck_material_claims_value_bounds")
    pressure_bounds = _check_sql(
        "material_claims",
        "ck_material_claims_pressure_nonnegative",
    )
    assert "Infinity" in value_bounds
    assert "Infinity" in pressure_bounds

    json_check = _check_sql("material_claims", "ck_material_claims_json_objects")
    assert all(
        field in json_check for field in ("source_locator", "raw_record", "extraction_metadata")
    )

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in claims.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("material_id", "source_record_hash") in unique_columns
    assert _foreign_key("material_claims", "source_snapshot_id").ondelete == "RESTRICT"


def test_qc_and_ml_snapshots_enforce_review_and_leakage_keys() -> None:
    qc = Base.metadata.tables["claim_qc"]
    assert qc.c.claim_id.nullable is False
    assert _foreign_key("claim_qc", "claim_id").ondelete == "CASCADE"
    gold_check = _check_sql("claim_qc", "ck_claim_qc_gold_reviewed")
    assert "review_status = 'approved'" in gold_check
    assert "reviewed_at IS NOT NULL" in gold_check
    assert "reviewed_by IS NOT NULL" not in gold_check
    assert _foreign_key("claim_qc", "reviewed_by").ondelete == "SET NULL"

    datasets = Base.metadata.tables["ml_dataset_snapshots"]
    assert datasets.c.source_snapshot_id.nullable is False
    assert _foreign_key("ml_dataset_snapshots", "source_snapshot_id").ondelete == "RESTRICT"
    frozen_check = _check_sql(
        "ml_dataset_snapshots",
        "ck_ml_dataset_snapshots_frozen_manifest",
    )
    assert "manifest_sha256 IS NOT NULL" in frozen_check
    assert "frozen_at IS NOT NULL" in frozen_check

    examples = Base.metadata.tables["ml_examples"]
    for name in ("work_group", "material_group", "duplicate_group", "assignment_hash"):
        assert examples.c[name].nullable is False
    assert _foreign_key("ml_examples", "claim_id").ondelete == "RESTRICT"
    assert _foreign_key("ml_examples", "material_id").ondelete == "RESTRICT"


def test_alembic_revision_extends_0043_and_has_reversible_operations() -> None:
    migration_path = (
        Path(__file__).parents[1] / "alembic" / "versions" / "0044_ml_foundation_schema.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    module = ast.parse(source)
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"revision", "down_revision"}
    }
    assert assignments == {
        "revision": "0044_ml_foundation",
        "down_revision": "0043_chunks_fts",
    }

    for table_name in PHASE1_TABLES:
        assert f'op.create_table(\n        "{table_name}"' in source
        assert f'op.drop_table("{table_name}")' in source
    for column_name in ("composition_status", "composition_data", "composition_enriched_at"):
        assert f'op.drop_column("materials", "{column_name}")' in source
