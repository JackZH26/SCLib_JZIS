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
        command.upgrade(config, "head")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            heads = set(MigrationContext.configure(connection).get_current_heads())
            assert heads == set(ScriptDirectory.from_config(config).get_heads())
            schema = inspect(connection)
            assert {"password_reset_tokens", "auth_audit_events"} <= set(schema.get_table_names())
            assert "session_version" in {c["name"] for c in schema.get_columns("users")}
            assert {"anomaly_context", "anomaly_review"} <= {c["name"] for c in schema.get_columns("materials")}
            assert "anomaly_policy_version" in {c["name"] for c in schema.get_columns("timeline_projection_state")}
            assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname = 'scientific_correction_append_only' AND NOT tgisinternal")).scalar_one() == 1
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
            assert set(MigrationContext.configure(connection).get_current_heads()) == set(ScriptDirectory.from_config(config).get_heads())
        print("Disposable migration head, anomaly schema, empty-ledger round trip and nonempty-ledger rollback guard verified.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
