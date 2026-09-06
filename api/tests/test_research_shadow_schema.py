"""Real PostgreSQL constraint tests on the isolated pytest database."""

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from models.db import Base, get_session_factory
from models.research_schema_v2 import TABLE_ORDER


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    # Keep the open transaction and its teardown on the same asyncio loop.
    async with get_session_factory()() as session:
        yield session


async def add(db, name, **values):
    table = Base.metadata.tables[name]
    result = await db.execute(table.insert().values(**values).returning(table.c.id))
    return result.scalar_one()


async def seed(db):
    material = "rv2-" + uuid.uuid4().hex
    await add(db, "materials", id=material, formula="MgB2", formula_normalized="MgB2")
    artifact = await add(
        db,
        "evidence_artifacts",
        kind="literature_locator",
        schema_version="1",
        source="synthetic-test",
        record_sha256="a" * 64,
        hash_status="not_applicable",
        access="metadata_only",
    )
    state = await add(
        db,
        "material_states",
        material_id=material,
        resolution="source_scoped",
        condition_schema_version="1",
        pressure_status="not_reported",
        temperature_role="unknown",
        context_sha256="b" * 64,
        source_artifact_id=artifact,
    )
    event = await add(
        db,
        "research_events",
        material_id=material,
        state_id=state,
        event_type="measurement",
        knowledge_origin="Observed",
        record_sha256="c" * 64,
    )
    return material, artifact, state, event


def test_shadow_scope_is_explicit_and_tc_single_source():
    assert len(TABLE_ORDER) == 10
    assert set(TABLE_ORDER) <= set(Base.metadata.tables)
    assert Base.metadata.tables["ml_examples"].c.claim_id.nullable is False
    assert Base.metadata.tables["material_claims"].c.event_id.nullable is True
    assert "uq_material_claims_material_source_hash" in {
        c.name for c in Base.metadata.tables["material_claims"].constraints
    }


async def test_material_state_event_and_structure_cannot_cross_materials(db_session):
    m1, artifact, s1, e1 = await seed(db_session)
    m2, _, s2, _ = await seed(db_session)
    sample = await add(db_session, "research_samples", material_id=m1, source_artifact_id=artifact)
    structure_artifact = await add(
        db_session,
        "evidence_artifacts",
        kind="structure",
        schema_version="1",
        source="synthetic",
        record_sha256="a" * 64,
        hash_status="unavailable",
        access="unknown",
    )
    structure = await add(
        db_session,
        "structure_records",
        material_id=m1,
        structure_kind="coordinates",
        coordinate_artifact_kind="structure",
        artifact_id=structure_artifact,
        record_sha256="d" * 64,
    )
    cases = [
        (
            "research_events",
            dict(
                material_id=m2,
                state_id=s1,
                event_type="measurement",
                knowledge_origin="Observed",
                record_sha256="c" * 64,
            ),
        ),
        (
            "material_states",
            dict(
                material_id=m2,
                sample_id=sample,
                resolution="source_scoped",
                condition_schema_version="1",
                pressure_status="not_reported",
                temperature_role="unknown",
                context_sha256="b" * 64,
                source_artifact_id=artifact,
            ),
        ),
        (
            "research_events",
            dict(
                material_id=m2,
                state_id=s2,
                structure_id=structure,
                event_type="measurement",
                knowledge_origin="Observed",
                record_sha256="c" * 64,
            ),
        ),
    ]
    for name, values in cases:
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await add(db_session, name, **values)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.delete(Base.metadata.tables["material_states"]).where(
                    Base.metadata.tables["material_states"].c.id == s1
                )
            )


@pytest.mark.parametrize(
    ("pressure", "status"),
    [
        (0, "not_reported"),
        (None, "reported"),
        (None, "explicit_ambient"),
        (float("nan"), "reported"),
        (float("inf"), "reported"),
        (-1, "reported"),
    ],
)
async def test_pressure_is_not_fabricated_or_nonfinite(db_session, pressure, status):
    material, artifact, _, _ = await seed(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(
                db_session,
                "material_states",
                material_id=material,
                resolution="source_scoped",
                condition_schema_version="1",
                pressure_status=status,
                pressure_gpa=pressure,
                temperature_role="unknown",
                context_sha256="b" * 64,
                source_artifact_id=artifact,
            )


@pytest.mark.parametrize(
    ("key", "unit", "value"),
    [
        ("tc", "K", 10),
        ("Tc", "K", 10),
        ("band_gap", "K", 10),
        ("band_gap", "eV", -1),
        ("formation_energy_per_atom", "eV/atom", float("nan")),
        ("formation_energy_per_atom", "eV/atom", float("inf")),
    ],
)
async def test_properties_reject_tc_unregistered_units_and_invalid_values(
    db_session, key, unit, value
):
    _, _, _, event = await seed(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(
                db_session,
                "event_properties",
                event_id=event,
                property_key=key,
                relation="exact",
                value=value,
                unit=unit,
                record_sha256="a" * 64,
            )


async def test_negative_formation_energy_components_and_precise_lineage(db_session):
    _, artifact, _, event = await seed(db_session)
    _, _, _, other_event = await seed(db_session)
    _, _, _, third_event = await seed(db_session)
    prop = await add(
        db_session,
        "event_properties",
        event_id=event,
        property_key="formation_energy_per_atom",
        relation="exact",
        value=-0.25,
        unit="eV/atom",
        record_sha256="a" * 64,
    )
    await add(
        db_session,
        "event_properties",
        event_id=event,
        property_key="formation_energy_per_atom",
        relation="exact",
        value=-0.3,
        unit="eV/atom",
        component_key="other-phase",
        record_sha256="b" * 64,
    )
    await add(
        db_session,
        "event_evidence",
        event_id=other_event,
        link_type="derives_from",
        input_event_id=event,
        input_property_id=prop,
    )
    for extra in (
        {"input_event_id": third_event},
        {"input_event_id": None},
        {"artifact_id": artifact},
    ):
        values = dict(
            event_id=other_event,
            link_type="derives_from",
            input_event_id=event,
            input_property_id=prop,
        )
        values.update(extra)
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await add(db_session, "event_evidence", **values)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(
                db_session,
                "event_properties",
                event_id=event,
                property_key="formation_energy_per_atom",
                relation="exact",
                value=-0.5,
                unit="eV/atom",
                record_sha256="a" * 64,
            )


async def test_stable_event_can_be_captured_twice_but_revision_must_match(db_session):
    _, _, _, event = await seed(db_session)
    snapshots = []
    for version in ("test-1", "test-2"):
        snapshot = await add(
            db_session, "source_snapshots", dataset_version=version, schema_version="2"
        )
        snapshots.append(snapshot)
        await add(
            db_session,
            "snapshot_event_memberships",
            snapshot_id=snapshot,
            event_id=event,
            event_revision=1,
            source_occurrence_key="row-1",
            source_record_sha256="a" * 64,
            result_manifest_sha256="b" * 64,
        )
    for revision in (1, 2):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await add(
                    db_session,
                    "snapshot_event_memberships",
                    snapshot_id=snapshots[0],
                    event_id=event,
                    event_revision=revision,
                    source_occurrence_key="row-1" if revision == 1 else "row-2",
                    source_record_sha256="a" * 64,
                    result_manifest_sha256="b" * 64,
                )


async def test_rps_properties_require_inferred_assessment_and_priority_run(db_session):
    material, _, state, observed = await seed(db_session)
    values = dict(
        property_key="rps_score", relation="exact", value=7100, unit="point", record_sha256="a" * 64
    )
    for discriminator in (None, "priority_assessment"):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await add(
                    db_session,
                    "event_properties",
                    event_id=observed,
                    assessment_event_type=discriminator,
                    **values,
                )
    run = await add(
        db_session,
        "research_runs",
        run_kind="priority_assessment",
        settings_schema_version="RPS-v1.2",
        record_sha256="b" * 64,
    )
    event = await add(
        db_session,
        "research_events",
        material_id=material,
        state_id=state,
        event_type="priority_assessment",
        knowledge_origin="Inferred",
        producer_run_id=run,
        assessment_run_kind="priority_assessment",
        record_sha256="c" * 64,
    )
    await add(
        db_session,
        "event_properties",
        event_id=event,
        assessment_event_type="priority_assessment",
        **values,
    )
    for relation, extra in (("exact", {"value": 101}), ("interval", {"lower": 50, "upper": 101})):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await add(
                    db_session,
                    "event_properties",
                    event_id=event,
                    assessment_event_type="priority_assessment",
                    property_key="rps_gain",
                    relation=relation,
                    unit="point",
                    record_sha256="a" * 64,
                    **extra,
                )


async def test_tc_onset_and_zero_share_event_without_rewriting_source_identity(db_session):
    material, _, _, event = await seed(db_session)
    snapshot = await add(db_session, "source_snapshots", dataset_version="tc-binding", schema_version="1")
    claims = []
    for key, value, source_hash in (("onset", 39, "d" * 64), ("zero", 38, "e" * 64)):
        claims.append(await add(db_session, "material_claims", material_id=material,
                                source_snapshot_id=snapshot, source_record_hash=source_hash,
                                value_relation="exact", value_kelvin=value, result_status="observed",
                                event_id=event, result_key=key, interpretation_revision=1, extractor_version="test"))
    assert claims[0] != claims[1]
    for key, source_hash in (("onset", "f" * 64), ("new-interpretation", "d" * 64)):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await add(db_session, "material_claims", material_id=material,
                          source_snapshot_id=snapshot, source_record_hash=source_hash,
                          value_relation="exact", value_kelvin=39, result_status="observed",
                          event_id=event, result_key=key, interpretation_revision=2, extractor_version="test")
