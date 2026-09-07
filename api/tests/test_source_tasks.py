"""Real immutable source tasks on guarded disposable PostgreSQL only."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, TimelineProjectionState, get_engine
from services import research_publication as publication
from services import source_tasks as service
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical
from services.source_impact import inspect_source_impact
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors
from tests.test_source_impact import material, observation

db_session = _serializable_db_session


async def prepared(db, *, kind="paper", with_state=True):
    people = await actors(db)
    source, args = await observation(db, kind=kind)
    if kind == "paper":
        await material(db, source=source)
    if with_state:
        await db.execute(sa.text("""INSERT INTO timeline_projection_state
            (id,schema_version,source_year,source_watermark,refreshed_at) VALUES(1,6,2026,now(),now())
            ON CONFLICT(id) DO UPDATE SET schema_version=6"""))
    else:
        await db.execute(sa.text("DELETE FROM timeline_projection_state WHERE id=1"))
    report = await inspect_source_impact(db, **args)
    return {"actors": people, "source": source, "report": report, "args": {
        "actor_user_id": people["curator"], **args, "expected_inventory_sha256": report["inventory_sha256"],
        "request_key": "synthetic-" + uuid4().hex}}


def execution(context, request, **extra):
    return {"actor_user_id": context["actors"]["curator"], "request_id": request["request"]["id"],
            "expected_request_sha256": request["request"]["record_sha256"],
            "execution_key": "synthetic-execution", **extra}


@pytest.mark.parametrize("kind", ["paper", "work"])
async def test_enqueue_default_dry_run_actual_bytes_and_exact_replay(db_session, kind):
    context = await prepared(db_session, kind=kind)
    before = await state(db_session)
    preview = await service.enqueue_source_task(db_session, **context["args"])
    assert preview["dry_run"] and not preview["committed"] and not preview["requires_outer_commit"]
    assert await state(db_session) == before
    receipt = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    assert receipt["requires_outer_commit"] and not receipt["replayed"]
    stored = await service._request(db_session, UUID(receipt["request"]["id"]))
    body = {key: value for key, value in context["report"].items() if key not in {"observation", "inventory_sha256"}}
    assert stored["inventory_json"].encode() == canonical(body)
    replay = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    assert replay["replayed"] and replay["request"] == receipt["request"]
    assert (await service.inspect_source_task(db_session, stored["id"]))["stored_state"] == "queued"
    for field in ("expected_inventory_sha256", "expected_event_sha256"):
        with pytest.raises(service.SourceTaskError, match="Idempotency"):
            await service.enqueue_source_task(db_session, **{**context["args"], field: "0" * 64}, dry_run=False)


@pytest.mark.parametrize("with_state", [False, True])
async def test_success_atomically_invalidates_only_existing_readiness_and_rehearses(db_session, with_state):
    context = await prepared(db_session, with_state=with_state)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    before = await state(db_session)
    args = execution(context, request)
    dry = await service.execute_source_task(db_session, **args)
    assert dry["attempt"]["status"] == "succeeded" and dry["executed_now"] is False
    assert await state(db_session) == before
    loaded = await db_session.get(TimelineProjectionState, 1)
    receipt = await service.execute_source_task(db_session, **args, dry_run=False)
    assert receipt["attempt"]["state_present"] is with_state
    assert receipt["attempt"]["state_changed"] is with_state
    assert receipt["executed_now"] and receipt["committed"] is False
    if loaded is not None:
        await db_session.refresh(loaded)
        assert loaded.schema_version == 0
    after = await state(db_session)
    if with_state:
        old, new = before["timeline_projection_state"][0], after["timeline_projection_state"][0]
        assert new == {**old, "schema_version": 0}
    else:
        assert not after["timeline_projection_state"]
    allowed = {"timeline_projection_state", "source_task_attempts", "source_task_epoch",
               "research_integrity_epoch", "research_publication_epoch", "source_lifecycle_epoch"}
    assert {name: rows for name, rows in before.items() if name not in allowed} == {
        name: rows for name, rows in after.items() if name not in allowed}
    semantics = receipt["receipt_semantics"]
    for key in ("timeline_rebuilt", "propagation_complete", "scientific_acceptance",
                "ml_training_approved", "source_reinstatement", "external_cache_invalidated"):
        assert semantics[key] is False


async def test_historical_success_replay_does_not_invalidate_later_rebuild(db_session):
    context = await prepared(db_session)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    args = execution(context, request)
    first = await service.execute_source_task(db_session, **args, dry_run=False)
    await db_session.execute(sa.text("UPDATE timeline_projection_state SET schema_version=6 WHERE id=1"))
    await db_session.execute(sa.text("UPDATE papers SET title='later source version' WHERE id=:id"), {"id": context["source"]})
    replay = await service.execute_source_task(db_session, **args, dry_run=False)
    assert replay["attempt"] == first["attempt"] and replay["replayed"] and not replay["executed_now"]
    assert (await db_session.execute(sa.text("SELECT schema_version FROM timeline_projection_state WHERE id=1"))).scalar_one() == 6
    with pytest.raises(service.SourceTaskError, match="terminal"):
        await service.execute_source_task(db_session, **{**args, "execution_key": "second"}, dry_run=False)
    replay_request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    assert replay_request["replayed"]


@pytest.mark.parametrize("change,code", [("source", "source_changed"), ("graph", "inventory_changed")])
async def test_stale_request_is_obsolete_and_never_changes_cache(db_session, change, code):
    context = await prepared(db_session)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    if change == "source":
        await db_session.execute(sa.text("UPDATE papers SET status='published' WHERE id=:id"), {"id": context["source"]})
    else:
        await material(db_session, source=context["source"])
    receipt = await service.execute_source_task(db_session, **execution(context, request), dry_run=False)
    assert receipt["attempt"]["status"] == "obsolete" and receipt["attempt"]["outcome_code"] == code
    assert not receipt["attempt"]["state_present"] and not receipt["executed_now"]
    assert (await db_session.execute(sa.text("SELECT schema_version FROM timeline_projection_state WHERE id=1"))).scalar_one() == 6


async def test_changed_inventory_cannot_be_enqueued_under_old_preview(db_session):
    context = await prepared(db_session)
    await material(db_session, source=context["source"])
    before = await state(db_session)
    with pytest.raises(service.SourceTaskError, match="inventory changed"):
        await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("role", ["admin", "member", "reviewer", "publisher"])
async def test_only_explicit_curator_can_request_or_execute(db_session, role):
    context = await prepared(db_session)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    with pytest.raises(ResearchAccessDenied):
        await service.enqueue_source_task(db_session, **{**context["args"], "actor_user_id": context["actors"][role]}, dry_run=False)
    with pytest.raises(ResearchAccessDenied):
        await service.execute_source_task(db_session, **execution(context, request, actor_user_id=context["actors"][role]), dry_run=False)


async def test_revoked_original_grant_blocks_even_with_new_valid_executor(db_session):
    context = await prepared(db_session)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    second = await actors(db_session)
    await publication.revoke_role(db_session, actor_user_id=context["actors"]["admin"],
        grant_id=context["actors"]["grants"]["curator"], reason_code="synthetic_revoke", dry_run=False)
    receipt = await service.execute_source_task(db_session, **execution(context, request, actor_user_id=second["curator"]), dry_run=False)
    assert receipt["attempt"]["status"] == "blocked"
    assert receipt["attempt"]["outcome_code"] == "request_authority_unavailable"


@pytest.mark.parametrize("error,code", [(service.SourceImpactError, "inventory_unavailable"),
                                       (service.SourceImpactLimitError, "scope_limit")])
async def test_incomplete_inspection_is_blocked_not_empty_success(db_session, monkeypatch, error, code):
    context = await prepared(db_session)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    async def broken(*_args, **_kwargs):
        raise error("PRIVATE_DIAGNOSTIC")
    monkeypatch.setattr(service, "inspect_source_impact", broken)
    result = await service.execute_source_task(db_session, **execution(context, request), dry_run=False)
    assert result["attempt"]["status"] == "blocked" and result["attempt"]["outcome_code"] == code
    assert b"PRIVATE_DIAGNOSTIC" not in canonical(result)


async def test_failure_reports_exact_chain_bounded_retry_and_terminal_exhaustion(db_session):
    context = await prepared(db_session)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    prior = None
    for number in range(1, 6):
        args = {**execution(context, request, execution_key=f"retry-{number}"), "outcome_code": "database_busy",
            "expected_predecessor_id": prior["id"] if prior else None,
            "expected_predecessor_sha256": prior["record_sha256"] if prior else None}
        before = await state(db_session)
        await service.record_source_task_failure(db_session, **args)
        assert await state(db_session) == before
        result = await service.record_source_task_failure(db_session, **args, dry_run=False)
        replay = await service.record_source_task_failure(db_session, **args, dry_run=False)
        assert replay["replayed"] and replay["attempt"] == result["attempt"]
        prior = result["attempt"]
        assert prior["attempt_number"] == number
        assert prior["status"] == ("exhausted" if number == 5 else "retryable_failure")
        assert not prior["state_changed"]
    with pytest.raises(service.SourceTaskError, match="terminal"):
        await service.execute_source_task(db_session, **execution(context, request, execution_key="retry-6"), dry_run=False)
    history = await service.inspect_source_task(db_session, request["request"]["id"])
    assert len(history["attempts"]) == 5 and history["stored_state"] == "exhausted"
    assert history["retry_scheduled"] is False


async def test_failure_then_success_and_exact_failure_predecessor(db_session):
    context = await prepared(db_session)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    args = execution(context, request, execution_key="failed")
    failure = await service.record_source_task_failure(db_session, **args, outcome_code="statement_timeout", dry_run=False)
    with pytest.raises(service.SourceTaskError, match="predecessor"):
        await service.record_source_task_failure(db_session, **{**args, "execution_key": "wrong"},
            outcome_code="statement_timeout", dry_run=False)
    with pytest.raises(service.SourceTaskError, match="allowlisted"):
        await service.record_source_task_failure(db_session, **args, outcome_code="PRIVATE_DATABASE_URL", dry_run=False)
    with pytest.raises(service.SourceTaskError, match="different failure"):
        await service.record_source_task_failure(db_session, **args, outcome_code="database_busy", dry_run=False)
    success = await service.execute_source_task(db_session, **execution(context, request, execution_key="next"), dry_run=False)
    assert success["attempt"]["attempt_number"] == 2
    assert success["attempt"]["predecessor_id"] == failure["attempt"]["id"]
    assert success["attempt"]["status"] == "succeeded"
    historical = await service.execute_source_task(db_session, **args, dry_run=False)
    assert historical["replayed"] and not historical["executed_now"]


async def test_post_effect_failure_rolls_back_invalidation_and_attempt(db_session, monkeypatch):
    context = await prepared(db_session)
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    before = await state(db_session)
    original = service._append
    async def broken(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic runner crash after effect")
    monkeypatch.setattr(service, "_append", broken)
    with pytest.raises(RuntimeError):
        await service.execute_source_task(db_session, **execution(context, request), dry_run=False)
    assert await state(db_session) == before


async def test_no_outer_commit_read_committed_rejected_and_timeout_restored(db_session):
    context = await prepared(db_session)
    before_timeout = (await db_session.execute(sa.text("SHOW statement_timeout"))).scalar_one()
    request = await service.enqueue_source_task(db_session, **context["args"], dry_run=False)
    assert (await db_session.execute(sa.text("SHOW statement_timeout"))).scalar_one() == before_timeout
    engine = get_engine().execution_options(isolation_level="READ COMMITTED")
    try:
        async with AsyncSession(engine) as ordinary:
            with pytest.raises(service.SourceTaskError, match="SERIALIZABLE"):
                await service.execute_source_task(ordinary, **execution(context, request), dry_run=False)
    finally:
        await engine.dispose()
    await db_session.rollback()
    table = Base.metadata.tables["source_task_requests"]
    assert (await db_session.execute(sa.select(table.c.id).where(table.c.id == UUID(request["request"]["id"])))).first() is None


@pytest.mark.parametrize("key", ["", "x" * 161, "\n", "https://secret/?token=x", None, 1])
async def test_unbounded_or_unsafe_keys_rejected(db_session, key):
    context = await prepared(db_session)
    with pytest.raises(service.SourceTaskError, match="idempotency"):
        await service.enqueue_source_task(db_session, **{**context["args"], "request_key": key}, dry_run=False)
