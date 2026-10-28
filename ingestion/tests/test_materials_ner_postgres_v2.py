"""Owned disposable Postgres checks for lossless, unapproved proposal storage."""
from copy import deepcopy
import os
from pathlib import Path
import runpy
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / part) for part in ("api", "scripts", "ingestion")]
from test_safety import validate_test_environment, verify_postgres_identity
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.proposals import import_packet
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration, run_one
from materials_ner_db_bridge_v2 import process
from models import materials_ner_proposals_v1 as base, materials_ner_proposals_v2 as relations
from services.materials_proposal_storage import verify_readback
from test_materials_ner_relations import fixture as relation_fixture
from test_materials_ner_native import fixture as legacy_fixture
from test_materials_ner_inventory_v2 import SequenceProvider


@pytest.fixture(scope="module")
def packets(tmp_path_factory):
    result = {}
    for version, fixture, workflow in ((1, legacy_fixture, "inventory_v7"), (2, relation_fixture, "inventory_v8")):
        root = tmp_path_factory.mktemp("proposal-storage")
        bundle, inventory, raw = fixture()
        store = Store(root)
        checksum, _ = save_bundle(root, bundle)
        job = store.enqueue(work_id=bundle.work_id, bundle_hash=checksum, config=configuration(workflow=workflow))
        run_one(store, job_id=job, provider_override=SequenceProvider([inventory, raw]))
        result[version] = import_packet(store, job)
    return result


@pytest_asyncio.fixture
async def database():
    capability = validate_test_environment()
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(verify_postgres_identity, capability)
        assert (await connection.execute(text("SELECT to_regnamespace('materials_ner_v1')"))).scalar() is None
    try:
        yield url, engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(verify_postgres_identity, capability)
            await connection.execute(text("DROP SCHEMA IF EXISTS materials_ner_v1 CASCADE"))
        await engine.dispose()


async def migration(engine, action):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    script = runpy.run_path(str(REPO / "api/alembic/versions/0100_materials_ner_relations.py"))
    def execute(connection):
        with Operations.context(MigrationContext.configure(connection)):
            script[action]()
    async with engine.begin() as connection:
        await connection.run_sync(execute)


async def counts(url):
    return (await process({"action": "status"}, url))["tables"]


@pytest.mark.asyncio
async def test_frozen_v1_importer_adoption_and_complete_v2_roundtrip(database, packets):
    url, engine = database
    namespace = runpy.run_path(str(REPO / "api/models/materials_ner_proposals_v1.py"))
    namespace.update(__name__="legacy_bridge_test")
    exec(compile((REPO / "scripts/materials_ner_db_bridge.py").read_text(), "<legacy-bridge>", "exec"), namespace)
    legacy = namespace["process"]
    await legacy({"action": "initialize"}, url)
    old = await legacy({"action": "ingest", "packet": packets[1]}, url)
    await migration(engine, "upgrade")
    await migration(engine, "upgrade")  # Adoption of the same fingerprint is idempotent.
    adopted = await process({"action": "ingest", "packet": packets[1]}, url)
    assert not adopted["inserted"] and adopted["readback_verified"]
    assert adopted["tables"]["results"] == old["tables"]["results"]
    first = await process({"action": "ingest", "packet": packets[2]}, url)
    second = await process({"action": "ingest", "packet": packets[2]}, url)
    assert first["inserted"] and not second["inserted"]
    assert first["relational_readback"] == second["relational_readback"]
    assert [first["tables"][name] for name in relations.ADDED_TABLES] == [1, 1, 2]
    assert not first["scientific_acceptance"] and not first["ml_training_eligible"]
    with pytest.raises(RuntimeError, match="retained Materials NER"):
        await migration(engine, "downgrade")
    assert await counts(url) == first["tables"]
    async with engine.begin() as connection:
        for packet in packets.values():
            await verify_readback(connection, packet)
        assert not (await connection.execute(text("SELECT EXISTS(SELECT 1 FROM information_schema.role_table_grants "
            "WHERE table_schema='materials_ner_v1' AND grantee='PUBLIC')"))).scalar_one()


@pytest.mark.asyncio
async def test_empty_extension_downgrade_preserves_legacy_records(database, packets):
    url, engine = database
    await process({"action": "initialize"}, url)
    await process({"action": "ingest", "packet": packets[1]}, url)
    await migration(engine, "downgrade")
    async with engine.begin() as connection:
        assert (await connection.execute(text("SELECT payload FROM materials_ner_v1.runs"))).scalar_one() == packets[1]
        assert (await connection.execute(text("SELECT fingerprint FROM materials_ner_v1.schema_version"))).scalar_one() == base.FINGERPRINT
    with pytest.raises(ValueError, match="fingerprint"):
        await process({"action": "ingest", "packet": packets[2]}, url)
    await migration(engine, "upgrade")
    result = await process({"action": "ingest", "packet": packets[1]}, url)
    assert not result["inserted"] and result["readback_verified"]


@pytest.mark.asyncio
async def test_late_sql_failure_rolls_back_complete_packet(database, packets):
    url, engine = database
    await process({"action": "initialize"}, url)
    before = await counts(url)
    async with engine.begin() as connection:
        await connection.execute(text("ALTER TABLE materials_ner_v1.condition_supports "
                                      "ADD CONSTRAINT synthetic_failure CHECK (false) NOT VALID"))
    with pytest.raises(IntegrityError):
        await process({"action": "ingest", "packet": packets[2]}, url)
    assert await counts(url) == before


@pytest.mark.parametrize("sql", [
    "UPDATE materials_ner_v1.condition_supports SET condition_id='missing'",
    "UPDATE materials_ner_v1.condition_supports SET state_id='other-state'",
    "UPDATE materials_ner_v1.condition_supports SET run_id=repeat('0',64)",
    "UPDATE materials_ner_v1.sample_relations SET to_sample_id=from_sample_id",
    "UPDATE materials_ner_v1.sample_relations SET from_sample_id='absent'",
    "UPDATE materials_ner_v1.runs SET ml_training_eligible=true",
])
@pytest.mark.asyncio
async def test_database_rejects_broken_ownership_and_self_approval(database, packets, sql):
    url, engine = database
    await process({"action": "initialize"}, url)
    await process({"action": "ingest", "packet": packets[2]}, url)
    async with engine.begin() as connection:
        # A second existing state makes the composite result/state FK essential.
        await connection.execute(text("INSERT INTO materials_ner_v1.states "
            "SELECT run_id,'other-state',sample_id,review_status,payload FROM materials_ner_v1.states LIMIT 1"))
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text(sql))


@pytest.mark.parametrize("sql,match", [
    ("UPDATE materials_ner_v1.conditions SET payload='{}'::jsonb", "relational readback"),
    ("DELETE FROM materials_ner_v1.condition_supports", "relational readback"),
    ("UPDATE materials_ner_v1.evidence SET path='/wrong'", "relational readback"),
    ("UPDATE materials_ner_v1.results SET review_status='quarantined'", "relational readback"),
    ("UPDATE materials_ner_v1.runs SET packet_hash=repeat('0',64)", "immutable proposal collision"),
])
@pytest.mark.asyncio
async def test_duplicate_import_checks_all_relational_rows(database, packets, sql, match):
    url, engine = database
    await process({"action": "initialize"}, url)
    await process({"action": "ingest", "packet": packets[2]}, url)
    async with engine.begin() as connection:
        await connection.execute(text(sql))
    with pytest.raises(ValueError, match=match):
        await process({"action": "ingest", "packet": packets[2]}, url)


@pytest.mark.parametrize("change,match", [
    ("rows", "row derivation mismatch"), ("evidence", "evidence projection mismatch"),
    ("job", "job binding mismatch"), ("approval", "cannot self-approve"),
])
@pytest.mark.asyncio
async def test_hash_resealing_does_not_approve_an_inconsistent_packet(database, packets, change, match):
    url, _ = database
    await process({"action": "initialize"}, url)
    bad = deepcopy(packets[2])
    if change == "rows": bad["rows"]["sample_relations"] = []
    if change == "evidence": bad["evidence"] = []
    if change == "job": bad["job_id"] = "unrelated-job"
    if change == "approval": bad["scientific_acceptance"] = True
    bad["packet_hash"] = digest({k: v for k, v in bad.items() if k != "packet_hash"})
    with pytest.raises(ValueError, match=match):
        await process({"action": "ingest", "packet": bad}, url)
    assert not any((await counts(url)).values())


@pytest.mark.asyncio
async def test_mismatched_schema_is_not_silently_adopted(database):
    url, engine = database
    await process({"action": "initialize"}, url)
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE materials_ner_v1.schema_version SET fingerprint='wrong' WHERE version=:v"),
                                 {"v": relations.VERSION})
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        await process({"action": "initialize"}, url)
