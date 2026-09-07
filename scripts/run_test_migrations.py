"""Guarded migration integration test, not a production migration entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from test_safety import validate_test_environment, verify_postgres_identity


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
        print("Disposable migration head, material-semantics/NULL-default and Timeline metadata round trips, raw/governance preservation, correction-ledger and source-registry rollback guards verified.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
