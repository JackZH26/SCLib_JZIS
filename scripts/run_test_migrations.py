"""Guarded migration integration test, not a production migration entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from test_safety import validate_test_environment, verify_postgres_identity


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
    """0057 may drop/recreate its indexes while retaining populated history."""
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    def snapshot(connection):
        # Local synthetic database only: compare every application table row,
        # including historical capsule bytes and lifecycle/source identities.
        return {name: connection.execute(text(f"SELECT to_jsonb(item) FROM public.{name} item ORDER BY to_jsonb(item)::text")).scalars().all()
                for name in inspect(connection).get_table_names(schema="public")
                if name != "alembic_version"}

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        _assert_source_impact_indexes(connection)
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


def main() -> None:
    # This must run before importing config, Alembic or any database client.
    capability = validate_test_environment()
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
        command.upgrade(config, "head")
        with engine.connect() as connection:
            admission = check_connection_schema(connection)
            assert admission["status"] == "compatible" and admission["database_mutated"] is False
            verify_postgres_identity(connection, capability)
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
            _assert_source_impact_indexes(connection)
            assert connection.execute(text("""SELECT count(*) FROM pg_trigger
                WHERE NOT tgisinternal AND tgname LIKE 'research_import_%_immutable_%'""")).scalar_one() == 10
            assert connection.execute(text("""SELECT count(*) FROM pg_trigger
                WHERE NOT tgisinternal AND tgname IN (
                    'source_revisions_immutable_row', 'source_revisions_immutable_truncate',
                    'source_captures_immutable_row', 'source_captures_immutable_truncate',
                    'claim_source_occurrences_immutable_row', 'claim_source_occurrences_immutable_truncate')""")).scalar_one() == 6
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
        else:
            raise AssertionError("Nonempty source registry downgrade must fail closed")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT count(*) FROM source_revisions")).scalar_one() == 1
            assert connection.execute(text("SELECT source_version_public_at FROM source_revisions")).scalar_one() is None
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
        else:
            raise AssertionError("Nonempty shadow import downgrade must fail closed")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT status FROM research_import_snapshots")).scalar_one() == "captured"
            assert connection.execute(text("SELECT count(*) FROM source_revisions")).scalar_one() == 1
            assert set(MigrationContext.configure(connection).get_current_heads()) == set(ScriptDirectory.from_config(config).get_heads())
        import asyncio
        release_id = asyncio.run(_freeze_on_migrated_schema(capability, api_root))
        try:
            validate_test_environment()
            command.downgrade(config, "0053_research_import")
        except RuntimeError as exc:
            assert "release history contains records" in str(exc)
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
        else:
            raise AssertionError("Nonempty research governance downgrade must fail closed")
        with engine.connect() as connection:
            assert check_connection_schema(connection)["status"] == "compatible"
            verify_postgres_identity(connection, capability)
            assert connection.execute(text("SELECT count(*) FROM research_publication_proposals WHERE id=CAST(:id AS uuid)"),
                                      {"id": publication_id}).scalar_one() == 1
        _source_lifecycle_on_migrated_schema(capability, engine, config)
        _source_impact_indexes_on_migrated_schema(capability, engine, config)
        print("Disposable migration head/admission, empty round trips, legacy preservation, migrated-schema freeze/publication/withdrawal, source-lifecycle bootstrap/transitions, populated-history index-only round trip and independent nonempty history rollback guards verified.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
