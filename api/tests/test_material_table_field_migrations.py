"""0091 roundtrips in an owned database; actual source, no scientific promotion."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import DBAPIError

from models.material_table_fields_v1 import FUNCTION_SIGNATURES
from tests.research_access_helpers import research_operator
from tests.test_material_field_cases import expression, retained, target
from tests.test_material_table_field_bridge import frozen_definitions, import_table
from tests.test_research_freeze import db_session as _owned_db_session
from tests.test_research_freeze import state

db_session = _owned_db_session


def migration91(connection, action):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0091_material_table_fields.py"
    spec = importlib.util.spec_from_file_location("owned_table_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, action)()


async def definitions(db):
    return [await db.scalar(sa.text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
            {"signature": f"public.{name}({args})"}) for name, args in FUNCTION_SIGNATURES]


@pytest.mark.asyncio
async def test_0091_empty_table_history_roundtrip_preserves_legacy_rows_and_functions(db_session):
    db = db_session
    actor = await research_operator()
    material, _ = await retained(db)
    await expression(db, actor)
    await target(db, actor, material)
    before, frozen, table = await state(db), await frozen_definitions(db), await definitions(db)
    assert all(table)
    connection = await db.connection()
    await connection.run_sync(lambda c: migration91(c, "downgrade"))
    assert not any(await definitions(db))
    assert await frozen_definitions(db) == frozen and await state(db) == before
    await connection.run_sync(lambda c: migration91(c, "upgrade"))
    assert await definitions(db) == table
    assert await frozen_definitions(db) == frozen and await state(db) == before


@pytest.mark.asyncio
async def test_0091_retained_table_history_refuses_destructive_downgrade(db_session):
    db = db_session
    actor = await research_operator()
    await import_table(db, actor)
    before, frozen, table = await state(db), await frozen_definitions(db), await definitions(db)
    connection = await db.connection()
    with pytest.raises(DBAPIError, match="table history retained; downgrade refused") as rejected:
        async with connection.begin_nested():
            await connection.run_sync(lambda c: migration91(c, "downgrade"))
    assert rejected.value.orig.sqlstate == "55000"
    assert await definitions(db) == table
    assert await frozen_definitions(db) == frozen and await state(db) == before
