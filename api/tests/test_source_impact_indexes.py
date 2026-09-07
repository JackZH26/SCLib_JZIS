"""0057 exact reverse lookup indexes, including inactive projection inventory."""
from __future__ import annotations

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import SOURCE_IMPACT_INDEXES, get_engine
from models.source_impact_indexes_v1 import INDEX_SPECS


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    engine = get_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


@pytest.mark.parametrize("name,table,column,method,operator_class", INDEX_SPECS)
async def test_exact_reverse_index_ready_and_not_partial(db_session, name, table, column, method, operator_class):
    row = (await db_session.execute(sa.text("""SELECT t.relname AS table_name,
        a.attname AS column_name, am.amname AS method, opc.opcname AS operator_class,
        i.indisvalid, i.indisready, i.indpred IS NULL AS nonpartial,
        i.indisunique, i.indnkeyatts
        FROM pg_index i JOIN pg_class ix ON ix.oid=i.indexrelid
        JOIN pg_namespace ns ON ns.oid=ix.relnamespace
        JOIN pg_class t ON t.oid=i.indrelid JOIN pg_am am ON am.oid=ix.relam
        JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=i.indkey[0]
        JOIN pg_opclass opc ON opc.oid=i.indclass[0]
        WHERE ns.nspname='public' AND ix.relname=:name"""), {"name": name})).mappings().one()
    assert (row["table_name"], row["column_name"], row["method"]) == (table, column, method)
    assert row["indisvalid"] and row["indisready"] and row["nonpartial"]
    assert row["indisunique"] is False and row["indnkeyatts"] == 1
    if operator_class:
        assert row["operator_class"] == operator_class


def test_frozen_index_declaration_adds_no_partial_or_unique_filter():
    assert set(SOURCE_IMPACT_INDEXES) == {spec[0] for spec in INDEX_SPECS}
    for name, table, column, method, operator_class in INDEX_SPECS:
        index = SOURCE_IMPACT_INDEXES[name]
        sql = str(sa.schema.CreateIndex(index).compile(dialect=dialect()))
        assert f"ON {table} USING {method}" in sql
        assert "WHERE" not in sql and "UNIQUE" not in sql and "CONCURRENTLY" not in sql
        assert list(index.columns.keys()) == [column]
        if operator_class:
            assert operator_class in sql
