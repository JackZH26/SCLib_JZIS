"""Actual synthetic source fixture checks, not a substitute for pg_restore.

Run only through scripts/run_disposable_tests.py. The standalone worker never
imports this module or pytest/conftest. The parent restore rehearsal separately
tests migration, actual dump/restore and a fresh index in independent processes.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import research_restore_worker as worker
import sqlalchemy as sa
from research_restore_index import verify_index
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, get_engine
from services.ml_coordinate_features import coordinate_features
from services.research_freeze import inspect_research_release


@pytest.mark.parametrize("with_unrelated_completed_run", [False, True])
async def test_actual_typed_source_capsule_access_and_readonly_index_rebuild(with_unrelated_completed_run):
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine) as db:
            async with db.begin():
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                await db.execute(sa.text("SET LOCAL statement_timeout='10000ms'"))
                run_table = Base.metadata.tables["research_runs"]
                unrelated_id = None
                unrelated_before = None
                unrelated_paper = None
                unrelated_links = None
                if with_unrelated_completed_run:
                    # The version label is intentionally shared by independent
                    # synthetic fixtures; it is not this capsule's run identity.
                    unrelated_id = uuid4()
                    await db.execute(run_table.insert().values(
                        id=unrelated_id, run_kind="dfpt", status="completed",
                        code_version="synthetic-not-executed/1",
                        settings_schema_version="restore-synthetic/1",
                        settings={"synthetic": True, "actual_calculation_executed": False},
                        record_sha256=worker._sha(str(unrelated_id).encode()),
                    ))
                    unrelated_before = (await db.execute(sa.select(
                        sa.func.to_jsonb(run_table.table_valued())
                    ).where(run_table.c.id == unrelated_id))).scalar_one()
                    # A second capsule's legitimate review history must neither
                    # fail this fixture's verification nor be removed to pass it.
                    other = await worker.seed_rows(db, uuid4().hex)
                    unrelated_paper = other["index"]["paper_id"]
                    unrelated_links = (await db.execute(sa.text("""SELECT to_jsonb(r)
                        FROM scientific_result_passage_links r WHERE paper_id=:paper
                        ORDER BY created_at"""), {"paper": unrelated_paper})).scalars().all()
                    assert len(unrelated_links) == 3
                seeded = await worker.seed_rows(db, uuid4().hex)
                release = seeded["release"]
                inspected = await inspect_research_release(db, release_id=release["release_id"],
                    expected_manifest_sha256=release["manifest_sha256"], artifact_bytes=seeded["artifact_bytes"])
                assert inspected["manifest_sha256"] == release["manifest_sha256"]
                assert {row["table"] for row in release["manifest"]["rows"]} >= {
                    "material_claims", "material_states", "research_runs", "structure_records",
                    "event_properties", "research_samples", "works", "ml_examples", "ml_example_inputs",
                }
                # Run identity comes from this verified dependency closure,
                # not a non-unique code/version label shared by other fixtures.
                run_ids = {UUID(row["row_id"]) for row in release["manifest"]["rows"]
                           if row["table"] == "research_runs"}
                assert len(run_ids) == 1 and unrelated_id not in run_ids
                runs = (await db.execute(sa.select(
                    run_table.c.id, run_table.c.status, run_table.c.settings, run_table.c.code_version
                ).where(run_table.c.id.in_(run_ids)))).all()
                assert {row.id for row in runs} == run_ids
                assert all(row.status == "planned" and row.settings["actual_calculation_executed"] is False
                           and row.code_version == "synthetic-not-executed/1" for row in runs)
                coordinates = next(payload for payload in seeded["artifact_bytes"].values()
                                   if b'"version":"sclib-coordinate/1.0.0"' in payload)
                result = coordinate_features(coordinates, expected_sha256=worker._sha(coordinates), source_formula="MgB2",
                                             coordinate_format="sclib-coordinate/1.0.0", geometry_scope="bulk_3d_no_vacuum")
                assert result["status"] == "computed"
                snapshot = await worker.sql_snapshot(db)
                assert snapshot["sha256"] == worker._sha(worker._canonical(snapshot["tables"]))
                assert not any(row["table"].startswith("sclib_test_guard") for row in snapshot["tables"])
            async with db.begin():
                await db.execute(sa.text("SET TRANSACTION READ ONLY"))
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                await db.execute(sa.text("SET LOCAL statement_timeout='10000ms'"))
                before = await worker.sql_snapshot(db)
                await worker.verify_access(db, seeded)
                with pytest.raises(worker.WorkerError):
                    await worker.verify_result_passage_links(db, paper_id=seeded["index"]["paper_id"],
                        reviewer_id=seeded["actors"]["member"])
                with pytest.raises(worker.WorkerError):
                    await worker.verify_result_passage_links(db, paper_id="missing-synthetic-paper",
                        reviewer_id=seeded["actors"]["reviewer"])
                report = await verify_index(db, seeded["index"])
                assert report["initial_index_count"] == 0
                assert report["initial_upsert_count"] == 2
                assert report["replay_upsert_count"] == 0
                assert report["provider_io_performed"] is False
                assert report["external_production_vector_restore_verified"] is False
                assert await worker.sql_snapshot(db) == before
                broken = deepcopy(seeded["index"])
                broken["claim_record_sha256"] = "0" * 64
                with pytest.raises(ValueError):
                    await verify_index(db, broken)
                assert await worker.sql_snapshot(db) == before
                if unrelated_id is not None:
                    assert (await db.execute(sa.select(
                        sa.func.to_jsonb(run_table.table_valued())
                    ).where(run_table.c.id == unrelated_id))).scalar_one() == unrelated_before
                    assert (await db.execute(sa.text("""SELECT to_jsonb(r)
                        FROM scientific_result_passage_links r WHERE paper_id=:paper
                        ORDER BY created_at"""), {"paper": unrelated_paper})).scalars().all() == unrelated_links
    finally:
        await engine.dispose()


class SnapshotDB:
    def __init__(self, *, names=None, counts=None):
        self.names = names or ["first", "second"]
        self.counts = iter(counts or [(1, 10), (1, 20)])
        self.aggregates = 0

    async def execute(self, query):
        class Result:
            def __init__(self, data):
                self.data = data

            def scalars(self):
                return self

            def all(self):
                return self.data

            def one(self):
                return self.data
        if "pg_tables" in str(query):
            return Result(self.names)
        return Result(next(self.counts))

    async def scalar(self, _query):
        self.aggregates += 1
        return "a" * 64


@pytest.mark.parametrize("counts", [[(20001, 1)], [(1, 32 * 1024 * 1024 + 1)], [(10000, 1), (10001, 1)]])
async def test_snapshot_refuses_entire_inventory_before_hydrating_any_table(counts):
    db = SnapshotDB(counts=counts)
    with pytest.raises(worker.WorkerError):
        await worker.sql_snapshot(db)
    assert db.aggregates == 0


@pytest.mark.parametrize("names", [["unsafe; SELECT 1"], ["A"], ["x" * 64], ["safe"] * 513])
async def test_snapshot_table_name_and_inventory_bounds(names):
    db = SnapshotDB(names=names)
    with pytest.raises(worker.WorkerError):
        await worker.sql_snapshot(db)
    assert db.aggregates == 0


async def test_actual_not_valid_constraint_refuses_schema_gate_and_rollback_restores_it():
    engine = get_engine()
    try:
        async with AsyncSession(engine) as db:
            async with db.begin():
                await worker._schema_validity(db)
                nested = await db.begin_nested()
                await db.execute(sa.text("ALTER TABLE public.stats_cache ADD CONSTRAINT restore_worker_not_valid CHECK (true) NOT VALID"))
                with pytest.raises(worker.WorkerError):
                    await worker._schema_validity(db)
                await nested.rollback()
                await worker._schema_validity(db)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("value", [1, 2, None, False])
async def test_schema_validity_never_treats_unknown_or_invalid_objects_as_zero(value):
    class DB:
        async def scalar(self, query):
            assert "convalidated" in str(query) and "indisvalid" in str(query) and "indisready" in str(query)
            return value
    with pytest.raises(worker.WorkerError):
        await worker._schema_validity(DB())
