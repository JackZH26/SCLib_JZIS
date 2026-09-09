"""Direct-SQL source history invariants on guarded disposable PostgreSQL."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, get_engine
from services.research_release_manifest import canonical, digest
from tests.test_research_freeze import add
from tests.test_research_publication import actors


@pytest_asyncio.fixture(loop_scope="function")
async def review_db():
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    engine = get_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


async def review_values(db):
    people = await actors(db)
    identifier = await source(db, status="retracted")
    event, = await events(db, identifier)
    document = dict(policy_version="source-lifecycle-review/1.0.0", event_id=str(event["id"]),
        event_sha256=event["record_sha256"], source_snapshot_sha256=event["snapshot_sha256"],
        claim_id=None, claim_revision_sha256=None, decision="retain_hold", reason_code="synthetic_review",
        reviewer_id=str(people["reviewer"]), reviewer_grant_id=str(people["grants"]["reviewer"]),
        scientific_acceptance=False, ml_training_approved=False, source_reinstatement=False)
    payload_hash = hashlib.sha256(canonical(document)).hexdigest()
    artifact = await add(db, "evidence_artifacts", kind="review", schema_version="source-lifecycle-review/1.0.0",
        source="synthetic-test", record_sha256=digest(document), bytes_sha256=payload_hash,
        hash_status="verified", access="restricted", metadata={"source_lifecycle_review": document})
    return dict(event_id=event["id"], event_sha256=event["record_sha256"],
        source_snapshot_sha256=event["snapshot_sha256"], decision="retain_hold",
        policy_version="source-lifecycle-review/1.0.0", reason_code="synthetic_review",
        reviewer_id=people["reviewer"], reviewer_grant_id=people["grants"]["reviewer"],
        review_artifact_id=artifact["id"], review_artifact_sha256=artifact["record_sha256"],
        review_bytes_sha256=artifact["bytes_sha256"], request_key="schema-" + uuid4().hex)


async def source(db, kind="paper", status="published"):
    if kind == "paper":
        identifier = "lifecycle-schema:" + uuid4().hex
        await db.execute(sa.text("""INSERT INTO papers(id,source,title,authors,abstract,status,
            citation_count,chunk_count,materials_extracted,quality_flags)
            VALUES (:id,'arxiv','Synthetic lifecycle schema','[]','Synthetic only',:status,0,0,'[]','[]')"""),
                         {"id": identifier, "status": status})
    else:
        identifier = uuid4()
        await db.execute(sa.text("""INSERT INTO works(id,canonical_title,publication_status)
            VALUES (:id,'Synthetic lifecycle schema',:status)"""), {"id": identifier, "status": status})
    return identifier


async def events(db, identifier, kind="paper"):
    return (await db.execute(sa.text(f"SELECT * FROM source_lifecycle_events WHERE {kind}_id=:id ORDER BY revision"),
                             {"id": identifier})).mappings().all()


@pytest.mark.parametrize("kind,status", [("paper", "published"), ("work", "active")])
async def test_unheld_source_has_no_fabricated_baseline(db_session, kind, status):
    identifier = await source(db_session, kind, status)
    assert await events(db_session, identifier, kind) == []


@pytest.mark.parametrize("kind,initial", [("paper", "published"), ("work", "active")])
async def test_raw_status_reset_and_date_correction_preserve_history(db_session, kind, initial):
    identifier = await source(db_session, kind, initial)
    name, status_field, date_field = (("papers", "status", "date_published") if kind == "paper"
                                     else ("works", "publication_status", "available_at"))
    for status in ("retracted", initial):
        await db_session.execute(sa.text(f"UPDATE {name} SET {status_field}=:status WHERE id=:id"),
                                 {"id": identifier, "status": status})
    await db_session.execute(sa.text(f"UPDATE {name} SET {date_field}='2026-09-07' WHERE id=:id"), {"id": identifier})
    before = await events(db_session, identifier, kind)
    assert [row["event_kind"] for row in before] == ["lifecycle_change", "lifecycle_change", "catalogue_revision"]
    assert [row["revision"] for row in before] == [1, 2, 3]
    assert before[0]["predecessor_id"] is None
    for previous, current in zip(before, before[1:]):
        assert current["predecessor_id"] == previous["id"]
        assert current["old_snapshot_sha256"] == previous["snapshot_sha256"]
    await db_session.execute(sa.text(f"UPDATE {name} SET updated_at=clock_timestamp() WHERE id=:id"), {"id": identifier})
    await db_session.execute(sa.text(f"UPDATE {name} SET {status_field}={status_field} WHERE id=:id"), {"id": identifier})
    assert await events(db_session, identifier, kind) == before


@pytest.mark.parametrize("kind,held", [("paper", "disputed"), ("work", "corrected")])
async def test_initial_held_row_is_observed_baseline_not_history(db_session, kind, held):
    identifier = await source(db_session, kind, held)
    row, = await events(db_session, identifier, kind)
    assert row["event_kind"] == "baseline_observed" and row["revision"] == 1
    assert row["prior_status"] is row["old_snapshot_sha256"] is row["predecessor_id"] is None
    assert row["observed_status"] == held
    domain = {str(key): str(value) if hasattr(value, "hex") else value for key, value in row.items()
              if key not in {"created_at", "record_sha256"}}
    expected = hashlib.sha256(json.dumps(domain, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert row["record_sha256"] == expected


@pytest.mark.parametrize("operation", ["update", "delete", "truncate", "source_delete", "source_reidentify"])
async def test_observed_history_cannot_be_mutated_or_source_reused(db_session, operation):
    identifier = await source(db_session, status="retracted")
    row, = await events(db_session, identifier)
    statement = {
        "update": "UPDATE source_lifecycle_events SET observed_status='published' WHERE id=:event_id",
        "delete": "DELETE FROM source_lifecycle_events WHERE id=:event_id",
        "truncate": "TRUNCATE source_lifecycle_events CASCADE",
        "source_delete": "DELETE FROM papers WHERE id=:paper_id",
        "source_reidentify": "UPDATE papers SET id=:new_id WHERE id=:paper_id",
    }[operation]
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(statement), {"event_id": row["id"], "paper_id": identifier,
                                                          "new_id": identifier + "-reused"})
    assert await events(db_session, identifier) == [row]


async def test_direct_event_insertion_cannot_forge_a_negative_observation(db_session):
    identifier = await source(db_session)
    relation = Base.metadata.tables["source_lifecycle_events"]
    with pytest.raises(DBAPIError, match="source_lifecycle_capture_trigger_only"):
        async with db_session.begin_nested():
            await db_session.execute(relation.insert().values(paper_id=identifier, revision=1,
                snapshot_sha256="a" * 64, observed_status="retracted", event_kind="baseline_observed"))
    assert await events(db_session, identifier) == []


async def test_counter_updates_do_not_append_but_raw_content_does(db_session):
    identifier = await source(db_session, status="corrected")
    baseline = await events(db_session, identifier)
    await db_session.execute(sa.text("""UPDATE papers SET citation_count=1,chunk_count=2,
        indexed_at=clock_timestamp(),paper_geo=jsonb_build_object('synthetic',true) WHERE id=:id"""), {"id": identifier})
    assert await events(db_session, identifier) == baseline
    await db_session.execute(sa.text("UPDATE papers SET abstract='Revised synthetic content' WHERE id=:id"), {"id": identifier})
    assert len(await events(db_session, identifier)) == 2


async def test_review_exact_artifact_and_history_are_guarded(review_db):
    values = await review_values(review_db)
    row = await add(review_db, "source_lifecycle_reviews", **values)
    assert row["decision"] == "retain_hold"
    with pytest.raises(DBAPIError, match="source_lifecycle_review_artifact_immutable"):
        async with review_db.begin_nested():
            await review_db.execute(sa.text("UPDATE evidence_artifacts SET source='changed' WHERE id=:id"),
                                    {"id": values["review_artifact_id"]})
    with pytest.raises(DBAPIError, match="append-only"):
        async with review_db.begin_nested():
            await review_db.execute(sa.text("DELETE FROM source_lifecycle_reviews WHERE id=:id"), {"id": row["id"]})


async def test_stale_repeatable_read_artifact_writer_is_fenced_by_review(review_db):
    values = await review_values(review_db)
    await review_db.commit()
    engine = get_engine().execution_options(isolation_level="REPEATABLE READ")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as stale:
            await stale.execute(sa.text("SELECT epoch FROM research_integrity_epoch WHERE id=1"))
            await add(review_db, "source_lifecycle_reviews", **values)
            await review_db.commit()
            with pytest.raises(DBAPIError, match="serialize"):
                await stale.execute(sa.text("UPDATE evidence_artifacts SET source='stale-change' WHERE id=:id"),
                                    {"id": values["review_artifact_id"]})
            await stale.rollback()
    finally:
        await engine.dispose()


async def test_stale_repeatable_read_source_writer_is_epoch_fenced(review_db):
    first = await source(review_db, status="retracted")
    second = await source(review_db, status="corrected")
    await review_db.commit()
    engine = get_engine().execution_options(isolation_level="REPEATABLE READ")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as stale:
            await stale.execute(sa.text("SELECT epoch FROM source_lifecycle_epoch WHERE id=1"))
            await review_db.execute(sa.text("UPDATE papers SET abstract='New first observation' WHERE id=:id"), {"id": first})
            await review_db.commit()
            with pytest.raises(DBAPIError, match="serialize"):
                # Different source row: failure is the epoch fence, not merely
                # PostgreSQL's same-row update conflict.
                await stale.execute(sa.text("UPDATE papers SET abstract='Stale second observation' WHERE id=:id"), {"id": second})
            await stale.rollback()
    finally:
        await engine.dispose()
    assert len(await events(review_db, first)) == 2
    assert len(await events(review_db, second)) == 1


async def test_source_contention_is_nonblocking_and_retry_does_not_fork(review_db):
    first = await source(review_db, status="retracted")
    second = await source(review_db, status="corrected")
    await review_db.commit()
    engine = get_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as contender:
            await review_db.execute(sa.text("UPDATE papers SET abstract='Held first writer' WHERE id=:id"), {"id": first})
            # Schema 0067 guards catalogue writes with the shared integrity
            # fence before the source-lifecycle fence. The higher-order guard
            # must reject promptly; do not bypass it merely to reach 0056.
            with pytest.raises(DBAPIError, match="research_integrity_busy_retry_transaction") as rejected:
                await contender.execute(sa.text("UPDATE papers SET abstract='Second writer' WHERE id=:id"), {"id": second})
            assert rejected.value.orig.sqlstate == "55P03"
            await contender.rollback()
            await review_db.commit()
            await contender.execute(sa.text("UPDATE papers SET abstract='Second writer' WHERE id=:id"), {"id": second})
            await contender.commit()
    finally:
        await engine.dispose()
    assert len(await events(review_db, first)) == len(await events(review_db, second)) == 2
