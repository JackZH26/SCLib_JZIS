"""Real staged snapshots through the operator's default-preview boundaries."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.db import get_session_factory
from services import index_generations as generations
from services import index_vector_adapter as adapter
from services.index_operations import run_operation
from tests.index_generation_fixtures import RESOURCE, prepare_generation_items, write_generation


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


@pytest.fixture
def transport():
    adapter.clear_disposable()
    value = adapter.register_disposable(RESOURCE)
    yield value
    adapter.clear_disposable()


async def test_operator_defaults_do_not_publish_record_or_activate(monkeypatch, db_session, transport):
    logical = "ops-" + uuid4().hex
    _, chunks, pin = await write_generation(monkeypatch, logical_index=logical, count=2)
    def forbidden(*args, **kwargs):
        raise AssertionError("Preview cannot contact a provider")
    monkeypatch.setattr(adapter, "publish", forbidden)
    monkeypatch.setattr(adapter, "observe", forbidden)
    for command in ("inspect", "publish", "observe"):
        result = await run_operation(db_session, {"command": command, "generation_id": pin["generation_id"]})
        assert result["dry_run"] and not result["committed"] and not result["provider_io_performed"]
        assert result["member_count"] == 2 and result["estimated_cost"] is None
        encoded = json.dumps(result)
        assert all(chunk.text not in encoded for chunk in chunks)
        assert "vector_bytes" not in encoded and "endpoint_resource" not in encoded
    assert transport.points == {}
    assert await generations.load_active_generation(db_session, logical_index=logical) is None
    assert await db_session.scalar(text("SELECT count(*) FROM index_generation_validations WHERE generation_id=:id"), {"id": pin["generation_id"]}) == 0


async def test_operator_explicit_publish_observe_and_cas_are_separate(monkeypatch, db_session, transport):
    logical = "ops-live-" + uuid4().hex
    _, _, pin = await write_generation(monkeypatch, logical_index=logical, count=2)
    identifier = pin["generation_id"]
    publication = await run_operation(db_session, {"command": "publish", "generation_id": identifier}, apply=True)
    assert publication["publication"]["acknowledged_count"] == 2
    assert not publication["publication"]["active_generation_changed"]
    assert await generations.load_active_generation(db_session, logical_index=logical) is None
    preview = await run_operation(db_session, {"command": "observe", "generation_id": identifier}, read_remote=True)
    assert preview["validation"]["outcome"] == "validated" and preview["validation"]["dry_run"]
    assert await db_session.scalar(text("SELECT count(*) FROM index_generation_validations WHERE generation_id=:id"), {"id": identifier}) == 0
    observed = await run_operation(db_session, {"command": "observe", "generation_id": identifier}, read_remote=True, apply=True)
    await db_session.commit()
    request = {"command": "activate", "generation_id": identifier,
        "validation_id": observed["validation"]["validation_id"], "expected_event_id": None,
        "idempotency_key": "operator-first", "action": "promote"}
    projected = await run_operation(db_session, request)
    assert projected["activation_receipt"]["mode"] == "generation_snapshot"
    assert not projected["active_generation_changed"] and not projected["receipt_is_current"]
    assert await generations.load_active_generation(db_session, logical_index=logical) is None
    applied = await run_operation(db_session, request, apply=True)
    assert not applied["committed"]  # only the caller is allowed to commit
    await db_session.commit()
    assert (await generations.load_active_generation(db_session, logical_index=logical))["activation_event_id"] == applied["activation_receipt"]["activation_event_id"]
    assert applied["active_generation_changed"] and applied["receipt_is_current"]
    inspected = await run_operation(db_session, {"command": "inspect", "generation_id": identifier})
    assert inspected["is_current"]
    assert inspected["current_active_generation"] == applied["current_active_generation"]
    # A later event makes an exact old retry historical, not a new promotion.
    later_request = {**request, "idempotency_key": "later", "expected_event_id": applied["activation_receipt"]["activation_event_id"]}
    later = await run_operation(db_session, later_request, apply=True)
    await db_session.commit()
    replay = await run_operation(db_session, request, apply=True)
    assert replay["activation_receipt"] == applied["activation_receipt"]
    assert replay["current_active_generation"] == later["current_active_generation"]
    assert not replay["active_generation_changed"] and not replay["receipt_is_current"]
    assert len(transport.points) == 2


async def test_operator_stage_dry_run_and_caller_rollback(monkeypatch, db_session):
    logical = "ops-stage-" + uuid4().hex
    _, chunks, _ = await write_generation(monkeypatch, logical_index=logical, count=1)
    identifier = str(uuid4())
    request = {"command": "stage", "generation_id": identifier, "logical_index": logical,
               "resource": RESOURCE, "items": await prepare_generation_items(db_session, chunks)}
    assert (await run_operation(db_session, request))["member_count"] == 1
    assert await generations.load_generation(db_session, generation_id=identifier) is None
    await run_operation(db_session, request, apply=True)
    await db_session.rollback()
    assert await generations.load_generation(db_session, generation_id=identifier) is None


@pytest.mark.parametrize("operation,apply,read_remote", [
    ({"command": "inspect", "generation_id": str(uuid4())}, True, False),
    ({"command": "publish", "generation_id": str(uuid4())}, False, True),
    ({"command": "observe", "generation_id": str(uuid4())}, True, False),
    ({"command": "delete", "generation_id": str(uuid4())}, False, False),
    ({"command": "inspect", "generation_id": str(uuid4()), "extra": "private"}, False, False),
])
async def test_operator_rejects_ambiguous_authority_before_sql(operation, apply, read_remote):
    with pytest.raises(ValueError):
        await run_operation(None, operation, apply=apply, read_remote=read_remote)
