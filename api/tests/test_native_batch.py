"""Native batch/lease replay on freshly owned synthetic services only."""
from dataclasses import replace
import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from tests.test_native_publisher import bridge as bridge, prepared, logical
from tests.test_index_generations import db_session as db_session
from tests.test_research_freeze import state
from tests.test_retrieval_activation import prepared_build, accepted, activation
from native_publisher import producer, batch
from models.db import get_session_factory
from services import retrieval_activation

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get("SCLIB_PGVECTOR_RUNTIME_TEST") != "1",
    reason="Requires fresh owned PostgreSQL/vector services")]


async def enqueue(db, tmp_path, index):
    paper, chunks, inputs = prepared(tmp_path)
    result = await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path,
        inputs=inputs, logical_index=index, dry_run=False)
    return paper, result


async def plan_for(db, base, jobs, *, dry_run=False):
    return await batch.claim_and_plan(db, batch_id=str(uuid4()), logical_index=base["logical_index"],
        base_content_id=base["content_id"], job_ids=[j["job"]["job_id"] for j in jobs],
        worker_id="synthetic-batch-worker", dry_run=dry_run)


async def test_claim_plan_preview_roundtrip_and_durable_partition_restart(bridge, db_session, tmp_path):
    base = await prepared_build(db_session)
    await db_session.commit()
    _, job = await enqueue(db_session, tmp_path, base["logical_index"])
    before = await state(db_session)
    await plan_for(db_session, base, [job], dry_run=True)
    assert await state(db_session) == before
    plan = await plan_for(db_session, base, [job])
    assert batch.BatchPlan.from_dict(plan.to_dict()) == plan
    await db_session.commit()
    def crash_after_commit(progress):
        raise RuntimeError("Synthetic interruption after committed partition")
    with pytest.raises(RuntimeError, match="committed partition"):
        await batch.materialize_content(plan, session_factory=get_session_factory(), progress=crash_after_commit)
    assert await db_session.scalar(sa.text("SELECT count(*) FROM retrieval_content_partitions_v2 WHERE content_id=CAST(:id AS uuid)"),
        {"id": plan.content_id}) == 1
    result = await batch.materialize_content(plan, session_factory=get_session_factory())
    assert result["members"] == 2 and result["activated"] is False
    retained = await state(db_session)
    assert await batch.materialize_content(plan, session_factory=get_session_factory()) == result
    assert await state(db_session) == retained


async def test_retry_reclaims_same_content_without_repeating_completed_partitions(bridge, db_session, tmp_path):
    base = await prepared_build(db_session)
    await db_session.commit()
    _, job = await enqueue(db_session, tmp_path, base["logical_index"])
    first = await plan_for(db_session, base, [job])
    await db_session.commit()
    await batch.materialize_content(first, session_factory=get_session_factory())
    await batch.retry_batch(db_session, first, error_code="build_failed", dry_run=False)
    await db_session.commit()
    with pytest.raises(batch.NativeBatchError, match="expired, finished"):
        await batch.verify_plan(db_session, first)
    second = await plan_for(db_session, base, [job])
    assert first.content_id == second.content_id and first.jobs[0].claim_id != second.jobs[0].claim_id
    await db_session.commit()
    result = await batch.materialize_content(second, session_factory=get_session_factory())
    assert result["members"] == 2


async def test_newest_selection_and_obsolete_plan_stop_before_work(bridge, db_session, tmp_path):
    base = await prepared_build(db_session)
    await db_session.commit()
    paper, first = await enqueue(db_session, tmp_path, base["logical_index"])
    plan = await plan_for(db_session, base, [first])
    await db_session.commit()
    revised, chunks, inputs = prepared(tmp_path, paper=paper, text="Synthetic revised native batch abstract.")
    second = await producer.publish_prepared(revised, chunks, [], archive_root=tmp_path,
        inputs=inputs, logical_index=base["logical_index"], dry_run=False)
    selected = await batch.latest_pending_jobs(db_session, logical_index=base["logical_index"])
    assert selected == [second["job"]["job_id"]]
    with pytest.raises(batch.NativeBatchError, match="superseded"):
        await batch.verify_plan(db_session, plan)
    with pytest.raises(batch.NativeBatchError, match="latest publication"):
        await plan_for(db_session, base, [first])


@pytest.mark.parametrize("field", ["base_record_sha256", "content_record_sha256", "publication_id", "claim_sha256"])
async def test_forged_plan_cannot_authorize_materialization(bridge, db_session, tmp_path, field):
    base = await prepared_build(db_session)
    await db_session.commit()
    _, job = await enqueue(db_session, tmp_path, base["logical_index"])
    plan = await plan_for(db_session, base, [job])
    if field in {"publication_id", "claim_sha256"}:
        forged = replace(plan, jobs=(replace(plan.jobs[0], **{field: str(uuid4()) if field == "publication_id" else "f" * 64}),))
    else:
        forged = replace(plan, **{field: "f" * 64})
    before = await state(db_session)
    with pytest.raises(batch.NativeBatchError):
        await batch.verify_plan(db_session, forged)
    assert await state(db_session) == before


async def test_finish_observes_only_real_complete_active_batch(bridge, db_session, tmp_path):
    base = await prepared_build(db_session)
    initial = await retrieval_activation.activate_backend(db_session,
        **activation(base, await accepted(db_session, base)), dry_run=False)
    await db_session.commit()
    _, first = await enqueue(db_session, tmp_path, base["logical_index"])
    _, second = await enqueue(db_session, tmp_path, base["logical_index"])
    plan = await plan_for(db_session, base, [first, second])
    await db_session.commit()
    with pytest.raises(DBAPIError, match="actual_active_complete"):
        await batch.finish_batch(db_session, plan, activation_event_id=initial["activation_event_id"], dry_run=False)
    await batch.materialize_content(plan, session_factory=get_session_factory())
    built = await prepared_build(db_session, content_id=plan.content_id, logical_index=base["logical_index"])
    event = await retrieval_activation.activate_backend(db_session,
        **activation(built, await accepted(db_session, built), predecessor=initial["activation_event_id"], old=False), dry_run=False)
    result = await batch.finish_batch(db_session, plan, activation_event_id=event["activation_event_id"], dry_run=False)
    retained = await state(db_session)
    assert len(result["results"]) == 2 and result["activation_performed"] is False
    assert await batch.finish_batch(db_session, plan, activation_event_id=event["activation_event_id"], dry_run=False) == result
    assert await state(db_session) == retained


async def test_projection_worker_copies_real_bytes_and_never_activates(bridge, db_session, tmp_path):
    base = await prepared_build(db_session)
    await db_session.commit()
    _, job = await enqueue(db_session, tmp_path, base["logical_index"])
    plan = await plan_for(db_session, base, [job])
    await db_session.commit()
    await batch.materialize_content(plan, session_factory=get_session_factory())
    # These are explicitly synthetic artifact declarations, not signature proof.
    arguments = dict(build_id=str(uuid4()), image_digest="sha256:" + "d" * 64,
        implementation_revision="e" * 40, session_factory=get_session_factory())
    for phase in ("projection", "copy-vectors", "small-graph"):
        first = await batch.prepare_projection(plan, phase=phase, **arguments)
        again = await batch.prepare_projection(plan, phase=phase, **arguments)
        assert first["activation_performed"] is again["quality_acceptance_created"] is False
    validated = await batch.prepare_projection(plan, phase="small-validate", validation_id=str(uuid4()), **arguments)
    assert validated["result"]["outcome"] == "validated"
    assert validated["result"]["source_member_count"] == validated["result"]["projection_member_count"] == 2
    assert validated["result"]["missing_count"] == validated["result"]["extra_count"] == validated["result"]["mismatch_count"] == 0
    assert await db_session.scalar(sa.text("SELECT count(*) FROM retrieval_activation_events_v2 WHERE logical_index=:index"),
        {"index": base["logical_index"]}) == 0


async def test_supersession_retains_actual_successor_without_touching_leased_work(bridge, db_session, tmp_path):
    base = await prepared_build(db_session)
    await db_session.commit()
    paper, first = await enqueue(db_session, tmp_path, base["logical_index"])
    plan = await plan_for(db_session, base, [first])
    await db_session.commit()
    revised, chunks, inputs = prepared(tmp_path, paper=paper, text="Synthetic later batch source.")
    second = await producer.publish_prepared(revised, chunks, [], archive_root=tmp_path,
        inputs=inputs, logical_index=base["logical_index"], dry_run=False)
    assert (await batch.supersede_pending(db_session, logical_index=base["logical_index"],
        worker_id="synthetic-superseder", dry_run=False))["results"] == []
    await batch.retry_batch(db_session, plan, dry_run=False)
    before = await state(db_session)
    preview = await batch.supersede_pending(db_session, logical_index=base["logical_index"], worker_id="synthetic-superseder")
    assert len(preview["results"]) == 1 and await state(db_session) == before
    applied = await batch.supersede_pending(db_session, logical_index=base["logical_index"], worker_id="synthetic-superseder", dry_run=False)
    assert len(applied["results"]) == 1 and applied["results"][0]["outcome"] == "superseded"
    assert await batch.latest_pending_jobs(db_session, logical_index=base["logical_index"]) == [second["job"]["job_id"]]


async def test_cli_claim_plan_is_private_and_preexisting_file_blocks_commit(bridge, db_session, tmp_path, monkeypatch):
    from native_publisher import batch_cli
    from types import SimpleNamespace
    monkeypatch.setattr(batch_cli, "get_settings", lambda: SimpleNamespace(retrieval_backend="pgvector"))
    base = await prepared_build(db_session)
    await db_session.commit()
    _, job = await enqueue(db_session, tmp_path, base["logical_index"])
    path = tmp_path / "plan.json"
    args = SimpleNamespace(phase="claim", logical_index=base["logical_index"], job_id=[job["job"]["job_id"]],
        limit=100, base_content_id=base["content_id"], worker_id="synthetic-cli", batch_id=None,
        lease_seconds=7200, plan_out=str(path), apply=False)
    before = await state(db_session)
    assert (await batch_cli.execute(args))["status"] == "preview_rolled_back"
    assert not path.exists() and await state(db_session) == before
    path.write_text("existing synthetic journal")
    args.apply = True
    with pytest.raises(FileExistsError):
        await batch_cli.execute(args)
    assert path.read_text() == "existing synthetic journal" and await state(db_session) == before
    path.unlink()  # Only this fresh synthetic fixture is removed.
    result = await batch_cli.execute(args)
    assert result["committed"] and path.stat().st_mode & 0o777 == 0o600
    plan = batch_cli.read_plan(path)
    await batch.verify_plan(db_session, plan)
