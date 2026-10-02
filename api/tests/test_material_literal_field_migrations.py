"""Owned schema roundtrips; every source/material fixture is explicitly synthetic."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import DBAPIError

from models import material_literal_fields_v1 as literal_model
from services import source_expression_intake_v2 as expressions
from tests.research_access_helpers import research_operator
from tests.test_material_field_cases import expression, retained, target
from tests.test_material_literal_field_bridge import _frozen_definitions
from tests.test_material_literal_field_bridge import literal_bridge as _literal_bridge
from tests.test_material_literal_field_contract import synthetic_literal_package
from tests.test_research_freeze import db_session as _owned_db_session
from tests.test_research_freeze import state

db_session = _owned_db_session
literal_bridge = _literal_bridge


def migration86(connection, action):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0086_material_literal_fields.py"
    spec = importlib.util.spec_from_file_location("owned_literal_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, action)()


async def literal_definitions(db):
    return (await db.execute(sa.text(
        "SELECT proname,pg_get_functiondef(p.oid) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND proname LIKE 'sclib_material_literal_%' ORDER BY proname"
    ))).all()


@pytest.mark.asyncio
async def test_0086_empty_literal_history_roundtrip_keeps_numeric_source_targets_and_frozen_functions(db_session):
    actor = await research_operator()
    material, _ = await retained(db_session)
    await expression(db_session, actor)
    await target(db_session, actor, material)
    before = await state(db_session)
    frozen = await _frozen_definitions(db_session)
    definitions = await literal_definitions(db_session)
    assert len(definitions) == len(literal_model.FUNCTION_SIGNATURES)
    connection = await db_session.connection()
    await connection.run_sync(lambda c: migration86(c, "downgrade"))
    assert not await literal_definitions(db_session)
    assert await _frozen_definitions(db_session) == frozen
    assert await state(db_session) == before
    await connection.run_sync(lambda c: migration86(c, "upgrade"))
    assert await literal_definitions(db_session) == definitions
    assert await _frozen_definitions(db_session) == frozen
    assert await state(db_session) == before


@pytest.mark.asyncio
async def test_0086_retained_literal_history_refuses_downgrade_without_mutating_any_rows(literal_bridge):
    db, actor = literal_bridge
    package = synthetic_literal_package()
    preview = await expressions.import_package(db, actor_user_id=actor["id"],
        request_key_value="synthetic:literal-migration86", package=package)
    await expressions.import_package(db, actor_user_id=actor["id"],
        request_key_value="synthetic:literal-migration86", package=package,
        dry_run=False, expected_preview_sha256=preview["preview_sha256"])
    before = await state(db)
    frozen = await _frozen_definitions(db)
    definitions = await literal_definitions(db)
    connection = await db.connection()
    with pytest.raises(DBAPIError, match="literal history retained; downgrade refused") as rejected:
        # This connection executes the DDL, so its savepoint must start now;
        # a lazy ORM savepoint on db would not surround run_sync(connection).
        async with connection.begin_nested():
            await connection.run_sync(lambda c: migration86(c, "downgrade"))
    assert rejected.value.orig.sqlstate == "55000"
    assert await literal_definitions(db) == definitions
    assert await _frozen_definitions(db) == frozen
    assert await state(db) == before
