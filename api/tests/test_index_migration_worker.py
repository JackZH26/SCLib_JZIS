"""Actual guarded SQL migration canary; no provider or production targets.

The standalone worker independently requires an empty capability-owned DB.
These tests exercise its internal fixture on the native metadata test schema;
the parent's separate rehearsal exercises the real Alembic chain.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import index_migration_worker as worker
import pytest
import sqlalchemy as sa
from index_migration_protocol import validate_migration_report
from research_restore_worker import _expected_revision

from models.db import get_session_factory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion"))


async def test_actual_combined_replacement_partial_publication_saved_answer_release_and_rollback(monkeypatch):
    from services import genai_client, index_vector_adapter
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("A synthetic migration must not construct provider clients")
    monkeypatch.setattr(genai_client, "client", forbidden)
    monkeypatch.setattr(index_vector_adapter, "_public_clients", forbidden)
    monkeypatch.setattr(index_vector_adapter, "_public_match_client", forbidden)
    report = await worker._measure_fixture(get_session_factory(), uuid4().hex, _expected_revision())
    assert validate_migration_report(report) == report
    assert not attempts
    assert report["generations"]["before"]["member_count"] == 7
    assert report["generations"]["after"]["member_count"] == 5
    assert report["partial_publication"]["missing_count"] == 4
    assert report["retention"]["before"] == report["retention"]["after"] == report["retention"]["rollback"]
    assert report["retention"]["before"]["measured_paper_pin_count"] == 2
    async with worker._session(get_session_factory(), readonly=True) as db:
        rows = list((await db.execute(sa.text("SELECT generation_id::text,action FROM index_activation_events "
            "WHERE logical_index=:logical ORDER BY event_number"), {"logical": report["logical_index"]})).all())
        assert rows == [(report["generations"]["before"]["generation_id"], "promote"),
                        (report["generations"]["after"]["generation_id"], "promote"),
                        (report["generations"]["before"]["generation_id"], "rollback")]
        outcomes = list((await db.execute(sa.text("SELECT outcome FROM index_generation_validations "
            "WHERE generation_id=:id ORDER BY created_at"),
            {"id": report["generations"]["after"]["generation_id"]})).scalars())
        assert outcomes == ["rejected", "validated"]
        assert await db.scalar(sa.text("SELECT count(*) FROM chunks WHERE paper_id=:paper"), {"paper": worker.PAPERS[0]}) == 3
        from models.db import Base
        from services.answer_evidence import verify_historical
        receipt_table = Base.metadata.tables["answer_evidence_receipts"]
        receipt = dict((await db.execute(sa.select(receipt_table).where(receipt_table.c.generation_id ==
            report["generations"]["before"]["generation_id"]))).mappings().one())
        original_receipt = await verify_historical(db, receipt)
        validation_id = await db.scalar(sa.text("SELECT id FROM index_generation_validations WHERE generation_id=:id "
            "AND outcome='validated' ORDER BY created_at DESC LIMIT 1"),
            {"id": report["generations"]["before"]["generation_id"]})
    # Fixed identities cannot be silently reused or merged into an existing run.
    with pytest.raises(ValueError, match="index_migration_measurement_invalid"):
        await worker._measure_fixture(get_session_factory(), uuid4().hex, _expected_revision())
    # A real later source hold must block a new activation, not erase history.
    from services.index_generations import IndexGenerationError, activate_generation
    async with worker._session(get_session_factory()) as db:
        await db.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:paper"), {"paper": worker.PAPERS[0]})
    before = await worker._activation_snapshot(get_session_factory(), report["logical_index"])
    with pytest.raises(IndexGenerationError, match="Current source lifecycle hold"):
        async with worker._session(get_session_factory()) as db:
            await activate_generation(db, generation_id=report["generations"]["before"]["generation_id"],
                validation_id=validation_id, expected_event_id=report["queries"]["rollback"]["activation_event_id"],
                idempotency_key="synthetic-held-rollback", action="rollback", dry_run=False)
    assert await worker._activation_snapshot(get_session_factory(), report["logical_index"]) == before
    async with worker._session(get_session_factory(), readonly=True) as db:
        assert await verify_historical(db, receipt) == original_receipt


async def test_public_worker_refuses_foreign_capability_before_client_construction(monkeypatch):
    from dataclasses import replace

    from test_safety import validate_test_environment
    cap = validate_test_environment()
    bad = replace(cap, manifest={**cap.manifest, "run_id": "0" * 32})
    import research_restore_worker
    async def forbidden(*args):
        raise AssertionError("Capability mismatch must precede a DB client")
    monkeypatch.setattr(research_restore_worker, "_engine", forbidden)
    with pytest.raises(ValueError, match="index_migration_measurement_invalid"):
        await worker.measure_migration(bad)


async def test_public_worker_rejects_preexisting_database_without_changing_it():
    from test_safety import validate_test_environment

    from models.db import Base
    cap = validate_test_environment()
    identifier = "migration-preexisting-" + uuid4().hex
    async with worker._session(get_session_factory()) as db:
        await db.execute(Base.metadata.tables["papers"].insert().values(id=identifier, source="arxiv",
            title="Synthetic existing row", authors=["Synthetic Fixture"], abstract="Synthetic existing metadata."))
    before = await worker._activation_snapshot(get_session_factory(), "migration-" + cap.run_id)
    async with worker._session(get_session_factory(), readonly=True) as db:
        row_before = await db.scalar(sa.text("SELECT to_jsonb(p)::text FROM papers p WHERE id=:id"), {"id": identifier})
    with pytest.raises(ValueError, match="index_migration_measurement_invalid"):
        await worker.measure_migration(cap)
    assert await worker._activation_snapshot(get_session_factory(), "migration-" + cap.run_id) == before
    async with worker._session(get_session_factory(), readonly=True) as db:
        assert await db.scalar(sa.text("SELECT to_jsonb(p)::text FROM papers p WHERE id=:id"), {"id": identifier}) == row_before


@pytest.mark.parametrize("target", ["client", "_embed", "_public_clients", "_public_match_client", "_index"])
def test_provider_attempts_are_counted_rejected_and_original_factory_restored(target):
    from ingestion.index import indexer

    from services import genai_client, index_vector_adapter
    module = genai_client if target == "client" else indexer if target == "_index" else index_vector_adapter
    original = getattr(module, target)
    with worker._forbid_providers() as counter:
        with pytest.raises(RuntimeError, match="index_migration_provider_forbidden"):
            getattr(module, target)()
        assert counter["attempts"] == 1
    assert getattr(module, target) is original
