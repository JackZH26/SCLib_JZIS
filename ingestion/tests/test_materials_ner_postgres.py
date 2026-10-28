"""Real Postgres checks; only the repository's disposable service capability is accepted."""
from copy import deepcopy
import os
from pathlib import Path
import runpy
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "ingestion"))
from test_safety import validate_test_environment, verify_postgres_identity  # noqa: E402


@pytest.mark.asyncio
async def test_postgres_atomic_import_readback_idempotence_and_no_self_approval(tmp_path):
    # Validate ownership before creating a database connection.
    capability = validate_test_environment()
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(verify_postgres_identity, capability)
    from ingestion.materials_ner.contract import digest
    from ingestion.materials_ner.proposals import import_packet
    from ingestion.materials_ner.sources import save_bundle
    from ingestion.materials_ner.store import Store
    from ingestion.materials_ner.worker import configuration, run_one
    from test_materials_ner_pipeline import example, FakeProvider

    bundle, extraction = example()
    bundle.work_id = extraction["work_id"] = "arxiv:0001.00001"
    store = Store(tmp_path)
    bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration())
    run_one(store, job_id=job, provider_override=FakeProvider(extraction))
    packet = import_packet(store, job)
    namespace = runpy.run_path(str(REPO / "api/models/materials_ner_proposals_v1.py"))
    namespace.update(__name__="bridge_for_test")
    exec(compile((REPO / "scripts/materials_ner_db_bridge.py").read_text(), "<bridge-test>", "exec"), namespace)
    process = namespace["process"]
    assert (await process({"action": "initialize"}, url))["tables"]["runs"] == 0
    first = await process({"action": "ingest", "packet": packet}, url)
    assert first["inserted"] and first["readback_verified"] and first["tables"]["results"] == 1
    duplicate = await process({"action": "ingest", "packet": packet}, url)
    assert not duplicate["inserted"] and duplicate["tables"] == first["tables"]
    bad = deepcopy(packet)
    bad["receipt"]["attempt_id"] = "different-synthetic-attempt"
    bad["run_id"] = digest(bad["receipt"])
    bad["rows"]["results"][0]["payload"]["sample_id"] = "dangling"
    bad["packet_hash"] = digest({k: v for k, v in bad.items() if k != "packet_hash"})
    with pytest.raises(Exception, match="ForeignKeyViolation|IntegrityError"):
        await process({"action": "ingest", "packet": bad}, url)
    assert (await process({"action": "status"}, url))["tables"] == first["tables"]
    with pytest.raises(Exception, match="CheckViolation|IntegrityError"):
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE materials_ner_v1.runs SET scientific_acceptance=true"))
    async with engine.begin() as connection:
        # The future Alembic migration must adopt an initialized identical schema.
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        migration = runpy.run_path(str(REPO / "api/alembic/versions/0092_materials_ner_proposals.py"))
        def adopt(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration["upgrade"]()
        await connection.run_sync(adopt)
    await engine.dispose()
