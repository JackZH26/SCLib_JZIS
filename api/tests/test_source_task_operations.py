"""Actual 0058 operator rehearsals and exact durable receipts, disposable only."""
from __future__ import annotations

import asyncio
import copy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, get_engine
from services import research_publication as publication
from services import source_task_operations as service
from services import source_tasks as tasks
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors
from tests.test_source_tasks import prepared

db_session = _serializable_db_session


def enqueue_request(context):
    return {"version": service.VERSION, "operation": "enqueue",
            **{key: value for key, value in context["args"].items() if key != "actor_user_id"}}


def execute_request(receipt, *, key="execute-one", prior=None):
    return {"version": service.VERSION, "operation": "execute", "request_id": receipt["request"]["id"],
        "expected_request_sha256": receipt["request"]["record_sha256"], "execution_key": key,
        "expected_predecessor_id": prior["id"] if prior else None,
        "expected_predecessor_sha256": prior["record_sha256"] if prior else None}


async def admitted(db, actor, request):
    preview = await service.preview_operation(db, actor_user_id=actor, request=request)
    receipt = await service.commit_operation(db, actor_user_id=actor, request=request,
                                             expected_preview_sha256=preview["preview_sha256"])
    return preview, receipt


@pytest.mark.parametrize("operation", ["enqueue", "execute"])
async def test_real_preview_is_stable_and_rolls_back_all_tables(db_session, operation):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    request = enqueue_request(context)
    if operation == "execute":
        _, queued = await admitted(db_session, actor, request)
        request = execute_request(queued)
    before = await state(db_session)
    first = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    second = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    assert first == second and not first["database_mutated"]
    assert first["predicted_status"] == ("queued" if operation == "enqueue" else "succeeded")
    assert await state(db_session) == before
    assert "request" not in first and "attempt" not in first


async def test_real_operation_receipts_preserve_only_bounded_effect(db_session):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    preview, queued = await admitted(db_session, actor, enqueue_request(context))
    assert queued["preview_sha256"] == preview["preview_sha256"]
    assert not queued["committed"] and queued["requires_outer_commit"] and queued["attempt"] is None
    before = await state(db_session)
    preview, result = await admitted(db_session, actor, execute_request(queued))
    assert result["executed_now"] and result["attempt"]["state_changed"]
    assert result["attempt"]["status"] == preview["predicted_status"] == "succeeded"
    after = await state(db_session)
    allowed = {"timeline_projection_state", "source_task_attempts", "source_task_epoch",
               "research_integrity_epoch", "research_publication_epoch", "source_lifecycle_epoch"}
    assert {key: value for key, value in before.items() if key not in allowed} == {
        key: value for key, value in after.items() if key not in allowed}
    assert after["timeline_projection_state"][0] == {**before["timeline_projection_state"][0], "schema_version": 0}
    assert all(value is False for key, value in result["receipt_semantics"].items()
               if key not in {"action_version", "currentness"})


async def test_durable_same_key_recovery_and_replay_outer_rollback(db_session):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    request = enqueue_request(context)
    preview, queued = await admitted(db_session, actor, request)
    await db_session.commit()
    before = await state(db_session)
    replay = await service.commit_operation(db_session, actor_user_id=actor, request=request,
                                             expected_preview_sha256=preview["preview_sha256"])
    assert replay["replayed"] and replay["request"] == queued["request"] and not replay["executed_now"]
    await db_session.rollback()  # Real HTTP adapter must undo replay-only guard epochs.
    assert await state(db_session) == before
    fetched = await service.inspect_by_key(db_session, actor_user_id=actor, request_key=request["request_key"])
    assert fetched == replay
    other = await actors(db_session)
    assert await service.inspect_by_key(db_session, actor_user_id=other["curator"],
                                        request_key=request["request_key"]) is None


async def test_exact_execution_lookup_does_not_substitute_later_attempt_or_other_actor(db_session):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    _, queued = await admitted(db_session, actor, enqueue_request(context))
    first = execute_request(queued, key="failed-once")
    failure = await tasks.record_source_task_failure(db_session, actor_user_id=actor,
        request_id=first["request_id"], expected_request_sha256=first["expected_request_sha256"],
        execution_key=first["execution_key"], outcome_code="statement_timeout", dry_run=False)
    second = execute_request(queued, key="next", prior=failure["attempt"])
    _, success = await admitted(db_session, actor, second)
    recovered = await service.inspect_execution(db_session, actor_user_id=actor,
                                                request_id=first["request_id"], execution_key=first["execution_key"])
    assert recovered["attempt"] == failure["attempt"] and recovered["attempt"] != success["attempt"]
    assert not recovered["executed_now"]
    assert await service.inspect_execution(db_session, actor_user_id=actor,
        request_id=first["request_id"], execution_key="not-recorded") is None
    other = await actors(db_session)
    assert await service.inspect_execution(db_session, actor_user_id=other["curator"],
        request_id=first["request_id"], execution_key=first["execution_key"]) is None
    assert await service.inspect_execution(db_session, actor_user_id=actor,
        request_id=str(uuid4()), execution_key="not-recorded") is None


async def test_advanced_head_rejects_old_preview_and_historical_predecessor_tampering(db_session):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    _, queued = await admitted(db_session, actor, enqueue_request(context))
    request = execute_request(queued)
    preview = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    failure = await tasks.record_source_task_failure(db_session, actor_user_id=actor,
        request_id=request["request_id"], expected_request_sha256=request["expected_request_sha256"],
        execution_key="intervening-failure", outcome_code="database_busy", dry_run=False)
    before = await state(db_session)
    with pytest.raises(service.SourceTaskOperationConflict):
        await service.commit_operation(db_session, actor_user_id=actor, request=request,
                                       expected_preview_sha256=preview["preview_sha256"])
    assert await state(db_session) == before
    request = execute_request(queued, prior=failure["attempt"])
    preview, _ = await admitted(db_session, actor, request)
    wrong = {**request, "expected_predecessor_sha256": "0" * 64}
    with pytest.raises(service.SourceTaskOperationConflict):
        await service.commit_operation(db_session, actor_user_id=actor, request=wrong,
                                       expected_preview_sha256=preview["preview_sha256"])


async def test_new_actor_grant_invalidates_uncommitted_preview_but_allows_historical_recovery(db_session):
    context = await prepared(db_session)
    people, request = context["actors"], enqueue_request(context)
    actor = people["curator"]
    preview = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    await publication.revoke_role(db_session, actor_user_id=people["admin"],
        grant_id=people["grants"]["curator"], reason_code="synthetic_revoke", dry_run=False)
    await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=actor,
        role="curator", reason_code="synthetic_replace", dry_run=False)
    with pytest.raises(service.SourceTaskOperationConflict):
        await service.commit_operation(db_session, actor_user_id=actor, request=request,
                                       expected_preview_sha256=preview["preview_sha256"])
    preview, queued = await admitted(db_session, actor, request)
    await publication.revoke_role(db_session, actor_user_id=people["admin"],
        grant_id=UUID(queued["actor_grant_id"]), reason_code="synthetic_revoke", dry_run=False)
    await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=actor,
        role="curator", reason_code="synthetic_replace", dry_run=False)
    recovered = await service.inspect_by_key(db_session, actor_user_id=actor, request_key=request["request_key"])
    assert recovered["actor_grant_id"] == queued["actor_grant_id"]
    replay = await service.commit_operation(db_session, actor_user_id=actor, request=request,
                                           expected_preview_sha256=preview["preview_sha256"])
    assert replay["replayed"]
    execute = await service.preview_operation(db_session, actor_user_id=actor, request=execute_request(queued))
    assert execute["predicted_status"] == "blocked"
    assert execute["predicted_outcome_code"] == "request_authority_unavailable"


@pytest.mark.parametrize("role", ["admin", "member", "reviewer", "publisher"])
async def test_legacy_flags_and_other_roles_do_not_admit_operation_or_lookup(db_session, role):
    context = await prepared(db_session)
    actor = context["actors"][role]
    with pytest.raises(ResearchAccessDenied):
        await service.preview_operation(db_session, actor_user_id=actor, request=enqueue_request(context))
    with pytest.raises(ResearchAccessDenied):
        await service.inspect_by_key(db_session, actor_user_id=actor, request_key="not-recorded")


@pytest.mark.parametrize("mutation", ["inventory", "source", "token"])
async def test_stale_enqueue_or_preview_tamper_rolls_back_everything(db_session, mutation):
    context = await prepared(db_session)
    actor, request = context["actors"]["curator"], enqueue_request(context)
    preview = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    if mutation == "source":
        await db_session.execute(sa.text("UPDATE papers SET title='synthetic changed' WHERE id=:id"), {"id": context["source"]})
    elif mutation == "inventory":
        from tests.test_source_impact import material
        await material(db_session, source=context["source"])
    before = await state(db_session)
    with pytest.raises(service.SourceTaskOperationConflict):
        await service.commit_operation(db_session, actor_user_id=actor, request=request,
            expected_preview_sha256="0" * 64 if mutation == "token" else preview["preview_sha256"])
    assert await state(db_session) == before


async def test_post_insert_error_rolls_back_preview_and_real_effect(db_session, monkeypatch):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    _, queued = await admitted(db_session, actor, enqueue_request(context))
    request = execute_request(queued)
    preview = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    before, original = await state(db_session), tasks._append
    count = 0
    async def broken(*args, **kwargs):
        nonlocal count
        value = await original(*args, **kwargs)
        count += 1
        if count == 2:  # First insertion is the genuine rollback rehearsal.
            raise RuntimeError("SYNTHETIC_PRIVATE_AFTER_EFFECT")
        return value
    monkeypatch.setattr(tasks, "_append", broken)
    with pytest.raises(RuntimeError):
        await service.commit_operation(db_session, actor_user_id=actor, request=request,
                                       expected_preview_sha256=preview["preview_sha256"])
    assert await state(db_session) == before


async def test_same_key_independent_transaction_has_no_second_durable_request(db_session):
    context = await prepared(db_session)
    actor, request = context["actors"]["curator"], enqueue_request(context)
    preview = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    await db_session.commit()
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            receipt = await service.commit_operation(first, actor_user_id=actor, request=request,
                                                     expected_preview_sha256=preview["preview_sha256"])
            with pytest.raises(sa.exc.DBAPIError):
                await service.commit_operation(second, actor_user_id=actor, request=request,
                                               expected_preview_sha256=preview["preview_sha256"])
            await second.rollback()
            await first.commit()
            replay = await service.commit_operation(second, actor_user_id=actor, request=request,
                                                    expected_preview_sha256=preview["preview_sha256"])
            assert replay["replayed"] and replay["request"]["id"] == receipt["request"]["id"]
            await second.rollback()
        relation = Base.metadata.tables["source_task_requests"]
        assert await db_session.scalar(sa.select(sa.func.count()).select_from(relation).where(
            relation.c.requester_id == actor, relation.c.request_key == request["request_key"])) == 1
    finally:
        await engine.dispose()


async def test_execute_commit_conflicts_if_predicted_outcome_changed_then_records_exact_terminal_preview(db_session):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    _, queued = await admitted(db_session, actor, enqueue_request(context))
    request = execute_request(queued)
    preview = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    await db_session.execute(sa.text("UPDATE papers SET title='synthetic source changed' WHERE id=:id"),
                             {"id": context["source"]})
    before = await state(db_session)
    with pytest.raises(service.SourceTaskOperationConflict):
        await service.commit_operation(db_session, actor_user_id=actor, request=request,
                                       expected_preview_sha256=preview["preview_sha256"])
    assert await state(db_session) == before
    fresh, receipt = await admitted(db_session, actor, request)
    assert fresh["predicted_status"] == receipt["attempt"]["status"] == "obsolete"
    assert not receipt["executed_now"] and not receipt["attempt"]["state_changed"]


async def test_success_replay_after_rebuild_and_source_change_is_only_historical(db_session):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    _, queued = await admitted(db_session, actor, enqueue_request(context))
    request = execute_request(queued)
    preview, succeeded = await admitted(db_session, actor, request)
    await db_session.execute(sa.text("UPDATE timeline_projection_state SET schema_version=6 WHERE id=1"))
    await db_session.execute(sa.text("UPDATE papers SET title='synthetic later source' WHERE id=:id"),
                             {"id": context["source"]})
    await db_session.commit()
    before = await state(db_session)
    replay = await service.commit_operation(db_session, actor_user_id=actor, request=request,
                                           expected_preview_sha256=preview["preview_sha256"])
    assert replay["replayed"] and replay["attempt"] == succeeded["attempt"] and not replay["executed_now"]
    await db_session.rollback()
    assert await state(db_session) == before


async def test_same_enqueue_key_changed_body_and_execution_key_changed_executor_conflict(db_session):
    context = await prepared(db_session)
    actor, request = context["actors"]["curator"], enqueue_request(context)
    _, queued = await admitted(db_session, actor, request)
    before = await state(db_session)
    with pytest.raises(service.SourceTaskOperationConflict):
        await service.preview_operation(db_session, actor_user_id=actor,
            request={**request, "expected_inventory_sha256": "0" * 64})
    assert await state(db_session) == before
    execute = execute_request(queued)
    await admitted(db_session, actor, execute)
    people = await actors(db_session)
    with pytest.raises(service.SourceTaskOperationConflict):
        await service.preview_operation(db_session, actor_user_id=people["curator"], request=execute)


async def test_cancel_after_actual_effect_rolls_back_all_changes(db_session, monkeypatch):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    _, queued = await admitted(db_session, actor, enqueue_request(context))
    request = execute_request(queued)
    preview = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    before, original = await state(db_session), tasks._append
    count = 0
    async def cancelled(*args, **kwargs):
        nonlocal count
        result = await original(*args, **kwargs)
        count += 1
        if count == 2:
            raise asyncio.CancelledError()
        return result
    monkeypatch.setattr(tasks, "_append", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await service.commit_operation(db_session, actor_user_id=actor, request=request,
                                       expected_preview_sha256=preview["preview_sha256"])
    assert await state(db_session) == before


async def test_execute_race_cannot_append_a_second_terminal_attempt(db_session):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    _, queued = await admitted(db_session, actor, enqueue_request(context))
    request = execute_request(queued)
    preview = await service.preview_operation(db_session, actor_user_id=actor, request=request)
    competing = {**request, "execution_key": "competing-key"}
    alternate = await service.preview_operation(db_session, actor_user_id=actor, request=competing)
    await db_session.commit()
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await service.commit_operation(first, actor_user_id=actor, request=request,
                                           expected_preview_sha256=preview["preview_sha256"])
            with pytest.raises(sa.exc.DBAPIError):
                await service.commit_operation(second, actor_user_id=actor, request=competing,
                                               expected_preview_sha256=alternate["preview_sha256"])
            await second.rollback()
            await first.commit()
            with pytest.raises(service.SourceTaskOperationConflict):
                await service.commit_operation(second, actor_user_id=actor, request=competing,
                                               expected_preview_sha256=alternate["preview_sha256"])
            await second.rollback()
        relation = Base.metadata.tables["source_task_attempts"]
        assert await db_session.scalar(sa.select(sa.func.count()).select_from(relation).where(
            relation.c.request_id == UUID(request["request_id"]))) == 1
    finally:
        await engine.dispose()


async def test_direct_optional_hook_requires_historical_exact_head_and_grant(db_session):
    context = await prepared(db_session)
    actor = context["actors"]["curator"]
    _, queued = await admitted(db_session, actor, enqueue_request(context))
    request = execute_request(queued)
    await admitted(db_session, actor, request)
    args = {key: value for key, value in request.items() if key not in {"version", "operation"}}
    replay = await tasks.execute_source_task(db_session, actor_user_id=actor, check_predecessor=True,
                                             dry_run=False, **args)
    assert replay["replayed"]
    with pytest.raises(tasks.SourceTaskError):
        await tasks.execute_source_task(db_session, actor_user_id=actor, check_predecessor=True,
            dry_run=False, **{**args, "expected_predecessor_id": str(uuid4()), "expected_predecessor_sha256": "a" * 64})
    with pytest.raises(ResearchAccessDenied):
        await tasks.execute_source_task(db_session, actor_user_id=actor, check_predecessor=True,
            expected_actor_grant_id=uuid4(), dry_run=False, **args)


def _pure_request():
    return {"version": service.VERSION, "operation": "enqueue", "request_key": "synthetic-request",
        "event_id": str(UUID(int=1)), "expected_event_sha256": "a" * 64, "expected_inventory_sha256": "b" * 64}


@pytest.mark.parametrize("field,value", [("version", None), ("version", True), ("operation", []),
    ("operation", "other"), ("request_key", "bad/key"), ("request_key", "x" * 161), ("request_key", False),
    ("event_id", "00000000000000000000000000000001"), ("event_id", 1),
    ("expected_event_sha256", "A" * 64), ("expected_inventory_sha256", "0" * 63)])
def test_strict_request_fields(field, value):
    request = _pure_request()
    request[field] = value
    with pytest.raises(service.SourceTaskOperationError):
        service.validate_request(request)


@pytest.mark.parametrize("payload", [b'{"version":"a","version":"b"}', b'{"x":NaN}', b'{"x":1e999}',
    b'{"x":1}', b'{"x":"\\ud800"}', b'\xff', b'[]', b'{"x":' + b'[' * 17 + b']' * 17 + b'}',
    b' ' * (service.MAX_BYTES + 1)])
def test_strict_json_bytes(payload):
    with pytest.raises(service.SourceTaskOperationError):
        service.loads(payload)


def test_closed_keys_predecessor_and_commit_envelope():
    request = _pure_request()
    assert service.loads(canonical(request)) == service.validate_request(request)
    for altered in ({**request, "actor_user_id": str(UUID(int=2))}, {key: value for key, value in request.items() if key != "version"}):
        with pytest.raises(service.SourceTaskOperationError):
            service.validate_request(altered)
    execute = {"version": service.VERSION, "operation": "execute", "request_id": str(UUID(int=3)),
        "expected_request_sha256": "c" * 64, "execution_key": "synthetic-execution",
        "expected_predecessor_id": None, "expected_predecessor_sha256": None}
    assert service.validate_request(execute) == execute
    for field in ("expected_predecessor_id", "expected_predecessor_sha256"):
        bad = copy.deepcopy(execute)
        bad[field] = str(UUID(int=4)) if field.endswith("id") else "d" * 64
        with pytest.raises(service.SourceTaskOperationError):
            service.validate_request(bad)
    body = {"request": request, "expected_preview_sha256": "e" * 64}
    assert service.validate_commit(service.loads(canonical(body), max_bytes=service.MAX_COMMIT_BYTES)) == body
    with pytest.raises(service.SourceTaskOperationError):
        service.validate_commit({**body, "dry_run": False})
