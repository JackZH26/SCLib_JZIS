"""Read-only API admission and an explicit, serialized migration job.

No application settings, dotenv files, cloud clients or application startup are
imported here. Migration credentials belong to the one-shot job, not the API.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.pool import NullPool

from alembic import command

# Shared by every online Alembic command and every startup checker. A session
# lock survives 0043's autocommit block; a transaction lock would not.
MIGRATION_LOCK_KEY = 0x53434C4942
API_ROOT = Path(__file__).resolve().parents[1]


class SchemaLifecycleError(RuntimeError):
    """Fail-closed operational error; messages never contain credentials."""


def alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def expected_heads() -> tuple[str, ...]:
    heads = tuple(sorted(ScriptDirectory.from_config(alembic_config()).get_heads()))
    if len(heads) != 1:
        raise SchemaLifecycleError("The application must declare one unambiguous schema head.")
    return heads


def sync_url(value: str) -> URL:
    try:
        url = make_url(value)
        if url.drivername not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg2"}:
            raise ValueError
        if not url.database or not url.host:
            raise ValueError
        return url.set(drivername="postgresql+psycopg2")
    except Exception:
        raise SchemaLifecycleError("A valid PostgreSQL database URL is required.") from None


def acquire_migration_lock(connection: Connection) -> None:
    """Acquire once on a dedicated NullPool session; its close releases the lock.

    Fail immediately instead of queueing a second upgrader. Commit the lock-only
    transaction before Alembic starts, so SQLAlchemy autobegin cannot cause it
    to mistake the migration transaction for an externally managed transaction.
    """
    if connection.in_transaction():
        raise SchemaLifecycleError("Migration locking requires a fresh connection.")
    acquired = connection.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
    ).scalar_one()
    connection.commit()
    if acquired is not True:
        raise SchemaLifecycleError("Another schema operation is active; retry the entire migration job later.")


def check_connection_schema(connection: Connection) -> dict:
    """Read-only, transaction-scoped admission; creates no version table.

    Exact equality is deliberate: no untested range or unknown newer schema is
    considered compatible. This does not certify table contents or migration
    history; migrations and staging parity remain separate release gates.
    """
    if connection.in_transaction():
        raise SchemaLifecycleError("Schema admission requires a fresh connection.")
    expected = expected_heads()
    with connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        acquired = connection.execute(
            text("SELECT pg_try_advisory_xact_lock_shared(:key)"), {"key": MIGRATION_LOCK_KEY}
        ).scalar_one()
        if acquired is not True:
            raise SchemaLifecycleError("A schema migration is active; API admission is blocked.")
        current = tuple(sorted(MigrationContext.configure(
            connection, opts={"version_table_schema": "public"}
        ).get_current_heads()))
        if current != expected:
            raise SchemaLifecycleError("Database schema is not the exact revision required by this API image.")
    return {"status": "compatible", "schema_heads": list(current), "database_mutated": False}


async def check_application_schema(engine) -> dict:
    """Use the application's async connection without modifying schema/data."""
    try:
        async with asyncio.timeout(10):
            async with engine.connect() as connection:
                return await connection.run_sync(check_connection_schema)
    except TimeoutError:
        raise SchemaLifecycleError("Schema admission timed out; API startup is blocked.") from None


def _database_url(*, migration: bool) -> str:
    secret_path = os.environ.get("SCLIB_MIGRATION_DATABASE_URL_FILE") if migration else None
    if secret_path:
        try:
            path = Path(secret_path)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 16384:
                raise ValueError
            value = path.read_text(encoding="utf-8").strip()
            if "\n" in value or "\r" in value:
                raise ValueError
            return value
        except Exception:
            raise SchemaLifecycleError("The dedicated migration credential file is unavailable or invalid.") from None
    value = os.environ.get("DATABASE_URL", "")
    if not value:
        raise SchemaLifecycleError("An explicit database credential is required; dotenv files are not loaded.")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "migrate"))
    args = parser.parse_args(argv)
    try:
        value = _database_url(migration=args.operation == "migrate")
        url = sync_url(value)
        if args.operation == "migrate":
            # This process is the dedicated job. env.py applies the same lock
            # even when an operator invokes Alembic directly instead.
            os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
            command.upgrade(alembic_config(), "head")
        engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as connection:
                result = check_connection_schema(connection)
        finally:
            engine.dispose()
        if args.operation == "migrate":
            result = {**result, "status": "migration_complete", "database_mutated": True}
        print(json.dumps(result, sort_keys=True))
        return 0
    except SchemaLifecycleError as exc:
        print(f"Schema lifecycle check failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # Driver/Alembic tracebacks can contain DSNs, SQL parameters or records.
        print("Schema lifecycle operation failed; inspect restricted database logs before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
