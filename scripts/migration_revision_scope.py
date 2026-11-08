"""Rehearse an older exact schema without treating it as the application head."""
from contextlib import contextmanager


def pre_materials_context_tables(connection, names):
    """Only pre-0096 comparisons may omit the three demonstrably empty tables.

    Never use this for current-head or refused-downgrade snapshots. No scientific
    row, hash or field is projected away; populated history fails immediately.
    """
    from sqlalchemy import text
    added = {"sample_compositions", "research_protocols", "sample_relations"}
    for name in added.intersection(names):
        assert not connection.execute(text(f"SELECT EXISTS(SELECT 1 FROM public.{name})")).scalar_one(), \
            "Retained Materials context cannot enter a pre-0096 comparison"
    return [name for name in names if name not in added]


def pre_claim_review_rows(name, rows):
    """Compare legacy rows across 0095's *absent vs NULL* additive column.

    Use only for a historical boundary which predates claim review. Never
    erase a populated claim target or relax any legacy value/hash comparison.
    Current-head and refused-downgrade full snapshots keep every column.
    """
    if name not in {"scientific_result_subjects", "scientific_result_decisions"}:
        return rows
    result = []
    for row in rows:
        if "claim_id" in row:
            assert row["claim_id"] is None, "Claim review history cannot enter a pre-0095 comparison"
            assert row.get("property_id") is not None, "Legacy review must retain its property target"
            if name == "scientific_result_subjects":
                assert row["subject_version"] == "scientific-result-subject/1.0.0"
            row = {key: value for key, value in row.items() if key != "claim_id"}
        result.append(row)
    import json
    return sorted(result, key=lambda row: json.dumps(row, sort_keys=True))


def assert_revision(connection, revision):
    from alembic.migration import MigrationContext

    assert set(MigrationContext.configure(connection).get_current_heads()) == {revision}


@contextmanager
def at_revision(capability, engine, config, revision):
    from alembic import command
    from migration_source_expressions import public_objects
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text
    from test_safety import validate_test_environment, verify_postgres_identity

    def complete_snapshot():
        validate_test_environment()
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            connection.rollback()
            assert check_connection_schema(connection)["status"] == "compatible"
            connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            rows = {name: connection.execute(text(
                f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text'
            )).scalars().all() for name in inspect(connection).get_table_names(schema="public")
                if name != "alembic_version"}
            return rows, public_objects(connection)

    before = complete_snapshot()
    # Later migrations enforce their own retained-history refusal. No ledger is
    # emptied and no function/trigger is excluded from the outer comparison.
    command.downgrade(config, revision)
    try:
        yield
    finally:
        validate_test_environment()
        command.upgrade(config, "head")
        assert complete_snapshot() == before
