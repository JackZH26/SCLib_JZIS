"""Guarded migration integration test, not a production migration entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from schema_rehearsal_report import (
    Recorder,
    ReportDestination,
    ReportError,
    SafeParser,
    sha,
)
from test_safety import validate_test_environment, verify_postgres_identity
from migration_legacy_corpus import TABLES as _LEGACY_CORPUS_TABLES

_RAG_EVIDENCE_TABLES = ("rag_extraction_revisions", "rag_evidence_revisions", "chunk_evidence_current")
_EMBEDDING_RECEIPT_TABLE = "embedding_completion_receipts"
_INDEX_GENERATION_TABLES = ("index_generation_epoch", "index_generations", "index_generation_members",
                           "index_generation_validations", "index_activation_events", "index_active_pointer")
_DISTRIBUTION_TABLES = ("research_distribution_epoch", "research_distribution_packages",
                        "research_distribution_dependencies", "research_distribution_permissions",
                        "research_distribution_reviews", "research_distribution_actions")
_ML_FEATURE_BINDING_TABLE = "ml_feature_source_bindings"
_SCIENTIFIC_IMPORT_TABLES = ("scientific_import_packages", "scientific_import_attempts", "scientific_import_blobs",
                             "scientific_import_files", "scientific_import_outcomes")
_ADJUDICATION_TABLES = ("scientific_result_subjects", "scientific_adjudication_requests", "scientific_result_decisions")
_ANSWER_EVIDENCE_TABLE = "answer_evidence_receipts"
_DISCOVERY_PROJECTION_TABLES = ("discovery_projection_packages", "discovery_projection_reviews", "discovery_projection_actions")
_ML_USE_ROLE_TABLE = "ml_use_role_decisions"
_ML_SUBMISSION_TABLES = ("ml_use_submissions", "ml_use_private_inputs", "ml_use_input_purges")
_ML_RIGHTS_TABLE = "ml_use_rights_decisions"
_ML_RUN_EVIDENCE_TABLES = ("ml_run_review_evidence", "ml_run_review_evidence_purges")
_ML_RUN_TABLES = ("ml_use_run_plans", "ml_use_run_decisions", *_ML_RUN_EVIDENCE_TABLES)
_ML_PILOT_TABLES = ("ml_pilot_registrations", "ml_pilot_participants", "ml_pilot_participation_decisions",
                    "ml_pilot_review_attestations")
_RESULT_PASSAGE_TABLE = "scientific_result_passage_links"


def _assert_empty_ml_runs(connection):
    from sqlalchemy import text

    for name in (*_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES):
        # 0081 is derived from already-retained 0062 members, not new history.
        if name == "index_generation_search":
            continue
        assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0


def _assert_empty_ml_use_roles(connection):
    from sqlalchemy import text

    assert connection.execute(text(f"SELECT count(*) FROM public.{_ML_USE_ROLE_TABLE}")).scalar_one() == 0
    _assert_empty_ml_submissions(connection)


def _assert_empty_ml_submissions(connection):
    from sqlalchemy import text

    _assert_empty_ml_runs(connection)
    assert connection.execute(text(f"SELECT count(*) FROM public.{_ML_RIGHTS_TABLE}")).scalar_one() == 0
    for name in _ML_SUBMISSION_TABLES:
        assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0


def _assert_empty_discovery_projections(connection):
    from sqlalchemy import text

    _assert_empty_ml_use_roles(connection)
    for name in _DISCOVERY_PROJECTION_TABLES:
        assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0


def _pre_answer_evidence_rows(connection, name):
    """Only the new nullable marker is absent at pre0068 heads; no old field is ignored."""
    from sqlalchemy import text

    projection = "to_jsonb(item)-'evidence_receipt_version'" if name == "ask_history" else "to_jsonb(item)"
    return connection.execute(text(f"SELECT {projection} FROM public.{name} item ORDER BY ({projection})::text")).scalars().all()


def _assert_empty_answer_evidence(connection):
    from sqlalchemy import text

    _assert_empty_discovery_projections(connection)
    assert connection.execute(text("SELECT count(*) FROM public.answer_evidence_receipts")).scalar_one() == 0
    assert connection.execute(text("SELECT count(*) FROM public.ask_history WHERE evidence_receipt_version IS NOT NULL")).scalar_one() == 0


def _report_signature(connection, check, *, release_id=None):
    """Only hashes/counts leave this guarded synthetic SQL measurement."""
    from sqlalchemy import text

    queries = {
        "seeded_legacy_materials": """SELECT id,records,has_competing_order,pairing_symmetry,is_unconventional,disputed
            FROM public.materials WHERE id IN ('mat:semantics-legacy','mat:semantics-missing')""",
        "seeded_source_revision": """SELECT * FROM public.source_revisions
            WHERE id='2a6a3c2e-bf22-4862-8a77-dc80b89d2779'""",
        "frozen_release_and_pins": """SELECT 'research_releases' AS table_name,to_jsonb(r) AS row FROM public.research_releases r WHERE id=CAST(:release_id AS uuid)
            UNION ALL SELECT 'research_release_pins',to_jsonb(p) FROM public.research_release_pins p WHERE release_id=CAST(:release_id AS uuid)""",
    }
    if check not in queries:
        raise ReportError("unknown_retention_measurement")
    return tuple(connection.execute(text("SELECT count(*),encode(digest(coalesce(jsonb_agg(to_jsonb(item) ORDER BY to_jsonb(item)::text)::text,'[]'),'sha256'),'hex') FROM (" + queries[check] + ") item"),
                                    {"release_id": release_id}).one())


def _observed(recorder, code):
    if recorder is not None:
        recorder.outcome(code)


def _assert_empty_scientific_imports(connection):
    from sqlalchemy import text

    for name in _SCIENTIFIC_IMPORT_TABLES:
        assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0
    _assert_empty_adjudications(connection)


def _assert_empty_adjudications(connection):
    from sqlalchemy import text

    for name in _ADJUDICATION_TABLES:
        assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0
    _assert_empty_answer_evidence(connection)


def _assert_empty_ml_feature_bindings(connection):
    from sqlalchemy import text

    assert connection.execute(text("SELECT count(*) FROM public.ml_feature_source_bindings")).scalar_one() == 0
    _assert_empty_scientific_imports(connection)


def _assert_empty_distributions(connection):
    from sqlalchemy import text

    for name in _DISTRIBUTION_TABLES[1:]:
        assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0
    assert connection.execute(text("SELECT epoch FROM public.research_distribution_epoch WHERE id=1")).scalar_one() == 0
    _assert_empty_ml_feature_bindings(connection)


def _assert_empty_index_generations(connection):
    from sqlalchemy import text

    for name in _INDEX_GENERATION_TABLES[1:]:
        assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0
    assert connection.execute(text("SELECT epoch FROM public.index_generation_epoch WHERE id=1")).scalar_one() == 0
    _assert_empty_distributions(connection)


def _assert_empty_embedding_receipts(connection):
    from sqlalchemy import text

    assert connection.execute(text("SELECT count(*) FROM public.embedding_completion_receipts")).scalar_one() == 0
    _assert_empty_index_generations(connection)


def _assert_empty_rag_evidence(connection):
    from sqlalchemy import text

    for name in _RAG_EVIDENCE_TABLES:
        assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0
    _assert_empty_embedding_receipts(connection)


def _assert_source_impact_indexes(connection, *, present=True):
    """Verify real migrated reverse indexes, not merely ORM declarations."""
    from models.source_impact_indexes_v1 import INDEX_SPECS
    from sqlalchemy import text

    for name, table, column, method, operator_class in INDEX_SPECS:
        row = connection.execute(text("""SELECT t.relname AS table_name,
            a.attname AS column_name, am.amname AS method, opc.opcname AS operator_class,
            i.indisvalid, i.indisready, i.indpred IS NULL AS nonpartial,
            i.indisunique, i.indnkeyatts
            FROM pg_index i JOIN pg_class ix ON ix.oid=i.indexrelid
            JOIN pg_namespace ns ON ns.oid=ix.relnamespace
            JOIN pg_class t ON t.oid=i.indrelid JOIN pg_am am ON am.oid=ix.relam
            JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=i.indkey[0]
            JOIN pg_opclass opc ON opc.oid=i.indclass[0]
            WHERE ns.nspname='public' AND ix.relname=:name"""), {"name": name}).mappings().one_or_none()
        if not present:
            assert row is None
            continue
        assert row is not None
        assert (row["table_name"], row["column_name"], row["method"]) == (table, column, method)
        assert row["indisvalid"] and row["indisready"] and row["nonpartial"]
        assert row["indisunique"] is False and row["indnkeyatts"] == 1
        if operator_class:
            assert row["operator_class"] == operator_class


def _source_impact_indexes_on_migrated_schema(capability, engine, config):
    """0057 may round-trip with history while the later ledgers are empty."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        # Local synthetic database only: compare every application table row,
        # including historical capsule bytes and lifecycle/source identities.
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", "source_task_epoch", "source_task_requests", "source_task_attempts",
                                "background_job_cycles", *_RAG_EVIDENCE_TABLES, _EMBEDDING_RECEIPT_TABLE,
                                *_INDEX_GENERATION_TABLES, *_DISTRIBUTION_TABLES, _ML_FEATURE_BINDING_TABLE, *_SCIENTIFIC_IMPORT_TABLES, *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_source_impact_indexes(connection)
        assert connection.execute(text("SELECT count(*) FROM source_task_requests")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM source_task_attempts")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM background_job_cycles")).scalar_one() == 0
        _assert_empty_rag_evidence(connection)
        before = snapshot(connection)
        assert before["source_lifecycle_events"]
    validate_test_environment()
    command.downgrade(config, "0056_source_lifecycle")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_source_impact_indexes(connection, present=False)
        assert snapshot(connection) == before
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("The impact application must refuse the previous schema head")
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_source_impact_indexes(connection)
        assert connection.execute(text("SELECT count(*) FROM source_task_requests")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM source_task_attempts")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM background_job_cycles")).scalar_one() == 0
        _assert_empty_rag_evidence(connection)
        assert snapshot(connection) == before


async def _freeze_on_migrated_schema(capability, api_root):
    """Reuse reviewed synthetic test inputs on actual migrations, never create_all."""
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import _to_async_dsn
    from services.research_freeze import (
        freeze_research_release,
        inspect_research_release,
    )
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from test_research_freeze import approved, seed

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool,
                                 isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            fixture = await seed(session)
            _, arguments = await approved(session, fixture)
            rehearsal = await freeze_research_release(session, **arguments)
            assert rehearsal["dry_run"] is True
            report = await freeze_research_release(session, **arguments, dry_run=False)
            await session.commit()
            replay = await freeze_research_release(session, **arguments, dry_run=False)
            assert replay["release_id"] == report["release_id"] and replay["rows_inserted"] == 0
            checked = await inspect_research_release(session, release_id=report["release_id"],
                expected_manifest_sha256=report["manifest_sha256"], artifact_bytes=arguments["artifact_bytes"])
            assert checked["scientific_acceptance"] is False and checked["ml_training_approved"] is False
            await session.commit()
            return report["release_id"]
    finally:
        await engine.dispose()


async def _publication_on_migrated_schema(capability, api_root):
    """Synthetic role/review/publication history on real 0055 migration tables."""
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import _to_async_dsn
    from services.research_publication import (
        PublicationUnavailable,
        admitted_publication,
        publication_action,
    )
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from test_research_publication import published

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool,
                                 isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            fixture = await published(session)
            await session.commit()
            proposal = fixture["proposal"]
            result = await admitted_publication(session, proposal["id"])
            assert result["public_payload"] == proposal["public_payload"]
            await publication_action(session, actor_user_id=fixture["actors"]["publisher"],
                proposal_id=proposal["id"], review_id=fixture["review"]["id"],
                expected_payload_sha256=proposal["payload_sha256"], kind="withdraw",
                reason_code="synthetic_migration_withdrawal", dry_run=False)
            await session.commit()
            try:
                await admitted_publication(session, proposal["id"])
            except PublicationUnavailable:
                pass
            else:
                raise AssertionError("Withdrawn metadata publication remained accessible")
            return proposal["id"]
    finally:
        await engine.dispose()


def _source_lifecycle_on_migrated_schema(capability, engine, config):
    """Observe real 0056 bootstrap and raw SQL transitions after older guards.

    Source state is synthetic. Observation time is not a provider revision or
    the historical time at which a source first became held.
    """
    from alembic import command
    from services.schema_lifecycle import (
        SchemaLifecycleError,
        check_connection_schema,
    )
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    held_paper = "synthetic:sc08-migration-held"
    fresh_paper = "synthetic:sc08-migration-fresh"
    held_work = "2a6a3c2e-bf22-4862-8a77-dc80b89d2781"
    fresh_work = "2a6a3c2e-bf22-4862-8a77-dc80b89d2782"
    frozen_tables = ("research_releases", "research_release_pins", "research_release_notices",
                     "research_publication_proposals", "research_publication_reviews",
                     "research_publication_actions")

    def saved_history(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY id")).scalars().all()
                for name in frozen_tables}

    def events(connection):
        return connection.execute(text("SELECT to_jsonb(e) FROM source_lifecycle_events e ORDER BY paper_id,work_id,revision")).scalars().all()

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        assert connection.execute(text("SELECT count(*) FROM source_lifecycle_events")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM source_lifecycle_reviews")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM background_job_cycles")).scalar_one() == 0
        original_history = saved_history(connection)
    # This drops 0057's rebuildable indexes and the still-empty 0056 ledger.
    # Older immutable history and independently verified guards remain in place.
    validate_test_environment()
    command.downgrade(config, "0055_research_publication")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("The new application must refuse the previous schema head")
    with engine.begin() as connection:
        verify_postgres_identity(connection, capability)
        connection.execute(text("""INSERT INTO papers(id,source,title,authors,abstract,status)
            VALUES (:held,'arxiv','Synthetic held bootstrap','[]'::jsonb,'','retracted'),
                   (:fresh,'arxiv','Synthetic unheld bootstrap','[]'::jsonb,'','published')"""),
            {"held": held_paper, "fresh": fresh_paper})
        connection.execute(text("""INSERT INTO works(id,canonical_title,publication_status)
            VALUES (CAST(:held AS uuid),'Synthetic held work','corrected'),
                   (CAST(:fresh AS uuid),'Synthetic unheld work','active')"""),
            {"held": held_work, "fresh": fresh_work})
        originals = {
            "paper": connection.execute(text("SELECT to_jsonb(p) FROM papers p WHERE id=:id"), {"id": held_paper}).scalar_one(),
            "work": connection.execute(text("SELECT to_jsonb(w) FROM works w WHERE id=CAST(:id AS uuid)"), {"id": held_work}).scalar_one(),
        }
        observation_start = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
    with engine.begin() as connection:
        verify_postgres_identity(connection, capability)
        baseline = events(connection)
        assert len(baseline) == 2
        assert all(row["revision"] == 1 and row["predecessor_id"] is None
                   and row["event_kind"] == "baseline_observed" for row in baseline)
        assert {row["observed_status"] for row in baseline} == {"retracted", "corrected"}
        assert connection.execute(text("SELECT min(created_at)>=:start AND max(created_at)<=clock_timestamp() FROM source_lifecycle_events"),
                                  {"start": observation_start}).scalar_one() is True
        assert connection.execute(text("SELECT to_jsonb(p) FROM papers p WHERE id=:id"), {"id": held_paper}).scalar_one() == originals["paper"]
        assert connection.execute(text("SELECT to_jsonb(w) FROM works w WHERE id=CAST(:id AS uuid)"), {"id": held_work}).scalar_one() == originals["work"]
        # Removing a live status flag cannot remove observed negative history.
        connection.execute(text("UPDATE papers SET status='published' WHERE id=:id"), {"id": held_paper})
        connection.execute(text("UPDATE works SET publication_status='active' WHERE id=CAST(:id AS uuid)"), {"id": held_work})
        # Bibliographic dates are semantic revisions even without a material edit.
        connection.execute(text("UPDATE papers SET date_published=DATE '2026-09-07' WHERE id=:id"), {"id": held_paper})
        connection.execute(text("UPDATE works SET available_at=DATE '2026-09-07' WHERE id=CAST(:id AS uuid)"), {"id": held_work})
        after_dates = events(connection)
        assert len(after_dates) == 6
        for key, identifier in (("paper_id", held_paper), ("work_id", held_work)):
            chain = [row for row in after_dates if row[key] == identifier]
            assert [row["revision"] for row in chain] == [1, 2, 3]
            assert [row["event_kind"] for row in chain] == ["baseline_observed", "lifecycle_change", "catalogue_revision"]
            assert [row["predecessor_id"] for row in chain[1:]] == [row["id"] for row in chain[:-1]]
            assert [row["old_snapshot_sha256"] for row in chain[1:]] == [row["snapshot_sha256"] for row in chain[:-1]]
        # Idempotent semantic retries and operational counters add no revision.
        connection.execute(text("UPDATE papers SET date_published=DATE '2026-09-07',citation_count=citation_count+1,updated_at=clock_timestamp() WHERE id=:id"),
                           {"id": held_paper})
        connection.execute(text("UPDATE works SET available_at=DATE '2026-09-07',updated_at=clock_timestamp() WHERE id=CAST(:id AS uuid)"),
                           {"id": held_work})
        assert events(connection) == after_dates
        # Sources that were not held at migration time start tracking on their
        # first negative transition; ordinary pre-hold updates do not backfill.
        connection.execute(text("UPDATE papers SET status='retracted' WHERE id=:id"), {"id": fresh_paper})
        connection.execute(text("UPDATE works SET publication_status='withdrawn' WHERE id=CAST(:id AS uuid)"), {"id": fresh_work})
        connection.execute(text("UPDATE papers SET status='published' WHERE id=:id"), {"id": fresh_paper})
        connection.execute(text("UPDATE works SET publication_status='active' WHERE id=CAST(:id AS uuid)"), {"id": fresh_work})
        all_events = events(connection)
        assert len(all_events) == 10
        assert connection.execute(text("SELECT bool_and(record_sha256=public.sclib_source_lifecycle_record_hash_v1(to_jsonb(e))) FROM source_lifecycle_events e")).scalar_one() is True
        for statement, parameters, expected_state in (
            ("DELETE FROM papers WHERE id=:id", {"id": held_paper}, "23503"),
            ("DELETE FROM works WHERE id=CAST(:id AS uuid)", {"id": held_work}, "23503"),
            ("UPDATE source_lifecycle_events SET event_kind=event_kind", {}, "55000"),
        ):
            try:
                with connection.begin_nested():
                    connection.execute(text(statement), parameters)
            except DBAPIError as exc:
                assert exc.orig.pgcode == expected_state
            else:
                raise AssertionError("Observed source identities and lifecycle history must be retained")
        assert events(connection) == all_events
        assert saved_history(connection) == original_history
    try:
        validate_test_environment()
        command.downgrade(config, "0055_research_publication")
    except RuntimeError as exc:
        assert "lifecycle history contains records" in str(exc)
    else:
        raise AssertionError("Nonempty lifecycle downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        # 0056 refusal also rolls back preceding index drops in the same
        # migration transaction, leaving the exact latest schema admitted.
        _assert_source_impact_indexes(connection)
        assert events(connection) == all_events
        assert saved_history(connection) == original_history


async def _source_tasks_on_migrated_schema(capability, api_root):
    """Exercise the real queue's SQL effect and rollback on migrated tables.

    This is an explicitly synthetic, narrow cache-invalidation receipt. It
    proves neither Timeline rebuilding nor source reinstatement/ML approval.
    Populate this ledger only after each older downgrade guard was exercised.
    """
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import Base, _to_async_dsn
    from services.research_release_manifest import digest
    from services.source_impact import inspect_source_impact
    from services.source_tasks import (
        enqueue_source_task,
        execute_source_task,
        record_source_task_failure,
    )
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from test_research_freeze import add, state
    from test_research_publication import actors
    from test_source_impact import material, observation

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool,
                                 isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            people = await actors(session)
            source, event_args = await observation(session)
            await material(session, source=source)
            inventory = await inspect_source_impact(session, **event_args)
            body = {key: value for key, value in inventory.items() if key not in {"observation", "inventory_sha256"}}
            assert digest(body) == inventory["inventory_sha256"]
            await session.execute(text("UPDATE timeline_projection_state SET schema_version=6 WHERE id=1"))
            request_args = dict(
                **event_args, actor_user_id=people["curator"], expected_inventory_sha256=inventory["inventory_sha256"],
                request_key="synthetic-migrated-queue")
            before_request = await state(session)
            rehearsal = await enqueue_source_task(session, **request_args)
            assert rehearsal["dry_run"] is True
            assert await state(session) == before_request
            request = (await enqueue_source_task(session, **request_args, dry_run=False))["request"]
            await session.commit()
            execute_args = dict(actor_user_id=people["curator"], request_id=request["id"],
                                expected_request_sha256=request["record_sha256"])

            async def append_attempt(number, predecessor=None, *, success):
                return await add(session, "source_task_attempts", request_id=request["id"],
                    attempt_number=number, predecessor_id=predecessor,
                    executor_id=people["curator"], executor_grant_id=people["grants"]["curator"],
                    execution_key=f"synthetic-attempt-{number}",
                    status="succeeded" if success else "retryable_failure",
                    outcome_code="timeline_cache_invalidated" if success else "database_busy")

            # A savepoint rollback must revert both the receipt and its actual
            # cache readiness effect, including all participating fence epochs.
            before_attempt = await state(session)
            assert before_attempt["timeline_projection_state"][0]["schema_version"] == 6
            rehearsal = (await execute_source_task(session, **execute_args, execution_key="synthetic-attempt-1"))["attempt"]
            assert rehearsal["state_present"] is True and rehearsal["state_changed"] is True
            assert await state(session) == before_attempt

            # Explicit attributed report after the rehearsal transaction ends;
            # this does not pretend to have witnessed a real database outage.
            await session.rollback()
            failure = (await record_source_task_failure(session, **execute_args,
                execution_key="synthetic-attempt-1", outcome_code="database_busy", dry_run=False))["attempt"]
            assert failure["state_present"] is False and failure["state_changed"] is False
            assert await session.scalar(text("SELECT schema_version FROM timeline_projection_state WHERE id=1")) == 6
            await session.commit()
            success = (await execute_source_task(session, **execute_args,
                execution_key="synthetic-attempt-2", dry_run=False))["attempt"]
            assert success["state_present"] is True and success["state_changed"] is True
            after_attempt = await state(session)
            expected_state = [dict(row, schema_version=0) for row in before_attempt["timeline_projection_state"]]
            assert after_attempt["timeline_projection_state"] == expected_state
            changed_tables = {"source_task_attempts", "source_task_epoch", "source_lifecycle_epoch",
                              "research_integrity_epoch", "research_publication_epoch", "timeline_projection_state"}
            assert {key: value for key, value in after_attempt.items() if key not in changed_tables} == {
                key: value for key, value in before_attempt.items() if key not in changed_tables}
            assert len([row for row in after_attempt["source_task_attempts"] if row["request_id"] == str(request["id"])]) == 2
            for name in ("source_task_requests", "source_task_attempts"):
                for statement in (f"UPDATE {name} SET record_sha256=record_sha256", f"DELETE FROM {name}", f"TRUNCATE {name} CASCADE"):
                    try:
                        async with session.begin_nested():
                            await session.execute(text(statement))
                    except DBAPIError as exc:
                        assert getattr(exc.orig, "sqlstate", None) == "55000"
                    else:
                        raise AssertionError("Source-task requests and attempts must remain immutable")
            assert await state(session) == after_attempt
            # The terminal receipt cannot acquire another successor.
            try:
                async with session.begin_nested():
                    await append_attempt(3, success["id"], success=True)
            except DBAPIError as exc:
                assert getattr(exc.orig, "sqlstate", None) == "23514"
            else:
                raise AssertionError("A terminal source-task receipt must not be executed again")
            assert await state(session) == after_attempt
            await session.commit()
            await session.execute(text("UPDATE timeline_projection_state SET schema_version=6 WHERE id=1"))
            await session.commit()
            replay = await execute_source_task(session, **execute_args, execution_key="synthetic-attempt-2", dry_run=False)
            assert replay["replayed"] is True and replay["attempt"] == success
            assert await session.scalar(text("SELECT schema_version FROM timeline_projection_state WHERE id=1")) == 6
            await session.commit()
            # Actual FK policy retains both actor identities. The account API's
            # separate preflight also treats these references as an audit hold.
            for name, column in (("source_task_requests", "requester_id"), ("source_task_attempts", "executor_id")):
                table = Base.metadata.tables[name]
                assert next(iter(table.c[column].foreign_keys)).ondelete == "RESTRICT"
            return str(request["id"])
    finally:
        await engine.dispose()


def _source_task_downgrade_guard(capability, engine, config, request_id):
    """A populated 0058 refusal preserves the whole latest schema and data."""
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == request_id for row in before["source_task_requests"])
        assert before["background_job_cycles"] == []
    try:
        validate_test_environment()
        command.downgrade(config, "0057_source_impact")
    except RuntimeError as exc:
        assert "task" in str(exc).lower() and "records" in str(exc).lower()
    else:
        raise AssertionError("Nonempty source-task downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_source_impact_indexes(connection)
        assert snapshot(connection) == before


def _background_jobs_empty_roundtrip(capability, engine, config):
    """0059 alone can round-trip without losing populated 0052–0058 history."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", "background_job_cycles", *_RAG_EVIDENCE_TABLES,
                                _EMBEDDING_RECEIPT_TABLE, *_INDEX_GENERATION_TABLES, *_DISTRIBUTION_TABLES, _ML_FEATURE_BINDING_TABLE, *_SCIENTIFIC_IMPORT_TABLES, *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert connection.execute(text("SELECT count(*) FROM background_job_cycles")).scalar_one() == 0
        _assert_empty_rag_evidence(connection)
        before = snapshot(connection)
        assert before["source_task_requests"] and before["source_task_attempts"]
    validate_test_environment()
    command.downgrade(config, "0058_source_tasks")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("The background-job application must refuse the previous schema head")
        verify_postgres_identity(connection, capability)
        assert "background_job_cycles" not in inspect(connection).get_table_names(schema="public")
        assert snapshot(connection) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert connection.execute(text("SELECT count(*) FROM background_job_cycles")).scalar_one() == 0
        _assert_empty_rag_evidence(connection)
        assert snapshot(connection) == before


async def _background_jobs_on_migrated_schema(capability, api_root):
    """Real session-locked service effects and failure rollback after all old guards."""
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import AuditReport, _to_async_dsn
    from services.background_jobs import due_cycle, run_background_cycle
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import insert, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool)

    async def snapshot():
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            async with AsyncSession(connection, expire_on_commit=False) as session:
                return await state(session)

    async def effect(session, scheduled_for, cycle_id, *, fail=False):
        await session.execute(insert(AuditReport).values(started_at=scheduled_for,
            completed_at=sa.func.clock_timestamp(), rule_name="en03-migration-synthetic",
            severity="info", rows_flagged=1, sample_ids=[str(cycle_id)],
            suggested_fixes=[{"synthetic": True, "cycle_id": str(cycle_id)}]))
        if fail:
            raise RuntimeError("Synthetic transaction rollback rehearsal")
        return {"audit_reports_created": 1, "synthetic": True}

    # Imports remain inside the already-validated native disposable boundary.
    import sqlalchemy as sa
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            now = (await connection.execute(text("SELECT clock_timestamp()"))).scalar_one()
        due = due_cycle(now, 1)
        before = await snapshot()
        assert before["background_job_cycles"] == []

        async def failed_effect(session, scheduled_for, cycle_id):
            return await effect(session, scheduled_for, cycle_id, fail=True)

        failed = await run_background_cycle("formula_audit", interval_seconds=1, handler=failed_effect,
            engine=engine, scheduled_for=due, config={"synthetic_migration": "rollback"})
        assert failed["status"] == "failed" and failed["error_code"] == "execution_failed"
        after_failure = await snapshot()
        assert after_failure["audit_reports"] == before["audit_reports"]
        assert len(after_failure["background_job_cycles"]) == 1
        assert {key: value for key, value in after_failure.items() if key != "background_job_cycles"} == {
            key: value for key, value in before.items() if key != "background_job_cycles"}

        arguments = dict(interval_seconds=1, handler=effect, engine=engine,
                         scheduled_for=due, config={"synthetic_migration": "success"})
        succeeded = await run_background_cycle("nightly_audit", **arguments)
        assert succeeded["status"] == "succeeded" and succeeded["attempts"] == 1
        after_success = await snapshot()
        assert len(after_success["background_job_cycles"]) == 2
        reports = [row for row in after_success["audit_reports"] if row["rule_name"] == "en03-migration-synthetic"]
        assert len(reports) == 1 and reports[0]["sample_ids"] == [succeeded["cycle_id"]]
        assert {key: value for key, value in after_success.items() if key not in {"background_job_cycles", "audit_reports"}} == {
            key: value for key, value in before.items() if key not in {"background_job_cycles", "audit_reports"}}
        replay = await run_background_cycle("nightly_audit", **arguments)
        assert replay["status"] == "already_succeeded" and replay["cycle_id"] == succeeded["cycle_id"]
        assert await snapshot() == after_success
        async with engine.connect() as connection:
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            assert not (await connection.execute(text("""SELECT EXISTS(SELECT 1 FROM pg_locks
                WHERE locktype='advisory' AND classid=0 AND objid IN (589017031,589017032,589017033,589017034,589017035)
                AND objsubid=1 AND database=(SELECT oid FROM pg_database WHERE datname=current_database()))"""))).scalar_one()
        return succeeded["cycle_id"]
    finally:
        await engine.dispose()


def _background_job_downgrade_guard(capability, engine, config, cycle_id):
    """A populated 0059 refusal preserves successful work and every older ledger."""
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == cycle_id and row["status"] == "succeeded" for row in before["background_job_cycles"])
        _assert_empty_rag_evidence(connection)
    try:
        validate_test_environment()
        command.downgrade(config, "0058_source_tasks")
    except RuntimeError as exc:
        assert "background-job" in str(exc) and "cycle history contains records" in str(exc)
    else:
        raise AssertionError("Nonempty background-job downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _rag_evidence_empty_roundtrip(capability, engine, config):
    """0060 alone round-trips while every independently tested older ledger survives."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_RAG_EVIDENCE_TABLES, _EMBEDDING_RECEIPT_TABLE,
                                *_INDEX_GENERATION_TABLES, *_DISTRIBUTION_TABLES, _ML_FEATURE_BINDING_TABLE, *_SCIENTIFIC_IMPORT_TABLES, *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_rag_evidence(connection)
        before = snapshot(connection)
        assert before["background_job_cycles"] and before["source_task_requests"]
    validate_test_environment()
    command.downgrade(config, "0059_background_jobs")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("The RAG-lineage application must refuse the previous schema head")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        assert not set(_RAG_EVIDENCE_TABLES) & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_rag_evidence(connection)
        assert snapshot(connection) == before


async def _rag_evidence_on_migrated_schema(capability, api_root):
    """Actual 0060 parent/envelope writes, dry-run, invalidation and exact replay."""
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import _to_async_dsn
    from services import rag_evidence
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from test_rag_evidence import chunk_row, seed
    from test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            chunk_id, candidate = await seed(session)
            await session.commit()
            before = await state(session)
            assert all(before[name] == [] for name in _RAG_EVIDENCE_TABLES)
            rehearsal = await rag_evidence.register_chunk_evidence(session, chunk_id=chunk_id, candidate=candidate)
            assert rehearsal["dry_run"] is True and rehearsal["committed"] is False
            assert await state(session) == before
            first = await rag_evidence.register_chunk_evidence(session, chunk_id=chunk_id, candidate=candidate, dry_run=False)
            await session.commit()
            written = await state(session)
            assert [len(written[name]) for name in _RAG_EVIDENCE_TABLES] == [1, 1, 1]
            parent = written["rag_extraction_revisions"][0]
            assert parent["scientific_acceptance"] is False and "PRIVATE ORIGINAL WORDING" not in str(parent)
            descriptor = (await rag_evidence.resolve_chunk_evidence(session, [await chunk_row(session, chunk_id)]))[chunk_id]
            assert descriptor["currentness"] == "current" and descriptor["chunk_kind"] == "derived_fact"
            assert descriptor["support_eligible"] is descriptor["independent_evidence"] is descriptor["scientific_acceptance"] is False
            replay = await rag_evidence.register_chunk_evidence(session, chunk_id=chunk_id, candidate=candidate, dry_run=False)
            assert replay == first
            await session.commit()
            assert await state(session) == written

            await session.execute(text("UPDATE chunks SET text='Synthetic changed rendering' WHERE id=:id"), {"id": chunk_id})
            invalidated = await state(session)
            assert invalidated["chunk_evidence_current"] == []
            assert invalidated["rag_extraction_revisions"] == written["rag_extraction_revisions"]
            assert invalidated["rag_evidence_revisions"] == written["rag_evidence_revisions"]
            # Even immutable rows appended in this outer effect set must roll
            # back with an interrupted chunk replacement.
            await rag_evidence.register_chunk_evidence(session, chunk_id=chunk_id, candidate=candidate, dry_run=False)
            await session.rollback()
            assert await state(session) == written

            await session.execute(text("UPDATE chunks SET text='Synthetic changed rendering' WHERE id=:id"), {"id": chunk_id})
            await session.commit()
            try:
                await rag_evidence.bind_chunk_evidence(session, chunk_id=chunk_id,
                    evidence_revision_id=first["evidence_revision_id"], dry_run=False)
            except DBAPIError as exc:
                assert "exact_live_chunk" in str(exc)
            else:
                raise AssertionError("An old rendering cannot be rebound to changed content")
            second = await rag_evidence.register_chunk_evidence(session, chunk_id=chunk_id, candidate=candidate, dry_run=False)
            await session.commit()
            assert second["evidence_revision_id"] != first["evidence_revision_id"]
            final = await state(session)
            assert [len(final[name]) for name in _RAG_EVIDENCE_TABLES] == [1, 2, 1]
            assert written["rag_evidence_revisions"][0] in final["rag_evidence_revisions"]
            assert await rag_evidence.register_chunk_evidence(session, chunk_id=chunk_id, candidate=candidate, dry_run=False) == second
            await session.commit()
            assert await state(session) == final
            return second["evidence_revision_id"]
    finally:
        await engine.dispose()


def _rag_evidence_downgrade_guard(capability, engine, config, evidence_id):
    """Populated 0060 refuses destructive downgrade without masking older guards."""
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_embedding_receipts(connection)
        before = snapshot(connection)
        assert any(row["id"] == evidence_id for row in before["rag_evidence_revisions"])
    try:
        validate_test_environment()
        command.downgrade(config, "0059_background_jobs")
    except RuntimeError as exc:
        assert "RAG-evidence" in str(exc) and "lineage history contains records" in str(exc)
    else:
        raise AssertionError("Nonempty RAG lineage downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _embedding_receipts_empty_roundtrip(capability, engine, config):
    """0061 alone round-trips after all older independent nonempty guards."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", _EMBEDDING_RECEIPT_TABLE, *_INDEX_GENERATION_TABLES,
                                *_DISTRIBUTION_TABLES, _ML_FEATURE_BINDING_TABLE, *_SCIENTIFIC_IMPORT_TABLES, *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_embedding_receipts(connection)
        before = snapshot(connection)
        assert before["rag_evidence_revisions"] and before["source_task_requests"] and before["background_job_cycles"]
    validate_test_environment()
    command.downgrade(config, "0060_rag_evidence")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("Embedding-receipt application must refuse the previous schema head")
        verify_postgres_identity(connection, capability)
        assert _EMBEDDING_RECEIPT_TABLE not in inspect(connection).get_table_names(schema="public")
        assert snapshot(connection) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_embedding_receipts(connection)
        assert snapshot(connection) == before


async def _embedding_receipts_on_migrated_schema(capability, api_root, evidence_id):
    """Real validated response receipt without provider or vector-upload calls."""
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import _to_async_dsn
    from services.embedding_receipts import append_embedding_receipt
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from test_embedding_receipts import completion
    from test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            chunk = (await session.execute(text("SELECT c.id,c.text FROM chunks c JOIN chunk_evidence_current p ON p.chunk_id=c.id "
                "WHERE p.evidence_revision_id=CAST(:id AS uuid)"), {"id": evidence_id})).mappings().one()
            vector, receipt = completion(chunk["text"])
            before = await state(session)
            assert before[_EMBEDDING_RECEIPT_TABLE] == []
            dry = await append_embedding_receipt(session, chunk_id=chunk["id"], vector=vector, receipt=receipt)
            assert dry["dry_run"] is True and dry["completion_scope"] == "embedding_response_only"
            assert await state(session) == before
            # An outer rollback must discard a non-dry-run receipt too.
            await append_embedding_receipt(session, chunk_id=chunk["id"], vector=vector, receipt=receipt, dry_run=False)
            await session.rollback()
            assert await state(session) == before
            first = await append_embedding_receipt(session, chunk_id=chunk["id"], vector=vector, receipt=receipt, dry_run=False)
            await session.commit()
            written = await state(session)
            assert len(written[_EMBEDDING_RECEIPT_TABLE]) == 1
            stored = written[_EMBEDDING_RECEIPT_TABLE][0]
            assert stored["evidence_revision_id"] == evidence_id
            assert stored["vector_sha256"] == receipt["vector_sha256"]
            assert stored["metadata_json"]["provider_truncated"] is False
            assert "PRIVATE ORIGINAL WORDING" not in str(stored) and "text" not in stored and "vector" not in stored
            assert {key: value for key, value in written.items() if key not in {_EMBEDDING_RECEIPT_TABLE, "research_integrity_epoch"}} == {
                key: value for key, value in before.items() if key not in {_EMBEDDING_RECEIPT_TABLE, "research_integrity_epoch"}}
            replay = await append_embedding_receipt(session, chunk_id=chunk["id"], vector=vector, receipt=receipt, dry_run=False)
            assert replay == first
            await session.commit()
            assert await state(session) == written
            return first["receipt_id"]
    finally:
        await engine.dispose()


def _embedding_receipt_downgrade_guard(capability, engine, config, receipt_id):
    """Nonempty 0061 refusal retains every receipt and earlier audit object."""
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == receipt_id for row in before[_EMBEDDING_RECEIPT_TABLE])
        _assert_empty_index_generations(connection)
    try:
        validate_test_environment()
        command.downgrade(config, "0060_rag_evidence")
    except RuntimeError as exc:
        assert "embedding-receipt" in str(exc) and "receipt history contains records" in str(exc)
    else:
        raise AssertionError("Nonempty embedding receipt downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _index_generations_empty_roundtrip(capability, engine, config):
    """Older populated audit ledgers survive an independently empty0062 cycle."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_INDEX_GENERATION_TABLES, *_DISTRIBUTION_TABLES, _ML_FEATURE_BINDING_TABLE, *_SCIENTIFIC_IMPORT_TABLES, *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_index_generations(connection)
        before = snapshot(connection)
        assert before[_EMBEDDING_RECEIPT_TABLE]
    validate_test_environment()
    command.downgrade(config, "0061_embedding_receipts")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError:
            pass
        else:
            raise AssertionError("Generation application must refuse older schema")
        verify_postgres_identity(connection, capability)
        assert not set(_INDEX_GENERATION_TABLES) & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_index_generations(connection)
        assert snapshot(connection) == before


async def _index_generations_on_migrated_schema(capability, api_root, receipt_id, *, recorder=None):
    """Actual bounded stage/validate/CAS/rollback, with no cloud calls."""
    validate_test_environment()
    import struct
    sys.path.insert(0, str(api_root / "tests"))
    from uuid import uuid4

    from models.db import _to_async_dsn
    from services.index_generations import (
        activate_generation,
        load_active_generation,
        load_generation_members,
        record_validation,
        stage_generation,
    )
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from test_embedding_receipts import completion
    from test_index_generations import observation, resource
    from test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
            chunk = (await session.execute(text("SELECT c.id,c.text FROM chunks c JOIN embedding_completion_receipts r ON r.chunk_key=c.id WHERE r.id=CAST(:id AS uuid)"),
                                           {"id": receipt_id})).mappings().one()
            vector, _ = completion(chunk["text"])
            items = [{"chunk_id": chunk["id"], "receipt_id": receipt_id, "vector": vector, "parser_version": "synthetic-migration/1"}]
            before = await state(session)
            generation_id = uuid4()
            await stage_generation(session, generation_id=generation_id, items=items, resource=resource())
            assert await state(session) == before
            await stage_generation(session, generation_id=generation_id, items=items, resource=resource(), dry_run=False)
            await session.rollback()
            assert await state(session) == before
            first = await stage_generation(session, generation_id=generation_id, items=items, resource=resource(), dry_run=False)
            await session.commit()
            written = await state(session)
            replay = await stage_generation(session, generation_id=generation_id, items=items, resource=resource(), dry_run=False)
            assert replay == first
            await session.commit()
            assert await state(session) == written
            report = await observation(session, first)
            validation = await record_validation(session, generation_id=generation_id, observation=report, dry_run=False)
            await session.commit()
            validated_state = await state(session)
            activate_args = dict(generation_id=generation_id, validation_id=validation["validation_id"], expected_event_id=None, idempotency_key="migration-initial")
            await activate_generation(session, **activate_args)
            assert await state(session) == validated_state
            first_active = await activate_generation(session, **activate_args, dry_run=False)
            await session.commit()
            active_state = await state(session)
            assert await activate_generation(session, **activate_args, dry_run=False) == first_active
            await session.commit()
            assert await state(session) == active_state
            second = await stage_generation(session, generation_id=uuid4(), items=[{**items[0], "parser_version": "synthetic-migration/2"}], resource=resource(), dry_run=False)
            second_validation = await record_validation(session, generation_id=second["generation_id"], observation=await observation(session, second), dry_run=False)
            second_active = await activate_generation(session, generation_id=second["generation_id"], validation_id=second_validation["validation_id"],
                                                      expected_event_id=first_active["activation_event_id"], idempotency_key="migration-second", dry_run=False)
            await session.execute(text("UPDATE chunks SET text='Synthetic newer mutable text' WHERE id=:id"), {"id": chunk["id"]})
            retained = await load_generation_members(session, generation_id=generation_id)
            assert retained[0]["snapshot_json"]["text"] == chunk["text"]
            assert len(retained[0]["vector_bytes"]) == 3072
            assert bytes(retained[0]["vector_bytes"]) == struct.pack(">768f", *vector)
            restored = await activate_generation(session, generation_id=generation_id, validation_id=validation["validation_id"],
                                                 expected_event_id=second_active["activation_event_id"], idempotency_key="migration-rollback", action="rollback", dry_run=False)
            await session.commit()
            actual = await load_active_generation(session)
            assert actual["activation_event_id"] == restored["activation_event_id"]
            assert actual["generation_id"] == str(generation_id)
            if recorder is not None:
                recorder.rollback = {
                    "generation_ids": [str(generation_id), second["generation_id"]],
                    "validation_ids": [validation["validation_id"], second_validation["validation_id"]],
                    "activation_event_ids": [first_active["activation_event_id"], second_active["activation_event_id"]],
                    "rollback_activation_event_id": restored["activation_event_id"],
                    "restored_generation_id": actual["generation_id"], "restored_activation_event_id": actual["activation_event_id"],
                    "retained_member_count": len(retained), "retained_text_sha256": sha(retained[0]["snapshot_json"]["text"].encode()),
                    "retained_vector_sha256": sha(bytes(retained[0]["vector_bytes"])),
                    "retained_vector_bytes": len(retained[0]["vector_bytes"]), "verified": True,
                    "procedure": "validate_retained_generation_then_CAS_from_current_event_with_action_rollback",
                }
            return str(generation_id)
    finally:
        await engine.dispose()


def _index_generation_downgrade_guard(capability, engine, config, generation_id):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == generation_id for row in before["index_generations"])
        _assert_empty_distributions(connection)
    try:
        validate_test_environment()
        command.downgrade(config, "0061_embedding_receipts")
    except RuntimeError as exc:
        assert "index-generation" in str(exc) and "retained history contains records" in str(exc)
    else:
        raise AssertionError("Nonempty generation history downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _distributions_empty_roundtrip(capability, engine, config):
    """Independently empty0063 roundtrip preserves every already populated ledger."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_DISTRIBUTION_TABLES, _ML_FEATURE_BINDING_TABLE, *_SCIENTIFIC_IMPORT_TABLES, *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_distributions(connection)
        before = snapshot(connection)
        assert before["index_activation_events"]
    validate_test_environment()
    command.downgrade(config, "0062_index_generations")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError:
            pass
        else:
            raise AssertionError("Distribution application must refuse the previous schema")
        verify_postgres_identity(connection, capability)
        assert not set(_DISTRIBUTION_TABLES) & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_distributions(connection)
        assert snapshot(connection) == before


async def _distributions_on_migrated_schema(capability, api_root):
    """Real full RPS recomputation, capsule roots, per-dependency grants and withdrawal."""
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import _to_async_dsn
    from services import research_distribution as service
    from services.research_distribution_contract import ResearchDistributionError
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.rps_distribution_fixtures import (
        distribution_inputs,
        publish_distribution,
        release_document,
    )
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool,
                                 isolation_level="SERIALIZABLE")
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            inputs = await distribution_inputs(session, release_document("synthetic-migrated-distribution"))
            people = inputs["shared"]["actors"]
            await session.commit()
            before = await state(session)
            arguments = dict(actor_user_id=people["curator"], request_key="migration:distribution:preview",
                             **inputs["arguments"])
            preview = await service.register_distribution(session, **arguments)
            assert preview["dry_run"] is True and preview["scientific_acceptance"] is False
            assert await state(session) == before
            await service.register_distribution(session, **arguments, dry_run=False)
            await session.rollback()
            assert await state(session) == before
            context = await publish_distribution(session, inputs["release"], shared=inputs["shared"])
            await session.commit()
            published = await state(session)
            package_id = context["registration"]["package_id"]
            admitted = await service.admitted_distribution(session, package_id)
            assert admitted["bundle_sha256"] == context["bundle"]["bundle_sha256"]
            replay = await service.register_distribution(session, actor_user_id=people["curator"],
                request_key=context["request_prefix"] + ":register", **context["arguments"], dry_run=False)
            assert replay == {**context["registration"], "replayed": True}
            await session.commit()
            assert await state(session) == published
            for index, permission in enumerate(context["permissions"]):
                assert await service.decide_distribution_permission(session,
                    request_key=context["request_prefix"] + ":permission:" + str(index),
                    **permission["arguments"], dry_run=False) == {**permission["receipt"], "replayed": True}
            assert await service.review_distribution(session, actor_user_id=people["reviewer"],
                request_key=context["request_prefix"] + ":review", package_id=package_id,
                expected_inventory_sha256=context["registration"]["inventory_sha256"],
                disclosure_approved=True, reason_code="synthetic_independent_disclosure", dry_run=False) == {**context["review"], "replayed": True}
            assert await service.distribution_action(session, actor_user_id=people["publisher"],
                request_key=context["request_prefix"] + ":publish", package_id=package_id,
                review_id=context["review"]["id"], expected_inventory_sha256=context["registration"]["inventory_sha256"],
                kind="publish", reason_code="synthetic_publication", dry_run=False) == {**context["action"], "replayed": True}
            await session.commit()
            assert await state(session) == published
            withdraw = dict(actor_user_id=people["publisher"], request_key="migration:distribution:withdraw",
                package_id=package_id, review_id=context["review"]["id"],
                expected_inventory_sha256=context["registration"]["inventory_sha256"], kind="withdraw",
                reason_code="synthetic_migration_withdrawal")
            await service.distribution_action(session, **withdraw)
            assert await state(session) == published
            await service.distribution_action(session, **withdraw, dry_run=False)
            await session.rollback()
            assert await state(session) == published
            await service.distribution_action(session, **withdraw, dry_run=False)
            await session.commit()
            withdrawn = await state(session)
            try:
                await service.admitted_distribution(session, package_id)
            except ResearchDistributionError:
                pass
            else:
                raise AssertionError("Withdrawn distribution must not be publicly admitted")
            await service.distribution_action(session, **withdraw, dry_run=False)
            await session.commit()
            assert await state(session) == withdrawn
            return package_id
    finally:
        await engine.dispose()


def _distribution_downgrade_guard(capability, engine, config, package_id):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == package_id for row in before["research_distribution_packages"])
        _assert_empty_ml_feature_bindings(connection)
    try:
        validate_test_environment()
        command.downgrade(config, "0062_index_generations")
    except RuntimeError as exc:
        assert "research-distribution" in str(exc) and "retained governance history" in str(exc)
    else:
        raise AssertionError("Nonempty distribution history downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _ml_feature_bindings_empty_roundtrip(capability, engine, config):
    """An empty0064 can round-trip after all older histories are populated."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", _ML_FEATURE_BINDING_TABLE, *_SCIENTIFIC_IMPORT_TABLES, *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_ml_feature_bindings(connection)
        before = snapshot(connection)
        assert before["research_distribution_actions"]
    validate_test_environment()
    command.downgrade(config, "0063_research_distribution")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError:
            pass
        else:
            raise AssertionError("Feature companion application must refuse the previous schema")
        verify_postgres_identity(connection, capability)
        assert _ML_FEATURE_BINDING_TABLE not in inspect(connection).get_table_names(schema="public")
        assert snapshot(connection) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_ml_feature_bindings(connection)
        assert snapshot(connection) == before


async def _ml_feature_bindings_on_migrated_schema(capability, api_root):
    """Actual source bytes and original0054 pins, never a fabricated Tc occurrence."""
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import _to_async_dsn
    from services import ml_feature_companion as service
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_ml_feature_companion import companion, feature_fixture, verify
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool,
                                 isolation_level="SERIALIZABLE")
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            fixture = await feature_fixture(session)
            await session.commit()
            before = await state(session)
            preview = await service.register_feature_source_binding(session, **fixture["args"])
            assert preview["dry_run"] is True and preview["committed"] is False
            assert await state(session) == before
            await service.register_feature_source_binding(session, **fixture["args"], dry_run=False)
            await session.rollback()
            assert await state(session) == before
            first = await service.register_feature_source_binding(session, **fixture["args"], dry_run=False)
            await session.commit()
            written = await state(session)
            replay = await service.register_feature_source_binding(session, **fixture["args"], dry_run=False)
            assert replay == {**first, "replayed": True}
            await session.commit()
            assert await state(session) == written
            retained = await companion(session, fixture)
            verified = verify(retained, fixture)[str(fixture["input"]["id"])]
            assert verified["target_ref"] == ["event_properties", str(fixture["property"]["id"])]
            assert verified["temporal"]["result_available_at"] == "2020-01-01T00:00:00Z"
            assert verified["temporal"]["captured_at"] == "2026-01-01T00:00:00Z"
            assert verified["ml_training_approved"] is verified["reviewer_authority_authenticated"] is False
            assert service.decode_companion_artifacts(retained) == fixture["artifact_bytes"]
            assert await state(session) == written
            return first["binding_id"]
    finally:
        await engine.dispose()


def _ml_feature_binding_downgrade_guard(capability, engine, config, binding_id):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == binding_id for row in before[_ML_FEATURE_BINDING_TABLE])
    try:
        validate_test_environment()
        command.downgrade(config, "0063_research_distribution")
    except RuntimeError as exc:
        assert "ML feature companion" in str(exc) and "retained source binding history" in str(exc)
    else:
        raise AssertionError("Nonempty feature source binding history downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _scientific_imports_empty_roundtrip(capability, engine, config):
    """Only the empty0065 ledger is removed; all older populated histories remain."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_SCIENTIFIC_IMPORT_TABLES, *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_scientific_imports(connection)
        before = snapshot(connection)
        assert before[_ML_FEATURE_BINDING_TABLE]
    validate_test_environment()
    command.downgrade(config, "0064_ml_feature_companion")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError:
            pass
        else:
            raise AssertionError("Scientific import application must refuse the previous schema")
        assert not set(_SCIENTIFIC_IMPORT_TABLES) & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_scientific_imports(connection)
        assert snapshot(connection) == before


async def _scientific_imports_on_migrated_schema(capability, api_root, *, recorder=None):
    """Actual retained bytes and separate durable start, never an attested DFT run."""
    validate_test_environment()
    sys.path.insert(0, str(api_root / "tests"))
    from models.db import _to_async_dsn
    from services import scientific_pending_import as service
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_research_freeze import state
    from tests.test_scientific_pending_import import _finish, _rows, _start, seed_import

    engine = create_async_engine(_to_async_dsn(capability.database_url), poolclass=NullPool,
                                 isolation_level="SERIALIZABLE")
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda sync: verify_postgres_identity(sync, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            fixture = await seed_import(session)
            await session.commit()
            prepared = service.compile_input(fixture["package"])
            before = await state(session)
            preview = await service.preview_import(session, actor_user_id=fixture["actors"]["curator"],
                request_key="migrated-scientific-preview", prepared=prepared)
            assert preview["status"] == "success_pending"
            assert await state(session) == before
            started = await _start(session, fixture, request_key="migrated-scientific-start")
            await session.commit()
            durable_start = await state(session)
            assert started["status"] == "outcome_unknown"
            replay = await _start(session, fixture, request_key="migrated-scientific-start")
            assert replay["replayed"] and replay["attempt_id"] == started["attempt_id"]
            assert await state(session) == durable_start
            # A fully executed finish is still caller-owned: outer rollback must
            # retain the committed start and remove every generated/result row.
            pending = await _finish(session, fixture, started, prepared=prepared)
            assert pending["status"] == "success_pending"
            await session.rollback()
            assert await state(session) == durable_start
            inspected = await service.inspect_import(session, actor_user_id=fixture["actors"]["curator"],
                attempt_id=started["attempt_id"])
            assert inspected["status"] == "outcome_unknown" and inspected["report"] is None
            finished = await _finish(session, fixture, started, prepared=prepared)
            await session.commit()
            written = await state(session)
            assert finished["status"] == "success_pending"
            assert set(finished["row_ids"]) == {"run", "state", "structure", "event", "property"}
            assert all(finished["authority"][key] is False for key in finished["authority"])
            blobs = await _rows(session, "scientific_import_blobs", package_id=started["package_id"])
            retained = {bytes(row["payload"]) for row in blobs}
            assert {fixture["input_bytes"], fixture["frequency_bytes"], fixture["fc_bytes"]} <= retained
            replay = await _finish(session, fixture, started, prepared=prepared)
            assert replay["replayed"] and replay["outcome_id"] == finished["outcome_id"]
            await session.commit()
            assert await state(session) == written
            if recorder is not None:
                negative = await seed_import(session, missing_fc=True)
                await session.commit()
                before_quarantine = await state(session)
                negative_start = await _start(session, negative, request_key="migrated-scientific-missing-fc")
                await session.commit()
                negative_finish = await _finish(session, negative, negative_start)
                await session.commit()
                assert negative_finish["status"] == "quarantined"
                after_quarantine = await state(session)
                for name in ("research_runs", "material_states", "structure_records", "research_events", "event_properties"):
                    assert after_quarantine[name] == before_quarantine[name]
                negative_rows = await _rows(session, "scientific_import_outcomes", attempt_id=negative_start["attempt_id"])
                assert len(negative_rows) == 1 and negative_rows[0]["reason_codes"] == ["force_constants_unavailable", "validated_coordinates_unavailable"]
                assert all(negative_rows[0][name + "_id"] is None for name in ("run", "state", "structure", "event", "property"))
                _observed(recorder, "missing_force_constants_quarantined_without_scientific_rows")
            return started["attempt_id"]
    finally:
        await engine.dispose()


def _scientific_import_downgrade_guard(capability, engine, config, attempt_id):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == attempt_id for row in before["scientific_import_attempts"])
    try:
        validate_test_environment()
        command.downgrade(config, "0064_ml_feature_companion")
    except RuntimeError as exc:
        assert "scientific-import" in str(exc) and "retained source or attempt history" in str(exc)
    else:
        raise AssertionError("Nonempty scientific import source/attempt history downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _assert_result_impact_indexes(connection, *, present=True):
    from models.scientific_result_impact_indexes_v1 import INDEX_SPECS
    from sqlalchemy import text

    for name, table, columns, predicate in INDEX_SPECS:
        row = connection.execute(text("""SELECT target.relname AS table_name,am.amname AS method,
            ix.indisvalid,ix.indisready,ix.indisunique,pg_get_expr(ix.indpred,ix.indrelid) AS predicate,
            ARRAY(SELECT a.attname FROM unnest(ix.indkey) WITH ORDINALITY k(attnum,ordinal)
                  JOIN pg_attribute a ON a.attrelid=ix.indrelid AND a.attnum=k.attnum
                  WHERE k.ordinal<=ix.indnkeyatts ORDER BY k.ordinal) AS columns
            FROM pg_index ix JOIN pg_class idx ON idx.oid=ix.indexrelid
            JOIN pg_class target ON target.oid=ix.indrelid JOIN pg_am am ON am.oid=idx.relam
            JOIN pg_namespace n ON n.oid=idx.relnamespace WHERE n.nspname='public' AND idx.relname=:name"""),
            {"name": name}).mappings().one_or_none()
        if not present:
            assert row is None
            continue
        assert row is not None and row["table_name"] == table and row["method"] == "btree"
        assert tuple(row["columns"]) == columns and row["indisvalid"] and row["indisready"] and not row["indisunique"]
        assert (row["predicate"] is None) is (predicate is None)
        if predicate is not None:
            assert "derives_from" in row["predicate"] if "derives_from" in predicate else (
                columns[0] in row["predicate"] and "IS NOT NULL" in row["predicate"])


def _result_impact_indexes_roundtrip(capability, engine, config, *, populated):
    """0066 removes only indexes, both before and after every retained ledger."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public") if name not in {"alembic_version", *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_result_impact_indexes(connection)
        _assert_empty_adjudications(connection)
        before = snapshot(connection)
        if populated:
            assert before["scientific_import_outcomes"] and before["ml_feature_source_bindings"]
            assert before["research_distribution_dependencies"]
        else:
            assert all(not before[name] for name in _SCIENTIFIC_IMPORT_TABLES)
    validate_test_environment()
    command.downgrade(config, "0065_scientific_import")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_result_impact_indexes(connection, present=False)
        assert snapshot(connection) == before
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError:
            pass
        else:
            raise AssertionError("Result impact application must refuse the previous schema")
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_result_impact_indexes(connection)
        _assert_empty_adjudications(connection)
        assert snapshot(connection) == before
        if populated:
            from uuid import UUID

            from sqlalchemy.dialects import postgresql
            from tests.test_scientific_result_impact_indexes import (
                plan_nodes,
                query_statements,
            )

            example_input = next(row for row in before["ml_example_inputs"] if row["input_property_id"] is not None)
            pin = next(row for row in before["research_release_pins"] if row["table_name"] == "event_properties"
                       and row["row_id"] == example_input["input_property_id"])
            statements = query_statements(event_id=UUID(example_input["input_event_id"]),
                property_id=UUID(example_input["input_property_id"]), release_id=UUID(pin["release_id"]))
            connection.execute(text("SET LOCAL enable_seqscan=off"))
            connection.execute(text("SET LOCAL statement_timeout='5s'"))
            expected = {"ml_inputs": {"idx_sri66_ml_input_event"}, "derivations": {"idx_sri66_derivation_input_event"},
                        "objects": {"idx_sri66_distribution_object"},
                        "capsules": {f"idx_sri66_distribution_capsule_{index}" for index in range(8)}}
            for name, statement in statements.items():
                sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
                plan = connection.execute(text("EXPLAIN (FORMAT JSON) " + sql)).scalar_one()[0]["Plan"]
                assert expected[name] <= {node.get("Index Name") for node in plan_nodes(plan)}
            assert snapshot(connection) == before


def _adjudications_empty_roundtrip(capability, engine, config):
    """Remove only empty0067, after all populated independent older guards."""
    from alembic import command
    from models.scientific_adjudication_v1 import (
        ASSEMBLY_WRITER_TABLES,
        CATALOGUE_TABLES,
        FUNCTION_SIGNATURES,
    )
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_ADJUDICATION_TABLES, _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_adjudications(connection)
        before = snapshot(connection)
        assert before["scientific_import_outcomes"] and before["ml_feature_source_bindings"]
        for name, arguments in FUNCTION_SIGNATURES:
            assert connection.execute(text("SELECT to_regprocedure(:signature)"), {"signature": f"public.{name}({arguments})"}).scalar_one() is not None
    validate_test_environment()
    command.downgrade(config, "0066_result_impact_indexes")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError:
            pass
        else:
            raise AssertionError("Exact-result review application must reject previous schema")
        verify_postgres_identity(connection, capability)
        assert not set(_ADJUDICATION_TABLES) & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before
        assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname='sa67_catalogue_writer' AND NOT tgisinternal")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname='sa67_assembly_writer' AND NOT tgisinternal")).scalar_one() == 0
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_adjudications(connection)
        assert snapshot(connection) == before
        assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname='sa67_catalogue_writer' AND NOT tgisinternal")).scalar_one() == len(CATALOGUE_TABLES)
        assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname='sa67_assembly_writer' AND NOT tgisinternal")).scalar_one() == len(ASSEMBLY_WRITER_TABLES)


async def _adjudications_on_migrated_schema(capability, api_root, attempt_id):
    """Actual source-bound decisions, rollback and no-op replay; no science rewrite."""
    validate_test_environment()
    from uuid import UUID

    from models.db import _to_async_dsn
    from services import scientific_adjudication as service
    from services.schema_lifecycle import check_connection_schema
    from services.scientific_result_subject import capture_result_subject
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_research_freeze import state
    from tests.test_research_publication import actors
    from tests.test_scientific_adjudication_schema import item_for

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            await session.execute(text("SET LOCAL statement_timeout='10s'"))
            people = await actors(session)
            property_id = await session.scalar(text("SELECT property_id FROM scientific_import_outcomes WHERE attempt_id=:id AND outcome='success_pending'"), {"id": UUID(attempt_id)})
            assert property_id is not None
            captured = await capture_result_subject(session, property_id)
            subject = {"id": captured.subject_id, "property_id": property_id, "basis_json": captured.text, "subject_sha256": captured.sha256}
            item = await item_for(session, subject)
            request = {"version": "scientific-result-adjudication/1.0.0", "request_key": "migration:exact-result-review", "items": [item]}
            before = await state(session)
            preview = await service.adjudicate(session, actor_user_id=people["reviewer"], request=request)
            assert preview["database_mutated"] is False and preview["can_commit"] is True
            assert await state(session) == before
            receipt = await service.adjudicate(session, actor_user_id=people["reviewer"], request=request,
                expected_preview_sha256=preview["preview_sha256"], dry_run=False)
            await session.commit()
            await session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            await session.execute(text("SET LOCAL statement_timeout='10s'"))
            after = await state(session)
            for name in before:
                if name not in {*_ADJUDICATION_TABLES, "research_integrity_epoch", "research_publication_epoch", "source_lifecycle_epoch"}:
                    assert after[name] == before[name], name
            assert len(after["scientific_result_subjects"]) == 1
            assert len(after["scientific_adjudication_requests"]) == 1
            assert len(after["scientific_result_decisions"]) == 1
            replay = await service.adjudicate(session, actor_user_id=people["reviewer"], request=request,
                expected_preview_sha256=preview["preview_sha256"], dry_run=False)
            assert replay["replayed"] is True
            assert await state(session) == after
            assert receipt["ml_training_approved"] is False and receipt["public_release_authorized"] is False
            await session.rollback()
            return receipt["request_id"]
    finally:
        await engine.dispose()


def _adjudication_downgrade_guard(capability, engine, config, request_id):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(t) FROM public.{name} t ORDER BY to_jsonb(t)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public") if name != "alembic_version"}
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == request_id for row in before["scientific_adjudication_requests"])
    try:
        validate_test_environment()
        command.downgrade(config, "0066_result_impact_indexes")
    except RuntimeError as exc:
        assert "retained exact review history" in str(exc)
    else:
        raise AssertionError("Nonempty exact-result adjudication downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _answer_evidence_empty_roundtrip(capability, engine, config):
    """0068 alone removes no earlier history and never backfills a legacy answer."""
    from uuid import uuid4

    from alembic import command
    from models.answer_evidence_v1 import FUNCTION_SIGNATURES
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: _pre_answer_evidence_rows(connection, name)
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", _ANSWER_EVIDENCE_TABLE, *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_answer_evidence(connection)
        before = snapshot(connection)
        assert before["scientific_result_decisions"]
    validate_test_environment()
    command.downgrade(config, "0067_scientific_adjudication")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("Saved-answer application must reject the previous schema")
        verify_postgres_identity(connection, capability)
        assert _ANSWER_EVIDENCE_TABLE not in inspect(connection).get_table_names(schema="public")
        assert "evidence_receipt_version" not in {column["name"] for column in inspect(connection).get_columns("ask_history")}
        assert snapshot(connection) == before
        for name, arguments in FUNCTION_SIGNATURES:
            assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() is None
        # This row genuinely predates the new column, not a post-upgrade retrofit.
        owner_id, legacy_id = uuid4(), uuid4()
        connection.execute(text("""INSERT INTO users(id,email,name,email_verified,is_active,is_admin,is_reviewer)
            VALUES(:id,:email,'Synthetic legacy history owner',true,true,false,false)"""),
            {"id": owner_id, "email": f"migration-legacy-{owner_id}@example.test"})
        connection.execute(text("""INSERT INTO ask_history(id,user_id,question,answer,sources,tokens_used,latency_ms,language,created_at)
            VALUES(:id,:owner,'Synthetic legacy question','Unpinned historical snapshot','[]'::jsonb,NULL,7,NULL,
                   '2020-01-01T00:00:00Z'::timestamptz)"""), {"id": legacy_id, "owner": owner_id})
        before = snapshot(connection)
        connection.commit()
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_answer_evidence(connection)
        assert snapshot(connection) == before
        assert connection.execute(text("SELECT evidence_receipt_version FROM ask_history WHERE id=:id"), {"id": legacy_id}).scalar_one() is None
        for name, arguments in FUNCTION_SIGNATURES:
            assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() is not None
        assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname IN ('ae68_parent','ae68_complete',"
            "'ae68_insert','ae68_immutable','ae68_truncate') AND NOT tgisinternal")).scalar_one() == 5
    return str(legacy_id)


async def _answer_evidence_on_migrated_schema(capability, api_root, generation_id, legacy_id):
    """Real retained generation, complete response, rollback/read replay and owner cascade."""
    validate_test_environment()
    from uuid import UUID, uuid4

    import sqlalchemy as sa
    from models.answer_evidence_v1 import VERSION
    from models.db import Base, _to_async_dsn
    from models.index_read import generation_read_metadata
    from models.search import AskRequest, AskResponse, AskSource
    from services import answer_evidence as service
    from services import evidence_packing, index_retrieval, retrieval_currentness
    from services.authors import short as authors_short
    from services.index_generations import (
        load_active_generation,
        load_generation_members,
    )
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
            await session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            legacy_before = await session.scalar(sa.text("SELECT to_jsonb(h) FROM ask_history h WHERE id=:id"), {"id": UUID(legacy_id)})
            pin = await load_active_generation(session)
            assert pin["generation_id"] == generation_id
            member = (await load_generation_members(session, generation_id=generation_id))[0]
            chunk = (await index_retrieval.hydrate(session, pin, [member["vector_id"]]))[member["vector_id"]]
            evidence = (await index_retrieval.resolve_evidence(session, [chunk]))[chunk.id]
            paper = index_retrieval.attribution(chunk)
            plan = evidence_packing.pack_evidence([{"chunk_id": chunk.id, "paper_id": chunk.paper_id,
                "content_sha256": member["content_sha256"], "source_snapshot_sha256": member["source_snapshot_sha256"],
                "chunk_kind": evidence["chunk_kind"]}], cost=lambda ids: 100 + 100 * len(ids), byte_budget=4096, max_chunks=1)
            source = AskSource(index=1, paper_id=paper.id, arxiv_id=paper.arxiv_id, title=paper.title,
                authors_short=authors_short(paper.authors or []), year=paper.date_submitted.year if paper.date_submitted else None,
                section=chunk.section, snippet=service._snippet(chunk.text), evidence_provenance=evidence, packing_info=plan.selected[0])
            request = AskRequest(question="What does the retained synthetic source say?", max_sources=1, language="auto")
            response = AskResponse(answer="Retained synthetic source [1]; no scientific approval.", sources=[source],
                tokens_used=None, query_time_ms=7, retrieval_generation=generation_read_metadata(pin),
                evidence_packing=evidence_packing.public_summary(plan))
            selection = retrieval_currentness.selection_pin(chunk, material_evidence=[], source_review={}, evidence=evidence)
            capture = service.capture_inputs(request=request, generation_pin=pin, sources=(source,), chunks=(chunk,), selection_pins=(selection,))
            prepared = service.finish_capture(capture, response)
            fields = await service.receipt_fields(session, prepared)
            fields = {**fields, **{key: UUID(fields[key]) if fields[key] else None for key in ("generation_id", "activation_event_id")}}
            owner_id, history_id = uuid4(), uuid4()
            await session.execute(Base.metadata.tables["users"].insert().values(id=owner_id,
                email=f"migration-receipt-{owner_id}@example.test", name="Synthetic receipt owner", is_active=True, email_verified=True))
            await session.commit()
            history = {"id": history_id, "user_id": owner_id, "question": request.question,
                "answer": response.answer, "sources": [source.model_dump(mode="json")], "tokens_used": None,
                "latency_ms": 7, "language": "auto", "evidence_receipt_version": VERSION}

            async def append(*, receipt=True, identifier=history_id):
                await session.execute(insert(Base.metadata.tables["ask_history"]).values(**{**history, "id": identifier}).on_conflict_do_nothing(index_elements=["id"]))
                if receipt:
                    await session.execute(insert(Base.metadata.tables[_ANSWER_EVIDENCE_TABLE]).values(history_id=identifier, **fields)
                        .on_conflict_do_nothing(index_elements=["history_id"]))
                await session.execute(sa.text("SET CONSTRAINTS ae68_complete IMMEDIATE"))
                await session.execute(sa.text("SET CONSTRAINTS ae68_complete DEFERRED"))

            before = await state(session)
            try:
                async with session.begin_nested():
                    await append(receipt=False)
            except DBAPIError as exc:
                assert "complete_receipt_required" in str(exc)
            else:
                raise AssertionError("Marked history cannot commit without its exact receipt")
            assert await state(session) == before
            await append()
            await session.rollback()
            assert await state(session) == before
            await append()
            await session.commit()
            written = await state(session)
            assert len(written[_ANSWER_EVIDENCE_TABLE]) == 1
            assert next(row for row in written["ask_history"] if row["id"] == legacy_id) == legacy_before
            for name in before:
                if name not in {"ask_history", _ANSWER_EVIDENCE_TABLE}:
                    assert written[name] == before[name], name
            await append()
            await session.commit()
            assert await state(session) == written
            await session.rollback()
            await session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            await session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            stored = dict((await session.execute(sa.select(Base.metadata.tables[_ANSWER_EVIDENCE_TABLE]).where(
                Base.metadata.tables[_ANSWER_EVIDENCE_TABLE].c.history_id == history_id))).mappings().one())
            verified = await service.verify_historical(session, stored)
            assert verified["bindings"]["mode"] == "generation_bound"
            assert verified["bindings"]["items"][0]["chunk_id"] == member["vector_id"]
            assert verified["response"]["tokens_used"] is None
            assert await service.verify_historical(session, stored) == verified
            assert await state(session) == written
            await session.rollback()
            # Owner deletion is intentionally allowed, but rollback restores both rows.
            await session.execute(sa.text("DELETE FROM ask_history WHERE id=:id AND user_id=:owner"), {"id": history_id, "owner": owner_id})
            assert await session.scalar(sa.text("SELECT count(*) FROM answer_evidence_receipts WHERE history_id=:id"), {"id": history_id}) == 0
            await session.rollback()
            assert await state(session) == written
            # Also prove a durable owner-scoped deletion, without deleting the
            # retained primary receipt needed by the independent downgrade guard.
            deleted_id = uuid4()
            await append(identifier=deleted_id)
            await session.commit()
            await session.execute(sa.text("DELETE FROM ask_history WHERE id=:id AND user_id=:owner"), {"id": deleted_id, "owner": owner_id})
            await session.commit()
            assert await state(session) == written
            await session.rollback()
            return str(history_id)
    finally:
        await engine.dispose()


def _answer_evidence_downgrade_guard(capability, engine, config, history_id):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(t) FROM public.{name} t ORDER BY to_jsonb(t)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["history_id"] == history_id for row in before[_ANSWER_EVIDENCE_TABLE])
    try:
        validate_test_environment()
        command.downgrade(config, "0067_scientific_adjudication")
    except RuntimeError as exc:
        assert "retained immutable saved answers" in str(exc)
    else:
        raise AssertionError("Nonempty saved-answer downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _discovery_projection_empty_roundtrip(capability, engine, config):
    """0069 removes only its own empty tables; preserve all earlier history."""
    from alembic import command
    from models.discovery_projection_v1 import FUNCTION_SIGNATURES
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
            for name in inspect(connection).get_table_names(schema="public")
            if name not in {"alembic_version", *_DISCOVERY_PROJECTION_TABLES, _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_discovery_projections(connection)
        before = snapshot(connection)
        assert before["answer_evidence_receipts"] and before["scientific_result_decisions"]
    validate_test_environment()
    command.downgrade(config, "0068_answer_evidence")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("Discovery projection application must reject the previous schema")
        verify_postgres_identity(connection, capability)
        assert not set(_DISCOVERY_PROJECTION_TABLES) & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before
        for name, arguments in FUNCTION_SIGNATURES:
            assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() is None
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_discovery_projections(connection)
        assert snapshot(connection) == before
        for name, arguments in FUNCTION_SIGNATURES:
            assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() is not None


async def _discovery_projection_on_migrated_schema(capability, api_root):
    """Actual three-table governance history; no synthetic science approval."""
    validate_test_environment()
    import sqlalchemy as sa
    from models.db import _to_async_dsn
    from services import discovery_projection_governance as service
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_discovery_projection_governance import (
        action_args,
        register,
        review_args,
    )
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            context, arguments, registered = await register(session)
            review = await service.review_projection(session, **review_args(context, registered), dry_run=False)
            # A protective withdrawal does not need a positive scientific cell;
            # it remains possible even when publication is scientifically held.
            withdrawal = await service.projection_action(session,
                **action_args(context, registered, review, kind="withdraw"), dry_run=False)
            assert all(row["committed"] is False for row in (registered, review, withdrawal))
            await session.commit()
            await session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            before = await state(session)
            replay = await service.register_projection(session, **arguments, dry_run=False)
            assert replay["replayed"] is True and replay["id"] == registered["id"]
            outcome = await service.inspect_operation(session, actor_user_id=arguments["actor_user_id"],
                operation="register", request_key=arguments["request_key"],
                expected_request_sha256=registered["request_sha256"])
            assert outcome["id"] == registered["id"]
            assert await state(session) == before
            await session.rollback()
            return registered["package_id"]
    finally:
        await engine.dispose()


def _discovery_projection_downgrade_guard(capability, engine, config, package_id):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
            for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == package_id for row in before["discovery_projection_packages"])
        assert all(before[name] for name in _DISCOVERY_PROJECTION_TABLES)
    try:
        validate_test_environment()
        command.downgrade(config, "0068_answer_evidence")
    except RuntimeError as exc:
        assert "retained immutable governance" in str(exc)
    else:
        raise AssertionError("Nonempty Discovery projection downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _discovery_main_barrier_roundtrip(capability, engine, config, *, package_id=None):
    """0070 changes functions only; empty and v1-populated data stay exact."""
    from alembic import command
    from models.discovery_projection_v2 import (
        FUNCTION_SIGNATURES,
        frozen_insert_statement,
    )
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        # Keep every retained JSON TEXT field and record hash, including v1
        # governance. Exclude the changed Alembic marker and the independently
        # asserted-empty later ML-role table, absent at the previous head.
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
            for name in inspect(connection).get_table_names(schema="public") if name not in {"alembic_version", _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    def functions(connection):
        signatures = (*FUNCTION_SIGNATURES, ("sclib_discovery_projection_insert_v1", ""))
        return {name: connection.execute(text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
            {"signature": f"public.{name}({arguments})"}).scalar_one() for name, arguments in signatures}

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        before_functions = functions(connection)
        assert all(before_functions.values())
        _assert_empty_ml_use_roles(connection)
        if package_id is None:
            _assert_empty_discovery_projections(connection)
        else:
            assert any(row["id"] == package_id for row in before["discovery_projection_packages"])
            assert all(before[name] for name in _DISCOVERY_PROJECTION_TABLES)
        assert connection.execute(text("""SELECT count(*) FROM public.discovery_projection_packages
            WHERE payload_json::jsonb->>'version' IS DISTINCT FROM 'discovery-scientific-projection/1.0.0'
              OR selection_json::jsonb->>'version' IS DISTINCT FROM 'discovery-scientific-selection/1.0.0'""")).scalar_one() == 0
    validate_test_environment()
    command.downgrade(config, "0069_discovery_projection")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("Main-barrier application must reject the previous schema")
        verify_postgres_identity(connection, capability)
        assert connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == "0069_discovery_projection"
        assert snapshot(connection) == before
        for name, arguments in FUNCTION_SIGNATURES:
            assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() is None
        # Compare the function body stored by PostgreSQL with the exact frozen
        # 0069 definition, not a hand-written approximation of its predicates.
        expected_body = frozen_insert_statement().split("AS $$", 1)[1].rsplit("$$", 1)[0]
        assert connection.execute(text("""SELECT prosrc FROM pg_proc
            WHERE oid=to_regprocedure('public.sclib_discovery_projection_insert_v1()')""")).scalar_one() == expected_body
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == "0081_index_search"
        _assert_empty_ml_use_roles(connection)
        assert snapshot(connection) == before
        assert functions(connection) == before_functions


async def _discovery_projection_replays_on_migrated_schema(capability, package_ids):
    """Original retained request keys replay after migration without any SQL effect."""
    validate_test_environment()
    import sqlalchemy as sa
    from models.db import _to_async_dsn
    from services import discovery_projection_governance as service
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            before = await state(session)
            for package_id in package_ids:
                row = await service._package(session, package_id)
                arguments = {**service._build_arguments(row), "actor_user_id": row["actor_user_id"],
                    "request_key": row["request_key"], "expected_payload_sha256": row["payload_sha256"]}
                replay = await service.register_projection(session, **arguments, dry_run=False)
                outcome = await service.inspect_operation(session, actor_user_id=row["actor_user_id"],
                    operation="register", request_key=row["request_key"], expected_request_sha256=row["request_sha256"])
                assert replay == outcome and replay["replayed"] is True
                assert replay["id"] == str(row["id"]) and replay["record_sha256"] == row["record_sha256"]
                assert replay["payload_sha256"] == row["payload_sha256"]
                assert replay["selection_sha256"] == row["selection_sha256"]
                assert replay["request_sha256"] == row["request_sha256"]
            assert await state(session) == before
            await session.rollback()
    finally:
        await engine.dispose()


async def _discovery_main_barrier_on_migrated_schema(capability, package_id):
    """Real v2 packages over the retained synthetic v1 context, not science approval."""
    validate_test_environment()
    import json
    from copy import deepcopy
    from uuid import uuid4

    import sqlalchemy as sa
    from models.db import _to_async_dsn
    from services import discovery_projection_governance as service
    from services import discovery_scientific_projection as projection
    from services.research_priority import digest
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
            await session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
            original = await service._package(session, package_id)
            original_payload = json.loads(original["payload_json"])
            assert original_payload["version"] == projection.VERSION
            assert json.loads(original["scientific_pins_json"]) == {}
            assert all("main_barrier" not in row for row in original_payload["rows"])
            declarations = (
                {"status": "not_declared"},
                {"status": "declared", "category": "evidence_gap",
                    "statement": "Synthetic evidence gap in this selected context, not a physical obstacle.",
                    "rationale": "The retained selected band-gap cell is unknown; no scientific conclusion is inferred.",
                    "basis_refs": [{"kind": "scientific_cell", "property_key": "band_gap"}]},
            )
            packages = []
            for declaration in declarations:
                arguments = service._build_arguments(original)
                selected = arguments["selection"]
                selected["version"] = projection.SELECTION_VERSION_V2
                for choice in selected["representatives"]:
                    assert next(cell for cell in choice["cells"] if cell["property_key"] == "band_gap")["availability"] == "unknown"
                    choice["main_barrier"] = deepcopy(declaration)
                arguments.update(actor_user_id=original["actor_user_id"], request_key="synthetic-main-barrier:" + uuid4().hex,
                    expected_selection_sha256=digest(selected))
                before = await state(session)
                preview = await service.register_projection(session, **arguments)
                assert preview["dry_run"] is True and preview["committed"] is False
                assert await state(session) == before
                registered = await service.register_projection(session, **arguments,
                    expected_payload_sha256=preview["payload_sha256"], dry_run=False)
                assert registered["committed"] is False and registered["replayed"] is False
                await session.commit()
                await session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
                await session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                stored = await service._package(session, registered["package_id"])
                payload = json.loads(stored["payload_json"])
                assert payload["version"] == projection.VERSION_V2
                assert payload["selection"]["version"] == projection.SELECTION_VERSION_V2
                assert all(row["main_barrier"] == declaration for row in payload["rows"])
                assert all(choice["main_barrier"] == declaration for choice in payload["selection"]["representatives"])
                assert [{key: value for key, value in row.items() if key != "main_barrier"}
                    for row in payload["rows"]] == original_payload["rows"]
                assert all(payload[key] is False for key in projection.AUTHORITY)
                assert stored["scientific_pins_json"] == original["scientific_pins_json"]
                assert stored["public_bundle_json"] == original["public_bundle_json"]
                assert await service._package(session, package_id) == original
                packages.append(registered["package_id"])
            assert len(set(packages)) == 2
            await session.rollback()
            return tuple(packages)
    finally:
        await engine.dispose()


def _discovery_main_barrier_downgrade_guard(capability, engine, config, package_ids):
    """A v2 package forbids downgrade before any function or history is changed."""
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
            for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert len(package_ids) == 2
        assert connection.execute(text("""SELECT count(*) FROM public.discovery_projection_packages
            WHERE id::text=ANY(:ids) AND payload_json::jsonb->>'version'='discovery-scientific-projection/2.0.0'
              AND selection_json::jsonb->>'version'='discovery-scientific-selection/2.0.0'"""),
            {"ids": list(package_ids)}).scalar_one() == 2
        before_function = connection.execute(text("SELECT pg_get_functiondef('public.sclib_discovery_projection_insert_v1()'::regprocedure)")).scalar_one()
    try:
        validate_test_environment()
        command.downgrade(config, "0069_discovery_projection")
    except RuntimeError as exc:
        assert "retained immutable v2 governance" in str(exc)
    else:
        raise AssertionError("Nonempty main-barrier v2 downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before
        assert connection.execute(text("SELECT pg_get_functiondef('public.sclib_discovery_projection_insert_v1()'::regprocedure)")).scalar_one() == before_function


def _ml_use_roles_empty_roundtrip(capability, engine, config):
    """0071 starts empty and removes no pre-existing data or Discovery v2 state."""
    from alembic import command
    from models.ml_use_roles_v1 import FUNCTION_SIGNATURES
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
            for name in inspect(connection).get_table_names(schema="public")
            if name not in {"alembic_version", _ML_USE_ROLE_TABLE, *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_ml_use_roles(connection)
        before = snapshot(connection)
    validate_test_environment()
    command.downgrade(config, "0070_discovery_main_barrier")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("ML-use application must reject the previous schema")
        verify_postgres_identity(connection, capability)
        assert _ML_USE_ROLE_TABLE not in inspect(connection).get_table_names(schema="public")
        for name, arguments in FUNCTION_SIGNATURES:
            assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() is None
        assert snapshot(connection) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_ml_use_roles(connection)
        assert snapshot(connection) == before
        for name, arguments in FUNCTION_SIGNATURES:
            assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() is not None


async def _ml_use_roles_on_migrated_schema(capability):
    validate_test_environment()
    from models.db import _to_async_dsn
    from services import ml_use_access as service
    from services.research_access import ResearchAccessDenied
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_ml_use_governance import arguments, decide, no_authority
    from tests.test_research_freeze import state
    from tests.test_research_publication import actors

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert (await connection.run_sync(check_connection_schema))["status"] == "compatible"
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            people = await actors(session)
            args = arguments(people)
            first = await decide(session, args)
            revoked = await decide(session, arguments(people, action="revoke", previous=first["decision"]))
            try:
                await service.active_ml_role(session, people["member"], role="requester")
            except ResearchAccessDenied:
                pass
            else:
                raise AssertionError("Revoked ML membership must not remain active")
            last = await decide(session, arguments(people, previous=revoked["decision"]))
            await session.commit()
            before = await state(session)
            replay = await service.decide_ml_role(session, **args, dry_run=False,
                                                  expected_intent_sha256=first["intent_sha256"])
            assert replay["replayed"] and replay["decision"] == first["decision"]
            assert await state(session) == before
            await session.rollback()
            await session.execute(text("SET TRANSACTION READ ONLY"))
            recovered = await service.ml_role_outcome(session, actor_user_id=people["admin"],
                request_key=args["request_key"], expected_intent_sha256=first["intent_sha256"])
            assert recovered["decision"] == first["decision"]
            info = await service.inspect_ml_access(session, actor_user_id=people["member"])
            assert info["active_roles"] == ["requester"] and info["heads"][0]["id"] == last["decision"]["id"]
            no_authority(info)
            return [item["decision"]["id"] for item in (first, revoked, last)]
    finally:
        await engine.dispose()


def _ml_use_roles_downgrade_guard(capability, engine, config, decision_ids):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
            for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert {row["id"] for row in before[_ML_USE_ROLE_TABLE]} == set(decision_ids)
        assert len(before[_ML_USE_ROLE_TABLE]) == len(decision_ids) == 3
    try:
        validate_test_environment()
        command.downgrade(config, "0070_discovery_main_barrier")
    except RuntimeError as exc:
        assert "immutable authorization history" in str(exc)
    else:
        raise AssertionError("Nonempty ML-use membership downgrade must fail closed")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _ml_submissions_empty_roundtrip(capability, engine, config):
    from alembic import command
    from models.ml_use_submissions_v1 import FUNCTIONS
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(t) FROM public.{name} t ORDER BY to_jsonb(t)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_ML_SUBMISSION_TABLES, _ML_RIGHTS_TABLE, *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_empty_ml_submissions(connection)
        before = snapshot(connection)
    validate_test_environment()
    command.downgrade(config, "0071_ml_use_roles")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        assert not set(_ML_SUBMISSION_TABLES) & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before
        for name in FUNCTIONS:
            assert connection.execute(text("SELECT to_regprocedure(:name)"), {"name": "public." + name + "()"}).scalar_one() is None
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        _assert_empty_ml_submissions(connection)
        assert snapshot(connection) == before


async def _ml_submissions_on_migrated_schema(capability):
    """Actual SQL audit/storage/retention; fixture worker proof is a labeled double."""
    validate_test_environment()
    from models.db import _to_async_dsn
    from services import ml_use_submissions as service
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_ml_label_capture import read_snapshot, write_snapshot
    from tests.test_ml_use_submissions import lookup, prepared
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
            _, args, values = await prepared(session)
            before = await state(session)
            await service.store_submission(session, **values)
            await session.rollback()
            assert await state(session) == before
            first = await service.store_submission(session, **values)
            await session.commit()
            retained = await state(session)
            replay = await service.store_submission(session, **values)
            assert replay["replayed"] and replay["record_sha256"] == first["record_sha256"]
            assert await state(session) == retained
            await read_snapshot(session)
            assert await service.retained_inputs(session, actor_user_id=args["actor_user_id"], **lookup(values)) == args["raw"]
            await write_snapshot(session)
            purge = await service.purge_inputs(session, actor_user_id=args["actor_user_id"], **lookup(values))
            assert purge["input_state"] == "purged" and purge["record_sha256"] == first["record_sha256"]
            await session.commit()
            final = await state(session)
            assert final[_ML_SUBMISSION_TABLES[0]] == retained[_ML_SUBMISSION_TABLES[0]]
            assert not final[_ML_SUBMISSION_TABLES[1]] and final[_ML_SUBMISSION_TABLES[2]]
            return first["submission_id"]
    finally:
        await engine.dispose()


def _ml_submissions_downgrade_guard(capability, engine, config, submission_id):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(t) FROM public.{name} t ORDER BY to_jsonb(t)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = snapshot(connection)
        assert any(row["id"] == submission_id for row in before[_ML_SUBMISSION_TABLES[0]])
    try:
        validate_test_environment()
        command.downgrade(config, "0071_ml_use_roles")
    except RuntimeError as exc:
        assert "retained private audit history" in str(exc)
    else:
        raise AssertionError("Purged inputs must not permit deletion of immutable request history")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


def _ml_rights_roundtrip(capability, engine, config, *, populated=False):
    from alembic import command
    from models.ml_use_rights_v1 import FUNCTIONS
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(t) FROM public.{name} t ORDER BY to_jsonb(t)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_ML_RUN_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES} and (populated or name != _ML_RIGHTS_TABLE)}

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        count = connection.execute(text(f"SELECT count(*) FROM public.{_ML_RIGHTS_TABLE}")).scalar_one()
        _assert_empty_ml_runs(connection)
        assert (count > 0) if populated else count == 0
        before = snapshot(connection)
    validate_test_environment()
    if populated:
        try:
            command.downgrade(config, "0072_ml_use_submissions")
        except RuntimeError as exc:
            assert "retained independent review history" in str(exc)
        else:
            raise AssertionError("ML rights history downgrade must refuse")
    else:
        command.downgrade(config, "0072_ml_use_submissions")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert _ML_RIGHTS_TABLE not in inspect(connection).get_table_names(schema="public")
            assert snapshot(connection) == before
            for name in FUNCTIONS:
                assert connection.execute(text("SELECT to_regprocedure(:name)"), {"name": "public." + name + "()"}).scalar_one() is None
        validate_test_environment()
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


async def _ml_rights_on_migrated_schema(capability):
    validate_test_environment()
    from models.db import _to_async_dsn
    from services import ml_use_rights as service
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_ml_use_rights import fixture, recorded, successor
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
            _, _, _, _, _, args = await fixture(session)
            before = await state(session)
            await service.decide(session, **args)
            assert await state(session) == before
            first = await recorded(session, args)
            await session.commit()
            after = await state(session)
            replay = await service.decide(session, **args, dry_run=False, expected_intent_sha256=first["intent_sha256"])
            assert replay["replayed"] and replay["decision"] == first["decision"]
            assert await state(session) == after
            await recorded(session, successor(args, first["decision"], decision="revoke", basis_code="withdrawn", expires_epoch=None))
            await session.commit()
    finally:
        await engine.dispose()


def _ml_runs_roundtrip(capability, engine, config, *, populated=False):
    from alembic import command
    from models.ml_use_runs_v1 import FUNCTIONS
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(t) FROM public.{name} t ORDER BY to_jsonb(t)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES} and (populated or name not in _ML_RUN_TABLES)}

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        if populated:
            assert all(connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() > 0 for name in _ML_RUN_TABLES[:2])
        else:
            _assert_empty_ml_runs(connection)
        before = snapshot(connection)
    validate_test_environment()
    if populated:
        try:
            command.downgrade(config, "0073_ml_use_rights")
        except RuntimeError as exc:
            # 0075 is now the first destructive step and must preserve its bytes/audit
            # before the older 0074 guard can inspect plan/review history.
            assert "retained private bytes or purge history" in str(exc)
        else:
            raise AssertionError("ML run contract history downgrade must refuse")
    else:
        command.downgrade(config, "0073_ml_use_rights")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert not set(_ML_RUN_TABLES) & set(inspect(connection).get_table_names(schema="public"))
            assert snapshot(connection) == before
            for name in FUNCTIONS:
                assert connection.execute(text("SELECT to_regprocedure(:name)"), {"name": "public." + name + "()"}).scalar_one() is None
        validate_test_environment()
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before


async def _ml_runs_on_migrated_schema(capability):
    validate_test_environment()
    from models.db import _to_async_dsn
    from services import ml_use_runs as service
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_ml_use_runs import fixture, recorded, review_args, successor
    from tests.test_research_freeze import state

    engine = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            connection = await session.connection()
            await connection.run_sync(lambda raw: verify_postgres_identity(raw, capability))
            _, _, _, receipt, actor, args = await fixture(session)
            before = await state(session)
            await service.propose(session, **args)
            assert await state(session) == before
            first = await recorded(session, args)
            review = review_args(actor, first["plan"], receipt)
            approved = await recorded(session, review, "decision")
            await session.commit()
            after = await state(session)
            replay = await service.decide(session, **review, dry_run=False, expected_intent_sha256=approved["intent_sha256"])
            assert replay["replayed"] and replay["decision"] == approved["decision"]
            assert await state(session) == after
            await recorded(session, successor(review, approved["decision"], decision="revoke", expires_epoch=None), "decision")
            await session.commit()
            from services import ml_run_evidence
            from tests.test_ml_label_capture import read_snapshot, write_snapshot
            target = {"decision_id": approved["decision"]["id"], "decision_sha256": approved["decision"]["record_sha256"]}
            await read_snapshot(session)
            document = await ml_run_evidence.read(session, actor_user_id=actor["actor_user_id"], **target)
            assert document["text"] == review["evidence_text"] and document["decision"] == approved["decision"]
            await write_snapshot(session)
            purged = await ml_run_evidence.purge(session, actor_user_id=actor["actor_user_id"], **target)
            assert not purged["replayed"]
            await session.commit()
            after_purge = await state(session)
            assert (await ml_run_evidence.purge(session, actor_user_id=actor["actor_user_id"], **target))["replayed"]
            assert await state(session) == after_purge
    finally:
        await engine.dispose()


def _ml_evidence_legacy_roundtrip(capability, engine, config):
    """Create a synthetic approval on real 0074, then prove byte-exact 0075 retention."""
    import asyncio

    from alembic import command
    from models.db import _to_async_dsn
    from services import ml_run_evidence, ml_use_runs
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_ml_label_capture import read_snapshot
    from tests.test_ml_use_runs import fixture, plan_ref, recorded, review_args

    async def operation(mode, values=None):
        validate_test_environment()
        owned = create_async_engine(_to_async_dsn(capability.database_url), isolation_level="SERIALIZABLE", poolclass=NullPool)
        try:
            async with AsyncSession(owned, expire_on_commit=False) as session:
                await (await session.connection()).run_sync(lambda raw: verify_postgres_identity(raw, capability))
                if mode == "plan":
                    _, _, _, receipt, actor, args = await fixture(session)
                    plan = (await recorded(session, args))["plan"]
                    review = review_args(actor, plan, receipt)
                    await session.commit()
                    return review
                if mode == "legacy":
                    # The actual 0074 schema has no text table or 0075 constraint.
                    fields = {k: str(v) if k == "actor_user_id" else v for k, v in values.items() if k != "evidence_text"}
                    row = await ml_use_runs.insert(session, fields, "decision")
                    result = ml_use_runs.dto(row, "decision")
                    await session.commit()
                    return result
                await read_snapshot(session)
                observed = await ml_use_runs.inspect(session, actor_user_id=values["actor_user_id"],
                    **plan_ref({"id": values["plan_id"], "record_sha256": values["plan_sha256"]}))
                assert observed["head"] == values and observed["recorded_approval_status"] == "evidence_unavailable"
                recovered = await ml_use_runs.outcome(session, actor_user_id=values["actor_user_id"], kind="decision",
                    request_key=values["request_key"], expected_intent_sha256=values["intent_sha256"])
                assert recovered["decision"] == values and recovered["replayed"]
                try:
                    await ml_run_evidence.read(session, actor_user_id=values["actor_user_id"],
                        decision_id=values["id"], decision_sha256=values["record_sha256"])
                except ml_use_runs.RunNotObserved:
                    pass
                else:
                    raise AssertionError("Legacy approval must not manufacture retained text")
        finally:
            await owned.dispose()

    def snapshot(connection):
        return {name: connection.execute(text(f"SELECT to_jsonb(t) FROM public.{name} t ORDER BY to_jsonb(t)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")
                if name not in {"alembic_version", *_ML_RUN_EVIDENCE_TABLES, *_ML_PILOT_TABLES, _RESULT_PASSAGE_TABLE, *_LEGACY_CORPUS_TABLES}}

    review = asyncio.run(operation("plan"))
    validate_test_environment()
    command.downgrade(config, "0074_ml_use_runs")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("Current application must reject the old schema")
        verify_postgres_identity(connection, capability)
        assert not set(_ML_RUN_EVIDENCE_TABLES) & set(inspect(connection).get_table_names(schema="public"))
    legacy = asyncio.run(operation("legacy", review))
    with engine.connect() as connection:
        before = snapshot(connection)
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before
        for name in _ML_RUN_EVIDENCE_TABLES:
            assert connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one() == 0
    asyncio.run(operation("verify", legacy))


def main() -> None:
    # This must run before importing config, Alembic or any database client.
    capability = validate_test_environment()
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report_destination = None
    if args.report is not None:
        # Only the creating parent may nominate its known private report file.
        if args.report != Path(capability.manifest["root"]) / "schema-rehearsal.json":
            raise ReportError("report_must_use_owned_private_directory")
        report_destination = ReportDestination(args.report)
    recorder = Recorder(Path(__file__).resolve().parents[1], capability.manifest["backend"]) if report_destination is not None else None
    retained_before = {}
    report_document = None
    api_root = Path(__file__).resolve().parents[1] / "api"
    sys.path.insert(0, str(api_root))
    from config import Settings

    Settings.model_config = {**Settings.model_config, "env_file": None}
    from alembic import command
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(capability.database_url)
    try:
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert inspect(connection).get_table_names(schema="public") == []
        config = Config(str(api_root / "alembic.ini"))
        config.set_main_option("script_location", str(api_root / "alembic"))
        # Same capability is rechecked immediately before migration creates clients.
        validate_test_environment()
        command.upgrade(config, "0050_timeline_identity")
        # SC10 starts from the real pre-upgrade schema. Migration 0004 already
        # removed this DB default, although the ORM/writer schema later drifted.
        with engine.begin() as connection:
            verify_postgres_identity(connection, capability)
            connection.execute(text("""INSERT INTO materials
                (id, formula, formula_normalized, records, pairing_symmetry, is_unconventional, disputed, has_competing_order)
                VALUES ('mat:semantics-legacy', 'X', 'semantics-legacy',
                    '[{"tc_kelvin": 10, "has_competing_order": false}]'::jsonb, 'd-wave', true, true, false),
                    ('mat:semantics-missing', 'Y', 'semantics-missing',
                    '[{"tc_kelvin": 20}]'::jsonb, NULL, NULL, false, NULL)"""))
            assert connection.execute(text("SELECT has_competing_order FROM materials WHERE id = 'mat:semantics-missing'")).scalar_one() is None
            if recorder is not None:
                recorder.phase(connection, "legacy_seeded")
                retained_before["seeded_legacy_materials"] = _report_signature(connection, "seeded_legacy_materials")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            admission = check_connection_schema(connection)
            assert admission["status"] == "compatible" and admission["database_mutated"] is False
            verify_postgres_identity(connection, capability)
            if recorder is not None:
                recorder.phase(connection, "first_head")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            heads = set(MigrationContext.configure(connection).get_current_heads())
            assert heads == set(ScriptDirectory.from_config(config).get_heads())
            schema = inspect(connection)
            assert {"password_reset_tokens", "auth_audit_events"} <= set(schema.get_table_names())
            assert "session_version" in {c["name"] for c in schema.get_columns("users")}
            assert {"anomaly_context", "anomaly_review"} <= {c["name"] for c in schema.get_columns("materials")}
            material_columns = {column["name"]: column for column in schema.get_columns("materials")}
            assert "material_semantics" in material_columns
            assert material_columns["has_competing_order"]["default"] is None
            assert material_columns["has_competing_order"]["nullable"] is True
            assert "anomaly_policy_version" in {c["name"] for c in schema.get_columns("timeline_projection_state")}
            assert "result_metadata" in {c["name"] for c in schema.get_columns("timeline_projection_points")}
            assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname = 'scientific_correction_append_only' AND NOT tgisinternal")).scalar_one() == 1
            assert {"source_revisions", "source_captures", "claim_source_occurrences"} <= set(schema.get_table_names())
            assert {"research_import_snapshots", "research_import_occurrences", "research_import_revisions",
                    "research_import_memberships", "research_import_receipts"} <= set(schema.get_table_names())
            assert {"research_integrity_epoch", "research_releases", "research_release_pins",
                    "research_release_notices"} <= set(schema.get_table_names())
            assert {"research_publication_epoch", "research_role_grants", "research_role_revocations",
                    "research_publication_permissions", "research_publication_proposals",
                    "research_publication_reviews", "research_publication_actions"} <= set(schema.get_table_names())
            assert {"source_lifecycle_epoch", "source_lifecycle_events",
                    "source_lifecycle_reviews"} <= set(schema.get_table_names())
            assert {"source_task_epoch", "source_task_requests", "source_task_attempts"} <= set(schema.get_table_names())
            assert "background_job_cycles" in schema.get_table_names()
            assert set(_RAG_EVIDENCE_TABLES) <= set(schema.get_table_names())
            assert _ML_FEATURE_BINDING_TABLE in schema.get_table_names()
            assert set(_SCIENTIFIC_IMPORT_TABLES) <= set(schema.get_table_names())
            assert set(_ADJUDICATION_TABLES) <= set(schema.get_table_names())
            assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('sa67_insert','sa67_immutable','sa67_truncate','sa67_complete')")).scalar_one() == 11
            _assert_result_impact_indexes(connection)
            assert connection.execute(text("""SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal
                AND tgname IN ('si65_insert','si65_immutable','si65_truncate','si65_complete')""")).scalar_one() == 17
            from models.scientific_import_v1 import (
                FUNCTION_SIGNATURES as IMPORT_FUNCTION_SIGNATURES,
            )
            for name, arguments in IMPORT_FUNCTION_SIGNATURES:
                assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                    {"signature": f"public.{name}({arguments})"}).scalar_one() is not None
            assert connection.execute(text("""SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal
                AND tgrelid='public.ml_feature_source_bindings'::regclass""")).scalar_one() == 3
            from models.ml_feature_companion_v1 import FUNCTION_SIGNATURES
            for name, arguments in FUNCTION_SIGNATURES:
                assert connection.execute(text("SELECT to_regprocedure(:signature)"),
                    {"signature": f"public.{name}({arguments})"}).scalar_one() is not None
            _assert_empty_rag_evidence(connection)
            assert connection.execute(text("SELECT count(*) FROM background_job_cycles")).scalar_one() == 0
            _assert_source_impact_indexes(connection)
            assert connection.execute(text("""SELECT count(*) FROM pg_trigger
                WHERE NOT tgisinternal AND tgname LIKE 'research_import_%_immutable_%'""")).scalar_one() == 10
            assert connection.execute(text("""SELECT count(*) FROM pg_trigger
                WHERE NOT tgisinternal AND tgname IN (
                    'source_revisions_immutable_row', 'source_revisions_immutable_truncate',
                    'source_captures_immutable_row', 'source_captures_immutable_truncate',
                    'claim_source_occurrences_immutable_row', 'claim_source_occurrences_immutable_truncate')""")).scalar_one() == 6
        _result_impact_indexes_roundtrip(capability, engine, config, populated=False)
        _observed(recorder, "empty_index_roundtrip_preserved")
        with engine.begin() as connection:
            verify_postgres_identity(connection, capability)
            legacy = connection.execute(text("""SELECT records, has_competing_order, pairing_symmetry,
                is_unconventional, disputed, material_semantics FROM materials WHERE id = 'mat:semantics-legacy'""")).one()
            assert legacy == ([{"tc_kelvin": 10, "has_competing_order": False}], False, "d-wave", True, True, {})
            assert connection.execute(text("SELECT records FROM materials WHERE id = 'mat:semantics-missing'")).scalar_one() == [{"tc_kelvin": 20}]
            connection.execute(text("""INSERT INTO materials (id, formula, formula_normalized, records)
                VALUES ('mat:semantics-unknown', 'Z', 'semantics-unknown', '[]'::jsonb)"""))
            assert connection.execute(text("SELECT has_competing_order FROM materials WHERE id = 'mat:semantics-unknown'")).scalar_one() is None
            connection.execute(text("""UPDATE materials SET material_semantics =
                '{"version": "material-semantics/1.0.0", "synthetic": true}'::jsonb
                WHERE id = 'mat:semantics-legacy'"""))
        validate_test_environment()
        command.downgrade(config, "0050_timeline_identity")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert "material_semantics" not in {column["name"] for column in inspect(connection).get_columns("materials")}
            assert connection.execute(text("SELECT has_competing_order FROM materials WHERE id = 'mat:semantics-unknown'")).scalar_one() is None
            assert connection.execute(text("SELECT has_competing_order, disputed, pairing_symmetry FROM materials WHERE id = 'mat:semantics-legacy'")).one() == (False, True, "d-wave")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT material_semantics FROM materials WHERE id = 'mat:semantics-legacy'")).scalar_one() == {}
            assert connection.execute(text("SELECT has_competing_order FROM materials WHERE id = 'mat:semantics-unknown'")).scalar_one() is None
            assert connection.execute(text("SELECT records FROM materials WHERE id = 'mat:semantics-legacy'")).scalar_one() == [{"tc_kelvin": 10, "has_competing_order": False}]
            assert {column["name"]: column for column in inspect(connection).get_columns("materials")}["has_competing_order"]["default"] is None
        # Result metadata is rebuildable, but neither migration direction may
        # relabel old numeric-bucket points as current or rewrite raw evidence.
        with engine.begin() as connection:
            verify_postgres_identity(connection, capability)
            connection.execute(text("""INSERT INTO materials (id, formula, formula_normalized, records)
                VALUES ('mat:timeline-migration', 'X', 'timeline-migration', jsonb_build_array(jsonb_build_object('tc_kelvin', 0.03, 'year', 2026)))"""))
            connection.execute(text("""INSERT INTO timeline_projection_points
                (id, material_id, year, tc_kelvin, source_updated_at, result_metadata)
                VALUES (:point_id, 'mat:timeline-migration', 2026, 0.03, now(), jsonb_build_object('synthetic', true))"""),
                {"point_id": "a" * 64})
            connection.execute(text("""INSERT INTO timeline_projection_state
                (id, schema_version, source_year, source_watermark, refreshed_at, material_count, active_point_count)
                VALUES (1, 5, 2026, now(), now(), 1, 1)"""))
        validate_test_environment()
        command.downgrade(config, "0049_anomaly_review")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert "result_metadata" not in {c["name"] for c in inspect(connection).get_columns("timeline_projection_points")}
            assert connection.execute(text("SELECT schema_version FROM timeline_projection_state WHERE id = 1")).scalar_one() == 0
            assert connection.execute(text("SELECT records FROM materials WHERE id = 'mat:timeline-migration'")).scalar_one() == [{"tc_kelvin": 0.03, "year": 2026}]
        command.upgrade(config, "head")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT result_metadata FROM timeline_projection_points WHERE material_id = 'mat:timeline-migration'")).scalar_one() == {}
            assert connection.execute(text("SELECT schema_version FROM timeline_projection_state WHERE id = 1")).scalar_one() == 0
        # Empty-ledger round trip and nonempty-ledger refusal are local-only.
        # Keep the 0056 lifecycle ledger empty through all earlier downgrade
        # refusal checks: its own fail-closed guard must not mask older guards.
        validate_test_environment()
        command.downgrade(config, "0048_pressure_projection")
        command.upgrade(config, "head")
        with engine.begin() as connection:
            verify_postgres_identity(connection, capability)
            connection.execute(text("""INSERT INTO materials (id, formula, formula_normalized, records)
                VALUES ('mat:migration-synthetic', 'X', 'migration-synthetic', jsonb_build_array(jsonb_build_object('tc_kelvin', 60)))"""))
            connection.execute(text("""INSERT INTO scientific_correction_proposals
                (id, material_id, source_result_id, field, revision, source_quantity, proposed_quantity,
                 evidence_paper_id, evidence_locator, reason, reviewer_id, policy_version)
                VALUES (gen_random_uuid(), 'mat:migration-synthetic', 'legacy-result:synthetic', 'tc_kelvin', 1,
                        jsonb_build_object('raw_value', 60), jsonb_build_object('raw_value', 55), 'paper:synthetic',
                        jsonb_build_object('table', 'synthetic'), 'Synthetic migration guard only', gen_random_uuid(),
                        'anomaly-review/1.0.0')"""))
        try:
            validate_test_environment()
            command.downgrade(config, "0048_pressure_projection")
        except RuntimeError as exc:
            assert "preserve scientific correction proposals" in str(exc)
            _observed(recorder, "correction_history_downgrade_refused")
        else:
            raise AssertionError("Nonempty correction ledger downgrade must fail closed")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT count(*) FROM scientific_correction_proposals")).scalar_one() == 1
            assert connection.execute(text("SELECT records FROM materials WHERE id = 'mat:migration-synthetic'")).scalar_one() == [{"tc_kelvin": 60}]
            assert "result_metadata" in {c["name"] for c in inspect(connection).get_columns("timeline_projection_points")}
            assert "material_semantics" in {c["name"] for c in inspect(connection).get_columns("materials")}
            assert connection.execute(text("SELECT has_competing_order FROM materials WHERE id = 'mat:semantics-unknown'")).scalar_one() is None
            assert set(MigrationContext.configure(connection).get_current_heads()) == set(ScriptDirectory.from_config(config).get_heads())
        # A single unresolved synthetic source row is still evidence and must
        # prevent destructive downgrade. No public-time inference is involved.
        with engine.begin() as connection:
            verify_postgres_identity(connection, capability)
            connection.execute(text("""INSERT INTO papers (id, source, title, authors, abstract, status)
                VALUES ('synthetic:ml01-migration', 'arxiv', 'Synthetic migration guard', '{}', '', 'published')"""))
            connection.execute(text("""INSERT INTO source_revisions
                (id, paper_id, revision_key, metadata_sha256, record_sha256)
                VALUES ('2a6a3c2e-bf22-4862-8a77-dc80b89d2779', 'synthetic:ml01-migration',
                        'unresolved-fixture', :digest, :digest)"""), {"digest": "a" * 64})
        try:
            validate_test_environment()
            command.downgrade(config, "0051_material_semantics")
        except RuntimeError as exc:
            assert "registry contains records" in str(exc)
            _observed(recorder, "source_history_downgrade_refused")
        else:
            raise AssertionError("Nonempty source registry downgrade must fail closed")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT count(*) FROM source_revisions")).scalar_one() == 1
            assert connection.execute(text("SELECT source_version_public_at FROM source_revisions")).scalar_one() is None
            if recorder is not None:
                retained_before["seeded_source_revision"] = _report_signature(connection, "seeded_source_revision")
            assert set(MigrationContext.configure(connection).get_current_heads()) == set(ScriptDirectory.from_config(config).get_heads())
        with engine.begin() as connection:
            verify_postgres_identity(connection, capability)
            connection.execute(text("""INSERT INTO research_import_snapshots
                (id, export_manifest_sha256, export_manifest, dataset_version, site_git_sha,
                 database_watermark, source_alembic_revision, schema_version, paper_count,
                 material_count, chunk_count, input_record_count, license_manifest_sha256, record_sha256)
                VALUES ('2a6a3c2e-bf22-4862-8a77-dc80b89d2780', :digest, '{"synthetic": true}'::jsonb,
                        'synthetic-migration', :git, now(), '0053_research_import', 'synthetic/1',
                        0, 0, 0, 0, :digest, :digest)"""), {"digest": "b" * 64, "git": "a" * 40})
        try:
            validate_test_environment()
            command.downgrade(config, "0052_source_provenance")
        except RuntimeError as exc:
            assert "shadow history contains records" in str(exc)
            _observed(recorder, "shadow_history_downgrade_refused")
        else:
            raise AssertionError("Nonempty shadow import downgrade must fail closed")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT status FROM research_import_snapshots")).scalar_one() == "captured"
            assert connection.execute(text("SELECT count(*) FROM source_revisions")).scalar_one() == 1
            assert set(MigrationContext.configure(connection).get_current_heads()) == set(ScriptDirectory.from_config(config).get_heads())
        import asyncio
        release_id = asyncio.run(_freeze_on_migrated_schema(capability, api_root))
        if recorder is not None:
            with engine.connect() as connection:
                verify_postgres_identity(connection, capability)
                retained_before["frozen_release_and_pins"] = _report_signature(connection, "frozen_release_and_pins", release_id=release_id)
        try:
            validate_test_environment()
            command.downgrade(config, "0053_research_import")
        except RuntimeError as exc:
            assert "release history contains records" in str(exc)
            _observed(recorder, "release_history_downgrade_refused")
        else:
            raise AssertionError("Nonempty research release downgrade must fail closed")
        with engine.connect() as connection:
            assert check_connection_schema(connection)["status"] == "compatible"
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT count(*) FROM research_releases WHERE id=CAST(:id AS uuid)"),
                                      {"id": release_id}).scalar_one() == 1
        publication_id = asyncio.run(_publication_on_migrated_schema(capability, api_root))
        try:
            validate_test_environment()
            command.downgrade(config, "0054_research_release")
        except RuntimeError as exc:
            assert "governance history contains records" in str(exc)
            _observed(recorder, "publication_history_downgrade_refused")
        else:
            raise AssertionError("Nonempty research governance downgrade must fail closed")
        with engine.connect() as connection:
            assert check_connection_schema(connection)["status"] == "compatible"
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT count(*) FROM research_publication_proposals WHERE id=CAST(:id AS uuid)"),
                                      {"id": publication_id}).scalar_one() == 1
        _source_lifecycle_on_migrated_schema(capability, engine, config)
        _source_impact_indexes_on_migrated_schema(capability, engine, config)
        request_id = asyncio.run(_source_tasks_on_migrated_schema(capability, api_root))
        _source_task_downgrade_guard(capability, engine, config, request_id)
        _observed(recorder, "source_task_history_downgrade_refused")
        _background_jobs_empty_roundtrip(capability, engine, config)
        cycle_id = asyncio.run(_background_jobs_on_migrated_schema(capability, api_root))
        _background_job_downgrade_guard(capability, engine, config, cycle_id)
        _observed(recorder, "background_history_downgrade_refused")
        _rag_evidence_empty_roundtrip(capability, engine, config)
        evidence_id = asyncio.run(_rag_evidence_on_migrated_schema(capability, api_root))
        _rag_evidence_downgrade_guard(capability, engine, config, evidence_id)
        _observed(recorder, "rag_history_downgrade_refused")
        _embedding_receipts_empty_roundtrip(capability, engine, config)
        receipt_id = asyncio.run(_embedding_receipts_on_migrated_schema(capability, api_root, evidence_id))
        _embedding_receipt_downgrade_guard(capability, engine, config, receipt_id)
        _observed(recorder, "embedding_history_downgrade_refused")
        _index_generations_empty_roundtrip(capability, engine, config)
        if recorder is not None:
            with engine.connect() as connection:
                verify_postgres_identity(connection, capability)
                recorder.phase(connection, "before_read_cutover")
        generation_id = asyncio.run(_index_generations_on_migrated_schema(capability, api_root, receipt_id, recorder=recorder))
        from migration_index_search import populated_roundtrip as search_roundtrip
        search_roundtrip(capability, engine, config)
        _index_generation_downgrade_guard(capability, engine, config, generation_id)
        _observed(recorder, "generation_history_downgrade_refused")
        _distributions_empty_roundtrip(capability, engine, config)
        package_id = asyncio.run(_distributions_on_migrated_schema(capability, api_root))
        _distribution_downgrade_guard(capability, engine, config, package_id)
        _observed(recorder, "distribution_history_downgrade_refused")
        _ml_feature_bindings_empty_roundtrip(capability, engine, config)
        binding_id = asyncio.run(_ml_feature_bindings_on_migrated_schema(capability, api_root))
        _ml_feature_binding_downgrade_guard(capability, engine, config, binding_id)
        _observed(recorder, "feature_history_downgrade_refused")
        _scientific_imports_empty_roundtrip(capability, engine, config)
        attempt_id = asyncio.run(_scientific_imports_on_migrated_schema(capability, api_root, recorder=recorder))
        _scientific_import_downgrade_guard(capability, engine, config, attempt_id)
        _observed(recorder, "scientific_import_history_downgrade_refused")
        _result_impact_indexes_roundtrip(capability, engine, config, populated=True)
        _observed(recorder, "populated_index_roundtrip_preserved")
        _adjudications_empty_roundtrip(capability, engine, config)
        adjudication_id = asyncio.run(_adjudications_on_migrated_schema(capability, api_root, attempt_id))
        _adjudication_downgrade_guard(capability, engine, config, adjudication_id)
        legacy_history_id = _answer_evidence_empty_roundtrip(capability, engine, config)
        history_id = asyncio.run(_answer_evidence_on_migrated_schema(capability, api_root, generation_id, legacy_history_id))
        _answer_evidence_downgrade_guard(capability, engine, config, history_id)
        _discovery_projection_empty_roundtrip(capability, engine, config)
        _discovery_main_barrier_roundtrip(capability, engine, config)
        discovery_package_id = asyncio.run(_discovery_projection_on_migrated_schema(capability, api_root))
        _discovery_projection_downgrade_guard(capability, engine, config, discovery_package_id)
        _discovery_main_barrier_roundtrip(capability, engine, config, package_id=discovery_package_id)
        asyncio.run(_discovery_projection_replays_on_migrated_schema(capability, (discovery_package_id,)))
        barrier_package_ids = asyncio.run(_discovery_main_barrier_on_migrated_schema(capability, discovery_package_id))
        _discovery_main_barrier_downgrade_guard(capability, engine, config, barrier_package_ids)
        asyncio.run(_discovery_projection_replays_on_migrated_schema(capability, (discovery_package_id, *barrier_package_ids)))
        _ml_use_roles_empty_roundtrip(capability, engine, config)
        role_decision_ids = asyncio.run(_ml_use_roles_on_migrated_schema(capability))
        _ml_use_roles_downgrade_guard(capability, engine, config, role_decision_ids)
        _ml_submissions_empty_roundtrip(capability, engine, config)
        submission_id = asyncio.run(_ml_submissions_on_migrated_schema(capability))
        _ml_submissions_downgrade_guard(capability, engine, config, submission_id)
        _ml_rights_roundtrip(capability, engine, config)
        asyncio.run(_ml_rights_on_migrated_schema(capability))
        _ml_rights_roundtrip(capability, engine, config, populated=True)
        _ml_runs_roundtrip(capability, engine, config)
        _ml_evidence_legacy_roundtrip(capability, engine, config)
        asyncio.run(_ml_runs_on_migrated_schema(capability))
        _ml_runs_roundtrip(capability, engine, config, populated=True)
        # Populate last so the 0076 guard cannot mask an earlier history guard.
        from migration_pilot_registration import (
            empty_roundtrip,
            populated_history,
            populated_roundtrip,
        )

        empty_roundtrip(capability, engine, config)
        _observed(recorder, "pilot_empty_roundtrip_preserved")
        asyncio.run(populated_history(capability))
        _observed(recorder, "pilot_incomplete_roster_refused")
        _observed(recorder, "pilot_account_participation_verified")
        populated_roundtrip(capability, engine, config)
        _observed(recorder, "pilot_history_downgrade_refused")
        from migration_pilot_attestations import empty_roundtrip as attestation_empty
        from migration_pilot_attestations import populated as attestation_populated
        attestation_empty(capability, engine, config)
        _observed(recorder, "attestation_empty_roundtrip_preserved")
        asyncio.run(attestation_populated(capability))
        _observed(recorder, "attestation_account_declaration_verified")
        from migration_pilot_attestations import retained_history
        retained_history(capability, engine, config)
        _observed(recorder, "attestation_history_downgrade_refused")
        from migration_scientific_result_passage import empty_roundtrip as result_passage_empty
        result_passage_empty(capability, engine, config)
        _observed(recorder, "result_passage_empty_roundtrip_preserved")
        from migration_scientific_result_passage import populated as result_passage_populated, retained_history as result_passage_retained
        asyncio.run(result_passage_populated(capability))
        _observed(recorder, "result_passage_review_withdrawal_verified")
        result_passage_retained(capability, engine, config)
        _observed(recorder, "result_passage_history_downgrade_refused")
        from migration_legacy_corpus import empty_roundtrip as corpus_empty, retained_history as corpus_retained
        corpus_empty(capability, engine, config)
        corpus_retained(capability, engine, config)
        if recorder is not None:
            with engine.connect() as connection:
                verify_postgres_identity(connection, capability)
                recorder.phase(connection, "final")
                for check, before in retained_before.items():
                    recorder.retention(check, before, _report_signature(connection, check, release_id=release_id))
                report_document = recorder.finish(connection)
        print("Disposable migration head/admission, empty round trips, legacy preservation, migrated-schema freeze/publication/withdrawal, source-lifecycle bootstrap/transitions, populated-history index-only round trip, atomic source-task cache invalidation/retry/rollback, session-locked background-cycle work/rollback/replay, text-free RAG lineage/invalidation/replay, complete embedding-response receipts, retained index-generation staging/validation/CAS/rollback, exact RPS distribution/full dependency permissions/publication/withdrawal/replay, exact property feature source companions/byte verification/replay, byte-retained pending scientific imports with durable unknown starts/atomic completion/rollback/replay, result-impact index-only empty/populated roundtrips, exact-result adjudication preview/commit/replay/source preservation, immutable saved-answer atomic receipts/legacy NULL preservation/historical verification/no-op replay/owner cascade, Discovery v1 byte-exact history and replay across main-barrier empty/populated function roundtrips, explicit synthetic v2 nondeclaration/evidence-gap registration, ML membership-only grant/revoke/regrant and exact historical no-op recovery, reviewed result-passage empty-ledger preservation, and independent nonempty history rollback guards verified.")
    finally:
        engine.dispose()
    if report_destination is not None:
        try:
            report_destination.publish(report_document, internal=True)
        finally:
            report_destination.close()


if __name__ == "__main__":
    try:
        main()
    except ReportError as exc:
        print(f"Schema rehearsal report refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
