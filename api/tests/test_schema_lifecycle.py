"""Guarded PostgreSQL schema admission/locking; no real migration credential.

The API fixture creates model tables, not a migrated database. A temporary
version table below supplies synthetic admission states only. The separate
guarded migration runner verifies the actual Alembic upgrade to head.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from alembic import command
from models.db import get_engine
from services.schema_lifecycle import (
    MIGRATION_LOCK_KEY,
    SchemaLifecycleError,
    acquire_migration_lock,
    alembic_config,
    check_application_schema,
    check_connection_schema,
    expected_heads,
)


@pytest.fixture
async def schema_engine():
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE public.alembic_version (version_num varchar(100) PRIMARY KEY)"))
        await connection.execute(text("INSERT INTO public.alembic_version VALUES (:head)"), {"head": expected_heads()[0]})
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE public.alembic_version"))
        await engine.dispose()


async def test_exact_schema_admission_is_read_only(schema_engine, monkeypatch):
    statements = []
    from sqlalchemy import event

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(schema_engine.sync_engine, "before_cursor_execute", record)
    try:
        result = await check_application_schema(schema_engine)
    finally:
        event.remove(schema_engine.sync_engine, "before_cursor_execute", record)
    assert result == {"status": "compatible", "schema_heads": list(expected_heads()), "database_mutated": False}
    assert all(statement.lstrip().upper().startswith(("SELECT", "SET")) for statement in statements)
    assert "SET TRANSACTION READ ONLY" in statements


@pytest.mark.parametrize("heads", [[], ["unknown-future"], ["0052_source_provenance"], ["head-one", "head-two"]])
async def test_incompatible_missing_or_multiple_heads_fail(schema_engine, heads):
    async with schema_engine.begin() as connection:
        await connection.execute(text("DELETE FROM public.alembic_version"))
        for head in heads:
            await connection.execute(text("INSERT INTO public.alembic_version VALUES (:head)"), {"head": head})
    with pytest.raises(SchemaLifecycleError, match="exact revision"):
        await check_application_schema(schema_engine)
    async with schema_engine.connect() as connection:
        assert set((await connection.execute(text("SELECT version_num FROM public.alembic_version"))).scalars()) == set(heads)


async def test_uninitialized_database_is_not_stamped(schema_engine):
    async with schema_engine.begin() as connection:
        await connection.execute(text("DROP TABLE public.alembic_version"))
    try:
        with pytest.raises(SchemaLifecycleError, match="exact revision"):
            await check_application_schema(schema_engine)
        async with schema_engine.connect() as connection:
            assert (await connection.execute(text("SELECT to_regclass('public.alembic_version')"))).scalar_one() is None
    finally:
        async with schema_engine.begin() as connection:
            await connection.execute(text("CREATE TABLE public.alembic_version (version_num varchar(100) PRIMARY KEY)"))


async def test_session_lock_serializes_manual_alembic_and_api_admission(schema_engine):
    async with schema_engine.connect() as owner:
        await owner.run_sync(acquire_migration_lock)
        # A second transaction commit cannot release the session lock.
        await owner.execute(text("SELECT 1"))
        await owner.commit()
        async with schema_engine.connect() as contender:
            with pytest.raises(SchemaLifecycleError, match="Another schema operation"):
                await contender.run_sync(acquire_migration_lock)
        with pytest.raises(SchemaLifecycleError, match="migration is active"):
            await check_application_schema(schema_engine)
        with pytest.raises(SchemaLifecycleError, match="Another schema operation"):
            await asyncio.to_thread(command.upgrade, alembic_config(), "head")
    # NullPool physically closes the owner, releasing the session lock.
    assert (await check_application_schema(schema_engine))["status"] == "compatible"


async def test_failed_migration_body_releases_lock_on_connection_close(schema_engine):
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        async with schema_engine.connect() as connection:
            await connection.run_sync(acquire_migration_lock)
            raise RuntimeError("synthetic migration failure")
    async with schema_engine.connect() as contender:
        await contender.run_sync(acquire_migration_lock)
        assert (await contender.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})).scalar_one() is True


async def test_api_admission_cannot_reuse_a_caller_transaction(schema_engine):
    async with schema_engine.begin() as connection:
        with pytest.raises(SchemaLifecycleError, match="fresh connection"):
            await connection.run_sync(check_connection_schema)


async def test_direct_lifespan_blocks_before_background_writers(monkeypatch):
    import main
    import services.schema_lifecycle as lifecycle

    spawned = []
    async def rejected(_):
        raise SchemaLifecycleError("Synthetic incompatible schema")
    monkeypatch.setattr(lifecycle, "check_application_schema", rejected)
    monkeypatch.setattr(main.asyncio, "create_task", lambda *args, **kwargs: spawned.append(args))
    with pytest.raises(SchemaLifecycleError, match="incompatible"):
        async with main.lifespan(main.app):
            pytest.fail("A mismatched application must never finish startup")
    assert spawned == []


@pytest.mark.parametrize("url", ["", "sqlite:///tmp/test", "postgresql://user:SECRET@/db", "mysql://user:SECRET@host/db"])
def test_invalid_urls_are_rejected_without_credentials(url):
    from services.schema_lifecycle import sync_url
    with pytest.raises(SchemaLifecycleError) as failure:
        sync_url(url)
    assert "SECRET" not in str(failure.value)


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+asyncpg", "postgresql+psycopg2"])
def test_url_translation_preserves_escaped_password(driver):
    from services.schema_lifecycle import sync_url
    url = sync_url(f"{driver}://user:p%40ss%25word@localhost/test")
    assert url.drivername == "postgresql+psycopg2"
    assert url.password == "p@ss%word"


def test_production_migration_secret_has_no_runtime_fallback(monkeypatch, tmp_path):
    from services.schema_lifecycle import _database_url
    secret = tmp_path / "migration-url"
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime:runtime@localhost/test")
    monkeypatch.setenv("SCLIB_MIGRATION_DATABASE_URL_FILE", str(secret))
    with pytest.raises(SchemaLifecycleError, match="credential file"):
        _database_url(migration=True)
    secret.write_text("postgresql://migrator:private@localhost/test\n")
    assert _database_url(migration=True) == "postgresql://migrator:private@localhost/test"
    assert _database_url(migration=False) == "postgresql://runtime:runtime@localhost/test"


@pytest.mark.parametrize("content", ["", "x" * 16385, "postgresql://secret@host/test\nextra"])
def test_malformed_migration_file_fails_closed(monkeypatch, tmp_path, content):
    from services.schema_lifecycle import _database_url
    secret = tmp_path / "migration-url"
    secret.write_text(content)
    monkeypatch.setenv("SCLIB_MIGRATION_DATABASE_URL_FILE", str(secret))
    with pytest.raises(SchemaLifecycleError, match="credential file"):
        _database_url(migration=True)


def test_check_cli_does_not_migrate_and_sanitizes_driver_failure(monkeypatch, capsys):
    import services.schema_lifecycle as lifecycle
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime:SECRET@localhost/test")
    monkeypatch.setattr(lifecycle.command, "upgrade", lambda *args: pytest.fail("check cannot migrate"))
    def unavailable(*args, **kwargs):
        raise RuntimeError("SECRET driver failure")
    monkeypatch.setattr(lifecycle, "create_engine", unavailable)
    assert lifecycle.main(["check"]) == 1
    output = capsys.readouterr()
    assert "SECRET" not in output.out + output.err
