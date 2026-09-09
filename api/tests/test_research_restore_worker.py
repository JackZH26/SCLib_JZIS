"""Actual synthetic source fixture checks, not a substitute for pg_restore.

Run only through scripts/run_disposable_tests.py. The standalone worker never
imports this module or pytest/conftest. The parent restore rehearsal separately
tests migration, actual dump/restore and a fresh index in independent processes.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import research_restore_worker as worker
import sqlalchemy as sa
from research_restore_index import verify_index
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_engine
from services.ml_coordinate_features import coordinate_features
from services.research_freeze import inspect_research_release


async def test_actual_typed_source_capsule_access_and_readonly_index_rebuild():
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine) as db:
            async with db.begin():
                await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                await db.execute(sa.text("SET LOCAL statement_timeout='10000ms'"))
                seeded = await worker.seed_rows(db, uuid4().hex)
                release = seeded["release"]
                inspected = await inspect_research_release(db, release_id=release["release_id"],
                    expected_manifest_sha256=release["manifest_sha256"], artifact_bytes=seeded["artifact_bytes"])
                assert inspected["manifest_sha256"] == release["manifest_sha256"]
                assert {row["table"] for row in release["manifest"]["rows"]} >= {
                    "material_claims", "material_states", "research_runs", "structure_records",
                    "event_properties", "research_samples", "works", "ml_examples", "ml_example_inputs",
                }
                runs = (await db.execute(sa.text("SELECT status,settings FROM research_runs WHERE code_version='synthetic-not-executed/1'"))).all()
                assert runs and all(status == "planned" and settings["actual_calculation_executed"] is False for status, settings in runs)
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
