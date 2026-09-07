"""Direct-SQL negative task invariants on guarded disposable PostgreSQL."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, get_engine
from models.source_tasks_v1 import ACTION_VERSION, INVENTORY_VERSION
from services.research_publication import revoke_role
from services.research_release_manifest import canonical, digest
from services.source_impact import inspect_source_impact
from tests.test_research_freeze import add
from tests.test_research_publication import actors
from tests.test_source_impact import observation


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


async def request_values(db, *, kind="paper"):
    people = await actors(db)
    source, arguments = await observation(db, kind=kind)
    inventory = await inspect_source_impact(db, **arguments)
    body = {key: value for key, value in inventory.items() if key not in {"observation", "inventory_sha256"}}
    return people, source, dict(event_id=UUID(arguments["event_id"]), event_sha256=arguments["expected_event_sha256"],
        source_snapshot_sha256=body["event"]["source_snapshot_sha256"], inventory_version=INVENTORY_VERSION,
        inventory_sha256=digest(body), inventory_json=canonical(body).decode(), action_version=ACTION_VERSION,
        requester_id=people["curator"], requester_grant_id=people["grants"]["curator"], request_key="schema-" + uuid4().hex)


def attempt_values(request, people, *, prior=None, status="succeeded", outcome="timeline_cache_invalidated"):
    return dict(request_id=request["id"], attempt_number=prior["attempt_number"] + 1 if prior else 1,
        predecessor_id=prior["id"] if prior else None, executor_id=people["curator"],
        executor_grant_id=people["grants"]["curator"], execution_key="execution-" + uuid4().hex,
        status=status, outcome_code=outcome)


async def stored(db, table):
    relation = Base.metadata.tables[table]
    return (await db.execute(sa.select(relation).order_by(relation.c.id))).mappings().all()


def verify_hash(row):
    body = {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
            if key not in {"created_at", "record_sha256", "inventory_json"}}
    assert row["record_sha256"] == digest(body)


async def projection_state(db, version=6):
    await db.execute(sa.text("""INSERT INTO timeline_projection_state(id,schema_version,classifier_version,
        pressure_policy_version,anomaly_policy_version,source_year,source_watermark,refreshed_at,material_count,active_point_count)
        VALUES (1,:version,'synthetic/classifier','synthetic/pressure','synthetic/anomaly',2026,:now,:now,123,456)
        ON CONFLICT (id) DO UPDATE SET schema_version=EXCLUDED.schema_version,
        classifier_version=EXCLUDED.classifier_version,pressure_policy_version=EXCLUDED.pressure_policy_version,
        anomaly_policy_version=EXCLUDED.anomaly_policy_version,source_year=EXCLUDED.source_year,
        source_watermark=EXCLUDED.source_watermark,refreshed_at=EXCLUDED.refreshed_at,
        material_count=EXCLUDED.material_count,active_point_count=EXCLUDED.active_point_count"""),
        {"version": version, "now": datetime(2026, 9, 7, tzinfo=UTC)})


@pytest.mark.parametrize("kind", ["paper", "work"])
async def test_exact_request_hash_and_atomic_singleton_invalidation(db_session, kind):
    people, source, values = await request_values(db_session, kind=kind)
    request = await add(db_session, "source_task_requests", **values)
    verify_hash(request)
    await projection_state(db_session)
    before = list(await stored(db_session, "timeline_projection_state"))
    points = list(await stored(db_session, "timeline_projection_points"))
    attempt = await add(db_session, "source_task_attempts", **attempt_values(request, people))
    assert attempt["state_present"] is True and attempt["state_changed"] is True
    verify_hash(attempt)
    after = list(await stored(db_session, "timeline_projection_state"))
    assert dict(after[0]) == {**before[0], "schema_version": 0}
    assert list(await stored(db_session, "timeline_projection_points")) == points
    assert request["inventory_json"] == values["inventory_json"]


@pytest.mark.parametrize("present", [True, False])
async def test_existing_invalid_or_missing_state_is_honest_noop(db_session, present):
    people, _, values = await request_values(db_session)
    request = await add(db_session, "source_task_requests", **values)
    if present:
        await projection_state(db_session, version=0)
    else:
        await db_session.execute(sa.text("DELETE FROM timeline_projection_state WHERE id=1"))
    attempt = await add(db_session, "source_task_attempts", **attempt_values(request, people))
    assert attempt["state_present"] is present and attempt["state_changed"] is False


async def test_receipt_and_effect_share_savepoint_rollback(db_session):
    people, _, values = await request_values(db_session)
    request = await add(db_session, "source_task_requests", **values)
    await projection_state(db_session)
    before = list(await stored(db_session, "timeline_projection_state"))
    attempts = list(await stored(db_session, "source_task_attempts"))
    savepoint = await db_session.begin_nested()
    result = await add(db_session, "source_task_attempts", **attempt_values(request, people))
    assert result["state_changed"] is True
    await savepoint.rollback()
    assert list(await stored(db_session, "timeline_projection_state")) == before
    assert list(await stored(db_session, "source_task_attempts")) == attempts


@pytest.mark.parametrize("table", ["source_task_requests", "source_task_attempts"])
@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_task_history_is_immutable(db_session, table, operation):
    people, _, values = await request_values(db_session)
    request = await add(db_session, "source_task_requests", **values)
    await add(db_session, "source_task_attempts", **attempt_values(request, people))
    statement = {"update": f"UPDATE {table} SET id=id", "delete": f"DELETE FROM {table}",
                 "truncate": f"TRUNCATE {table} CASCADE"}[operation]
    before = list(await stored(db_session, table))
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(statement))
    assert list(await stored(db_session, table)) == before


@pytest.mark.parametrize("field,value", [
    ("inventory_sha256", "a" * 64), ("event_sha256", "a" * 64),
    ("source_snapshot_sha256", "b" * 64), ("inventory_version", "source-impact/future"),
    ("action_version", "timeline-full-rebuild/1.0.0"), ("request_key", "space not allowed"),
])
async def test_request_requires_exact_bounded_versioned_bindings(db_session, field, value):
    _, _, values = await request_values(db_session)
    values[field] = value
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "source_task_requests", **values)


async def test_inventory_checksum_does_not_replace_exact_event_envelope(db_session):
    import json

    _, _, values = await request_values(db_session)
    body = json.loads(values["inventory_json"])
    body["event"]["id"] = str(uuid4())
    values.update(inventory_json=canonical(body).decode(), inventory_sha256=digest(body))
    with pytest.raises(DBAPIError, match="exact_inventory_envelope"):
        async with db_session.begin_nested():
            await add(db_session, "source_task_requests", **values)


async def test_request_idempotency_key_cannot_be_reused_with_new_row(db_session):
    _, _, values = await request_values(db_session)
    await add(db_session, "source_task_requests", **values)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "source_task_requests", **values)


@pytest.mark.parametrize("role", ["admin", "reviewer", "member"])
async def test_legacy_admin_or_noncurator_cannot_declare_request_authority(db_session, role):
    people, _, values = await request_values(db_session)
    values["requester_id"] = people[role]
    values["requester_grant_id"] = people["grants"].get(role, people["grants"]["curator"])
    with pytest.raises(DBAPIError, match="explicit_active_curator"):
        async with db_session.begin_nested():
            await add(db_session, "source_task_requests", **values)


@pytest.mark.parametrize("kind", ["paper", "work"])
async def test_new_source_event_stales_request_and_success_but_allows_obsolete_receipt(db_session, kind):
    people, source, values = await request_values(db_session, kind=kind)
    request = await add(db_session, "source_task_requests", **values)
    name, field = ("papers", "status") if kind == "paper" else ("works", "publication_status")
    await db_session.execute(sa.text(f"UPDATE {name} SET {field}='active' WHERE id=:id"), {"id": source})
    with pytest.raises(DBAPIError, match="current_event_required"):
        async with db_session.begin_nested():
            await add(db_session, "source_task_requests", **{**values, "request_key": "stale-" + uuid4().hex})
    with pytest.raises(DBAPIError, match="current_event_required"):
        async with db_session.begin_nested():
            await add(db_session, "source_task_attempts", **attempt_values(request, people))
    receipt = await add(db_session, "source_task_attempts", **attempt_values(
        request, people, status="obsolete", outcome="source_changed"), state_present=True, state_changed=True)
    assert receipt["state_present"] is receipt["state_changed"] is False


async def test_revoked_requester_cannot_execute_but_independent_curator_can_record_block(db_session):
    people, _, values = await request_values(db_session)
    request = await add(db_session, "source_task_requests", **values)
    executor = await actors(db_session)
    await revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
                      reason_code="synthetic_revocation", dry_run=False)
    with pytest.raises(DBAPIError, match="request_authority_unavailable"):
        async with db_session.begin_nested():
            await add(db_session, "source_task_attempts", **attempt_values(request, executor))
    receipt = await add(db_session, "source_task_attempts", **attempt_values(request, executor,
        status="blocked", outcome="request_authority_unavailable"))
    assert not receipt["state_changed"]


@pytest.mark.parametrize("status,outcome", [("succeeded", "timeline_cache_invalidated"),
    ("obsolete", "inventory_changed"), ("blocked", "scope_limit")])
async def test_terminal_attempt_cannot_have_a_successor(db_session, status, outcome):
    people, _, values = await request_values(db_session)
    request = await add(db_session, "source_task_requests", **values)
    prior = await add(db_session, "source_task_attempts", **attempt_values(request, people, status=status, outcome=outcome))
    with pytest.raises(DBAPIError, match="exact_retry_predecessor"):
        async with db_session.begin_nested():
            await add(db_session, "source_task_attempts", **attempt_values(request, people, prior=prior))


async def test_retries_require_exact_head_and_fifth_transient_is_exhausted(db_session):
    people, _, values = await request_values(db_session)
    request = await add(db_session, "source_task_requests", **values)
    prior = None
    for index in range(1, 5):
        prior = await add(db_session, "source_task_attempts", **attempt_values(request, people, prior=prior,
            status="retryable_failure", outcome="database_busy"))
        assert prior["attempt_number"] == index
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "source_task_attempts", **attempt_values(request, people, prior=prior,
                status="retryable_failure", outcome="database_busy"))
    last = await add(db_session, "source_task_attempts", **attempt_values(request, people, prior=prior,
        status="exhausted", outcome="database_busy"))
    assert last["attempt_number"] == 5
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "source_task_attempts", **attempt_values(request, people, prior=last))


@pytest.mark.parametrize("mutation", ["missing_predecessor", "wrong_number", "foreign_predecessor", "early_exhaustion"])
async def test_invalid_retry_chains_rejected(db_session, mutation):
    people, _, values = await request_values(db_session)
    request = await add(db_session, "source_task_requests", **values)
    prior = await add(db_session, "source_task_attempts", **attempt_values(request, people,
        status="retryable_failure", outcome="statement_timeout"))
    next_values = attempt_values(request, people, prior=prior)
    if mutation == "missing_predecessor":
        next_values["predecessor_id"] = None
    elif mutation == "wrong_number":
        next_values["attempt_number"] = 3
    elif mutation == "foreign_predecessor":
        next_values["predecessor_id"] = uuid4()
    else:
        next_values.update(status="exhausted", outcome_code="serialization_failure")
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "source_task_attempts", **next_values)


async def test_read_committed_queue_writer_rejected_but_projection_guard_supported(db_session):
    _, _, values = await request_values(db_session)
    await db_session.commit()
    engine = get_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as ordinary:
            with pytest.raises(DBAPIError, match="requires_serializable"):
                async with ordinary.begin_nested():
                    await add(ordinary, "source_task_requests", **values)
            before = await ordinary.scalar(sa.text("SELECT epoch FROM source_task_epoch WHERE id=1"))
            await ordinary.execute(sa.text("UPDATE timeline_projection_points SET active=false WHERE false"))
            assert await ordinary.scalar(sa.text("SELECT epoch FROM source_task_epoch WHERE id=1")) > before
    finally:
        await engine.dispose()


async def test_stale_repeatable_read_projection_writer_fenced_by_receipt(db_session):
    people, _, values = await request_values(db_session)
    request = await add(db_session, "source_task_requests", **values)
    await projection_state(db_session)
    await db_session.commit()
    engine = get_engine().execution_options(isolation_level="REPEATABLE READ")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as stale:
            await stale.execute(sa.text("SELECT epoch FROM source_task_epoch WHERE id=1"))
            await add(db_session, "source_task_attempts", **attempt_values(request, people))
            await db_session.commit()
            with pytest.raises(DBAPIError, match="serialize"):
                await stale.execute(sa.text("UPDATE timeline_projection_points SET active=false WHERE false"))
    finally:
        await engine.dispose()
