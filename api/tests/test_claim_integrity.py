"""Real PostgreSQL admission checks, only through the disposable API runner."""
from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

from models.claim_integrity import (
    NEW_CHECKS,
    TARGET_FOREIGN_KEY,
    TARGET_UNIQUE,
    audit_incompatible_rows,
)
from models.db import Base, get_session_factory
from services.claim_outcomes import negative_outcome_issues, outcome_conflicts_with_positive

TABLES = Base.metadata.tables
VALUES = {
    "exact": {"value_kelvin": 12.0},
    "interval": {"value_lower_kelvin": 10.0, "value_upper_kelvin": 20.0},
    "lt": {"value_upper_kelvin": 2.0}, "le": {"value_upper_kelvin": 2.0},
    "gt": {"value_lower_kelvin": 10.0}, "ge": {"value_lower_kelvin": 10.0},
    "unreported": {},
}


@pytest_asyncio.fixture(loop_scope="function")
async def db():
    async with get_session_factory()() as session:
        yield session


async def add(db, table, **values):
    target = TABLES[table]
    return (await db.execute(target.insert().values(**values).returning(target.c.id))).scalar_one()


async def seed(db):
    material = await add(db, "materials", id="ci47-" + uuid.uuid4().hex,
                         formula="MgB2", formula_normalized="MgB2")
    source = await add(db, "source_snapshots", dataset_version="synthetic-ci47",
                       schema_version="ci47-test")
    return material, source


def claim_values(material, source, **changes):
    return {"material_id": material, "source_snapshot_id": source,
            "source_record_hash": uuid.uuid4().hex * 2, "extractor_version": "synthetic-test",
            "raw_record": {"fixture": "SYNTHETIC_NOT_FOR_LOG"}, **changes}


async def example_values(db, material, source, claim):
    snapshot = await add(db, "ml_dataset_snapshots", source_snapshot_id=source,
                         name=uuid.uuid4().hex, version="1", label_policy_version="test",
                         feature_schema_version="test", split_ruleset_version="test")
    return {"dataset_snapshot_id": snapshot, "example_key": uuid.uuid4().hex,
            "claim_id": claim, "material_id": material, "split": "train",
            "task_type": "tc_regression", "work_group": "synthetic-work",
            "material_group": material, "duplicate_group": "synthetic-group",
            "assignment_hash": "a" * 64}


@pytest.mark.parametrize("state,value,accepted", [
    ("explicit_ambient", None, False), ("explicit_ambient", 0, True),
    ("explicit_ambient", 1, False), ("reported", None, False),
    ("reported", 10, True), ("not_reported", None, True),
    ("not_reported", 0, False), ("ambiguous", None, True),
])
async def test_claim_pressure_null_is_not_a_check_bypass(db, state, value, accepted):
    material, source = await seed(db)
    values = claim_values(material, source, pressure_state=state, pressure_gpa=value)
    if accepted:
        await add(db, "material_claims", **values)
    else:
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await add(db, "material_claims", **values)


@pytest.mark.parametrize("relation", tuple(VALUES))
@pytest.mark.parametrize("status", ["observed", "not_detected", "inconclusive", "unknown"])
@pytest.mark.parametrize("validity", ["accepted", "pending"])
@pytest.mark.parametrize("property_type", ["tc", "non_transition"])
async def test_complete_result_status_relation_admission_matrix(
    db, relation, status, validity, property_type,
):
    material, source = await seed(db)
    values = claim_values(
        material, source, value_relation=relation, result_status=status,
        property_type=property_type,
        validity_status=validity, minimum_temperature_k=2.0, measurement_method="resistivity",
        **VALUES[relation],
    )
    permitted = validity == "pending"
    permitted |= property_type == "tc" and status in {"unknown", "inconclusive"}
    permitted |= property_type == "tc" and status == "observed" and relation != "unreported"
    permitted |= (property_type == "non_transition" and status == "not_detected"
                  and relation in {"unreported", "lt", "le"})
    if permitted:
        await add(db, "material_claims", **values)
    else:
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await add(db, "material_claims", **values)


@pytest.mark.parametrize("changes", [
    {"minimum_temperature_k": None}, {"measurement_method": None},
    {"measurement_method": ""}, {"measurement_method": "  unknown "},
    {"measurement_method": "not_reported"}, {"measurement_method": " \n\t "},
    {"measurement_method": "\nunknown\t"}, {"property_type": "tc"},
    {"evidence_role": "primary_theoretical", "measurement_method": "DFT"},
    *[{"extraction_metadata": {"result_classification": {"knowledge_origin": origin}}}
      for origin in ("Computed", "Inferred", "AI-Proposed")],
])
async def test_accepted_negative_needs_a_coherent_type_window_and_method(db, changes):
    material, source = await seed(db)
    values = claim_values(material, source, property_type="non_transition",
                          result_status="not_detected", validity_status="accepted",
                          minimum_temperature_k=2.0, measurement_method="resistivity")
    values.update(changes)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await add(db, "material_claims", **values)


@pytest.mark.parametrize("field", ["value_kelvin", "value_lower_kelvin", "value_upper_kelvin",
                                    "pressure_gpa", "minimum_temperature_k", "magnetic_field_t",
                                    "extraction_confidence", "relation_confidence"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
async def test_all_v1_numeric_columns_reject_nonfinite_values_in_postgres(db, field, value):
    material, source = await seed(db)
    relation = {"value_kelvin": "exact", "value_lower_kelvin": "ge",
                "value_upper_kelvin": "le"}.get(field, "unreported")
    values = claim_values(material, source, value_relation=relation, **{field: value})
    if field == "pressure_gpa":
        values["pressure_state"] = "reported"
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await add(db, "material_claims", **values)


@pytest.mark.parametrize("values", [
    {"value_relation": "exact", "value_kelvin": None},
    {"value_relation": "exact", "value_kelvin": 1.0, "value_upper_kelvin": 2.0},
    {"value_relation": "interval", "value_lower_kelvin": 1.0},
    {"value_relation": "interval", "value_lower_kelvin": 2.0, "value_upper_kelvin": 1.0},
    {"value_relation": "lt", "value_lower_kelvin": 1.0, "value_upper_kelvin": 2.0},
    {"value_relation": "gt", "value_lower_kelvin": 1.0, "value_kelvin": 2.0},
    {"value_relation": "unreported", "value_kelvin": 0.0},
])
async def test_v1_value_shapes_are_enforced_by_database(db, values):
    material, source = await seed(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await add(db, "material_claims", **claim_values(material, source, **values))


async def test_cross_material_target_insert_update_and_parent_reassignment_are_rejected(db):
    material, source = await seed(db)
    other_material, _ = await seed(db)
    claim = await add(db, "material_claims", **claim_values(material, source))
    values = await example_values(db, material, source, claim)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await add(db, "ml_examples", **{**values, "material_id": other_material})
    example = await add(db, "ml_examples", **values)
    for table, identifier, update in (
        ("ml_examples", example, {"material_id": other_material}),
        ("ml_examples", example, {"claim_id": None}),
        ("material_claims", claim, {"material_id": other_material}),
    ):
        target = TABLES[table]
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(target.update().where(target.c.id == identifier).values(**update))


async def seed_event(db):
    material, _ = await seed(db)
    artifact = await add(db, "evidence_artifacts", kind="literature_locator", schema_version="1",
                         source="synthetic-ci47", record_sha256="a" * 64,
                         hash_status="not_applicable", access="metadata_only")
    state = await add(db, "material_states", material_id=material, resolution="source_scoped",
                      condition_schema_version="1", pressure_status="not_reported",
                      temperature_role="unknown", context_sha256="b" * 64,
                      source_artifact_id=artifact)
    event = await add(db, "research_events", material_id=material, state_id=state,
                      event_type="measurement", knowledge_origin="Observed", record_sha256="c" * 64)
    return state, event


@pytest.mark.parametrize("field,relation", [("value", "exact"), ("lower", "ge"), ("upper", "le")])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
async def test_v2_all_bound_columns_keep_finite_guards(db, field, relation, number):
    _, event = await seed_event(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await add(db, "event_properties", event_id=event, property_key="formation_energy_per_atom",
                      unit="eV/atom", relation=relation, record_sha256="d" * 64, **{field: number})


@pytest.mark.parametrize("values", [
    {"relation": "exact", "value": None},
    {"relation": "exact", "value": 1.0, "upper": 2.0},
    {"relation": "interval", "lower": 1.0},
    {"relation": "interval", "lower": 2.0, "upper": 1.0},
    {"relation": "lt", "lower": 1.0, "upper": 2.0},
    {"relation": "ge", "value": 1.0, "lower": 2.0},
    {"relation": "unreported", "value": 0.0},
])
async def test_v2_shapes_do_not_gain_null_bypasses(db, values):
    _, event = await seed_event(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await add(db, "event_properties", event_id=event, property_key="band_gap", unit="eV",
                      record_sha256="d" * 64, **values)


@pytest.mark.parametrize("changes", [
    {"pressure_status": "explicit_ambient", "pressure_gpa": None},
    {"pressure_status": "reported", "pressure_gpa": None},
    {"pressure_status": "reported", "pressure_gpa": float("nan")},
    {"pressure_status": "reported", "pressure_gpa": float("inf")},
    {"temperature_role": "measurement", "temperature_k": float("nan")},
    {"temperature_role": "measurement", "temperature_k": float("inf")},
])
async def test_v2_state_pressure_and_temperature_guards_remain_effective(db, changes):
    state, _ = await seed_event(db)
    target = TABLES["material_states"]
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(target.update().where(target.c.id == state).values(**changes))


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/0047_claim_integrity.py"
    spec = importlib.util.spec_from_file_location("ci47_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke_migration(connection, action):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), action)()


async def test_preflight_blocks_legacy_bad_rows_without_repair_and_reports_only_ids(db, caplog):
    # Removing only this migration's constraints inside the rollback-only test
    # transaction recreates 0046 permissiveness, never changes a real database.
    connection = await db.connection()
    await connection.run_sync(invoke_migration, "downgrade")
    material, source = await seed(db)
    other_material, _ = await seed(db)
    ambient = await add(db, "material_claims", **claim_values(
        material, source, pressure_state="explicit_ambient", pressure_gpa=None))
    negative = await add(db, "material_claims", **claim_values(
        material, source, result_status="not_detected", property_type="non_transition",
        validity_status="accepted", minimum_temperature_k=2.0, measurement_method="resistivity",
        value_relation="interval", value_lower_kelvin=10.0, value_upper_kelvin=20.0))
    mismatch = await add(db, "ml_examples", **await example_values(db, other_material, source, ambient))
    before = (await db.execute(sa.select(TABLES["material_claims"]).where(
        TABLES["material_claims"].c.id.in_([ambient, negative])))).mappings().all()
    report = await connection.run_sync(audit_incompatible_rows)
    assert not report["compatible"]
    rules = {row["rule"]: row for row in report["violations"]}
    assert str(ambient) in rules["ck_ci47_claim_pressure_required"]["sample_ids"]
    assert str(negative) in rules["ck_ci47_claim_accepted_outcome"]["sample_ids"]
    assert str(mismatch) in rules[TARGET_FOREIGN_KEY]["sample_ids"]
    assert "SYNTHETIC_NOT_FOR_LOG" not in json.dumps(report)
    caplog.set_level("INFO", logger="alembic.runtime.migration")
    with pytest.raises(RuntimeError, match="no values were repaired"):
        async with db.begin_nested():
            await connection.run_sync(invoke_migration, "upgrade")
    after = (await db.execute(sa.select(TABLES["material_claims"]).where(
        TABLES["material_claims"].c.id.in_([ambient, negative])))).mappings().all()
    assert before == after
    assert "SYNTHETIC_NOT_FOR_LOG" not in caplog.text
    assert "0047 integrity preflight" in caplog.text


async def test_compatible_forward_migration_preserves_data_and_matches_current_metadata(db):
    connection = await db.connection()
    await connection.run_sync(invoke_migration, "downgrade")
    material, source = await seed(db)
    claim = await add(db, "material_claims", **claim_values(
        material, source, result_status="not_detected", property_type="non_transition",
        validity_status="accepted", minimum_temperature_k=2.0, measurement_method="resistivity"))
    # Exercise every legitimate shape and absence category: NULL is data, not
    # automatically an audit violation. This also covers all nullable optional
    # numeric/hash/binding columns left at their defaults on each fixture.
    for relation, values in VALUES.items():
        await add(db, "material_claims", **claim_values(
            material, source, result_status="unknown", property_type="tc",
            validity_status="accepted", value_relation=relation, **values))
    for state, value in (("not_reported", None), ("ambiguous", None),
                         ("ambiguous", 5.0), ("explicit_ambient", 0.0), ("reported", 5.0)):
        await add(db, "material_claims", **claim_values(
            material, source, pressure_state=state, pressure_gpa=value))
    for status, pressure in (("not_reported", None), ("ambiguous", None),
                             ("explicit_ambient", 0.0), ("reported", 5.0)):
        state, event = await seed_event(db)
        await db.execute(TABLES["material_states"].update().where(
            TABLES["material_states"].c.id == state).values(
                pressure_status=status, pressure_gpa=pressure))
        for relation, values in VALUES.items():
            bound_fields = {name: values[key] for name, key in (
                ("value", "value_kelvin"), ("lower", "value_lower_kelvin"),
                ("upper", "value_upper_kelvin")) if key in values}
            await add(db, "event_properties", event_id=event,
                      property_key="band_gap", unit="eV", relation=relation, component_key=relation,
                      record_sha256=uuid.uuid4().hex * 2, **bound_fields)
    preflight = await connection.run_sync(audit_incompatible_rows)
    assert preflight["compatible"], preflight
    await connection.run_sync(invoke_migration, "upgrade")
    assert (await connection.run_sync(audit_incompatible_rows))["compatible"]
    def inspect_constraints(conn):
        inspector = sa.inspect(conn)
        assert set(NEW_CHECKS) <= {row["name"] for row in inspector.get_check_constraints("material_claims")}
        assert TARGET_UNIQUE in {row["name"] for row in inspector.get_unique_constraints("material_claims")}
        assert TARGET_FOREIGN_KEY in {row["name"] for row in inspector.get_foreign_keys("ml_examples")}
    await connection.run_sync(inspect_constraints)
    assert (await db.execute(sa.select(TABLES["material_claims"].c.id).where(
        TABLES["material_claims"].c.id == claim))).scalar_one() == claim


def test_negative_helper_has_no_cross_package_dependency_and_mirrors_ingestion():
    root = Path(__file__).resolve().parents[2]
    assert (root / "api/services/claim_outcomes.py").read_bytes() == (
        root / "ingestion/ingestion/claims/outcomes.py").read_bytes()
    good = {"result_status": "not_detected", "property_type": "non_transition",
            "value_relation": "unreported", "minimum_temperature_k": 2.0,
            "measurement_method": "resistivity"}
    assert not negative_outcome_issues(good)
    assert negative_outcome_issues({**good, "result_status": "unknown"})
    assert negative_outcome_issues({**good, "minimum_temperature_k": True})


@pytest.mark.parametrize("marker", [
    {"outcome": "negative"}, {"outcome_state": "not observed"}, {"outcome": "inconclusive"},
    {"no_transition": True}, {"not_detected": True}, {"superconductivity_observed": False},
    {"transition_observed": False}, {"is_superconducting": False},
])
def test_positive_veto_checks_later_markers_without_proving_a_negative(marker):
    assert outcome_conflicts_with_positive({"result_status": "observed", **marker})
    assert not outcome_conflicts_with_positive({})
    assert not outcome_conflicts_with_positive({"is_superconducting": "false"})
