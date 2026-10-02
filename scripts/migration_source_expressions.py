"""Empty 0083–0086 round trip on the fresh owned migration rehearsal.

The API suite retains committed expression and field-case audit history. Its
nonempty downgrade tests must keep that history; no fixture clears it. This
proof runs in the separately created migration database before either later
namespace is populated, with all earlier rehearsal rows retained.
"""
from __future__ import annotations

from migration_source_properties import FIELD_CASE_TABLES, FIELD_REVIEW_TABLES, INTAKE_V2_TABLES
from test_safety import validate_test_environment, verify_postgres_identity

TABLES = (*INTAKE_V2_TABLES, *FIELD_CASE_TABLES, *FIELD_REVIEW_TABLES)


def function_signatures():
    from models.material_field_cases_v1 import FUNCTION_SIGNATURES as FIELD_FUNCTIONS
    from models.material_field_review_v1 import FUNCTION_SIGNATURES as REVIEW_FUNCTIONS
    from models.material_literal_fields_v1 import FUNCTION_SIGNATURES as LITERAL_FUNCTIONS
    from models.source_expression_intake_v2 import FUNCTION_SIGNATURES as INTAKE_FUNCTIONS

    return (*INTAKE_FUNCTIONS, *FIELD_FUNCTIONS, *REVIEW_FUNCTIONS, *LITERAL_FUNCTIONS)


def expected_triggers():
    # Independent inventory: every frozen guard remains present, alongside the
    # finite literal dispatch and review guards added by the later revisions.
    return {
        *((table, name) for table in INTAKE_V2_TABLES
          for name in ("se83_insert", "se83_immutable", "se83_truncate")),
        *((table, name) for table in INTAKE_V2_TABLES[1:]
          for name in ("se83_complete", "aa86_profile", "se86_insert")),
        *((table, name) for table in FIELD_CASE_TABLES
          for name in ("fc84_insert", "fc84_immutable", "fc84_truncate", "aa86_profile", "fc86_insert")),
        *((table, name) for table in FIELD_REVIEW_TABLES
          for name in ("fr85_insert", "fr85_immutable", "fr85_truncate", "fr85_complete")),
    }


def snapshot(connection):
    from sqlalchemy import inspect, text

    connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    return {
        name: connection.execute(text(
            f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text')).scalars().all()
        for name in inspect(connection).get_table_names(schema="public")
        if name not in {"alembic_version", *TABLES}
    }


def objects(connection):
    from sqlalchemy import text

    functions = tuple(connection.execute(text(
        "SELECT pg_get_functiondef(to_regprocedure(:signature))"),
        {"signature": f"public.{name}({arguments})"}).scalar_one_or_none()
        for name, arguments in function_signatures())
    triggers = tuple(connection.execute(text("""SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND NOT t.tgisinternal AND c.relname=ANY(:tables)
        ORDER BY c.relname,t.tgname"""), {"tables": list(TABLES)}).all())
    return functions, triggers


def assert_empty(connection):
    from sqlalchemy import text

    for name in TABLES:
        assert connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one() == 0


def public_objects(connection):
    from sqlalchemy import text

    functions = dict(connection.execute(text("""SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' ORDER BY p.oid::regprocedure::text""")).all())
    triggers = tuple(connection.execute(text("""SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND NOT t.tgisinternal
        ORDER BY c.relname,t.tgname""")).all())
    return functions, triggers


def empty_roundtrip(capability, engine, config):
    validate_test_environment()
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()  # Admission requires a fresh transaction after identity reads.
        assert check_connection_schema(connection)["status"] == "compatible"
        assert_empty(connection)
        before, definitions = snapshot(connection), objects(connection)
        all_definitions = public_objects(connection)
        new_signatures = {connection.execute(text("SELECT to_regprocedure(:signature)::text"),
            {"signature": f"public.{name}({arguments})"}).scalar_one()
            for name, arguments in function_signatures()}
        earlier_definitions = ({key: value for key, value in all_definitions[0].items()
                                if key not in new_signatures},
                               tuple(row for row in all_definitions[1] if row[0] not in TABLES))
        assert any(before.values()), "Earlier rehearsal rows must actually be populated"
        assert all(definitions[0])
        assert {(row[0], row[1]) for row in definitions[1]} == expected_triggers()
    command.downgrade(config, "0082_source_property_pending")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("0086 API must refuse 0082 schema")
        assert not set(TABLES) & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before
        assert public_objects(connection) == earlier_definitions
        functions, triggers = objects(connection)
        assert functions == (None,) * len(definitions[0]) and not triggers
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)["status"] == "compatible"
        assert_empty(connection)
        assert snapshot(connection) == before
        assert objects(connection) == definitions
        assert public_objects(connection) == all_definitions
    print("Empty 0083–0086 round trip preserved every earlier SQL row and restored all functions/triggers.")
