"""0092 exact row/function preservation and retained-history refusal rehearsal."""


def table_names():
    from models.materials_v3 import TABLE_ORDER

    return TABLE_ORDER


def assert_empty(connection):
    from sqlalchemy import text

    for name in table_names():
        assert (
            connection.execute(
                text(f'SELECT count(*) FROM public."{name}"')
            ).scalar_one()
            == 0
        )


def empty_roundtrip(capability, engine, config):
    from alembic import command
    from sqlalchemy import inspect, text
    from migration_source_expressions import public_objects
    from test_safety import validate_test_environment, verify_postgres_identity
    from services.schema_lifecycle import check_connection_schema

    def snapshot(connection, exclude_new=False):
        connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        return {
            name: connection.execute(
                text(
                    f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text'
                )
            )
            .scalars()
            .all()
            for name in inspect(connection).get_table_names(schema="public")
            if name != "alembic_version"
            and (not exclude_new or name not in table_names())
        }

    validate_test_environment()
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        assert_empty(connection)
        before, old_rows, definitions = (
            snapshot(connection),
            snapshot(connection, True),
            public_objects(connection),
        )
        assert any(old_rows.values()), (
            "The 0092 roundtrip must retain actual preexisting rows"
        )
        old_objects = (
            {k: v for k, v in definitions[0].items() if k != "mv3_immutable_history()"},
            tuple(row for row in definitions[1] if row[0] not in table_names()),
        )
        assert {(r[0], r[1]) for r in definitions[1] if r[0] in table_names()} == {
            (name, trigger)
            for name in table_names()
            for trigger in ("mv3_immutable", "mv3_no_truncate")
        }
    command.downgrade(config, "0091_material_table_fields")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        assert (
            snapshot(connection) == old_rows
            and public_objects(connection) == old_objects
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)["status"] == "compatible"
        assert (
            snapshot(connection) == before and public_objects(connection) == definitions
        )
    print(
        "Empty 0092 roundtrip preserved every preexisting field, row, function and trigger."
    )


def retained_history(capability, engine, config):
    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from test_safety import validate_test_environment, verify_postgres_identity
    from services.schema_lifecycle import check_connection_schema

    validate_test_environment()
    with engine.begin() as connection:
        verify_postgres_identity(connection, capability)
        identifier = connection.execute(
            text("""INSERT INTO ner_source_captures
            (source_sha256,manifest_sha256,parser_version,source_version,source_license)
            VALUES (:sha,:sha,'synthetic/1','synthetic-only','synthetic') RETURNING id"""),
            {"sha": "9" * 64},
        ).scalar_one()
    with engine.begin() as connection:
        for sql in (
            "UPDATE ner_source_captures SET source_version='changed' WHERE id=:id",
            "DELETE FROM ner_source_captures WHERE id=:id",
            "TRUNCATE ner_source_captures CASCADE",
        ):
            transaction = connection.begin_nested()
            try:
                connection.execute(text(sql), {"id": identifier})
            except DBAPIError as exc:
                assert "append-only" in str(exc)
                transaction.rollback()
            else:
                transaction.rollback()
                raise AssertionError("Retained NER history mutation was allowed")
    try:
        command.downgrade(config, "0091_material_table_fields")
    except RuntimeError as exc:
        assert "retained history exists" in str(exc)
    else:
        raise AssertionError("Populated 0092 downgrade was allowed")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)["status"] == "compatible"
        assert (
            connection.execute(
                text("SELECT source_version FROM ner_source_captures WHERE id=:id"),
                {"id": identifier},
            ).scalar_one()
            == "synthetic-only"
        )
    print(
        "Retained 0092 history refused UPDATE, DELETE, TRUNCATE CASCADE and destructive downgrade."
    )
