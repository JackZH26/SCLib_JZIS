"""Native planner-path checks, not a production latency or lock-budget claim."""
from __future__ import annotations

from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from models.db import SCIENTIFIC_RESULT_IMPACT_INDEXES, Base
from models.scientific_result_impact_indexes_v1 import INDEX_SPECS
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as db_session
from tests.test_scientific_result_impact import distribution_context, inspect


def plan_nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from plan_nodes(child)


def query_statements(*, event_id, property_id, release_id):
    """The actual collector's four reverse predicates and narrow projections."""
    inputs, examples, datasets = (Base.metadata.tables[name] for name in
                                 ("ml_example_inputs", "ml_examples", "ml_dataset_snapshots"))
    evidence = Base.metadata.tables["event_evidence"]
    dependencies = Base.metadata.tables["research_distribution_dependencies"]
    selected = sa.values(sa.column("table_name", sa.String(100)), sa.column("row_id", sa.String(200)),
                         name="scientific_impact_objects").data([("event_properties", str(property_id))])
    capsule_columns = [dependencies.c[f"capsule_release_{index}"] for index in range(8)]
    return {
        "ml_inputs": sa.select(inputs.c.id, inputs.c.input_property_id, inputs.c.input_event_id,
            examples.c.id, datasets.c.id).select_from(inputs.join(examples, examples.c.id == inputs.c.example_id)
            .join(datasets, datasets.c.id == examples.c.dataset_snapshot_id)).where(inputs.c.input_event_id == event_id).limit(1001),
        "derivations": sa.select(evidence.c.id, evidence.c.event_id, evidence.c.input_property_id)
            .where(evidence.c.input_event_id == event_id, evidence.c.link_type == "derives_from").limit(1001),
        "objects": sa.select(dependencies.c.id, dependencies.c.package_id, dependencies.c.table_name, dependencies.c.row_id)
            .select_from(dependencies.join(selected, sa.and_(dependencies.c.table_name == selected.c.table_name,
                dependencies.c.row_id == selected.c.row_id))).limit(1001),
        "capsules": sa.select(dependencies.c.id, dependencies.c.package_id, *capsule_columns)
            .where(sa.or_(*(column.in_([release_id]) for column in capsule_columns))).limit(1001),
    }


async def explain(db, statement):
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    return (await db.execute(sa.text("EXPLAIN (ANALYZE, FORMAT JSON, BUFFERS) " + sql))).scalar_one()[0]


@pytest.mark.parametrize("name,table,columns,predicate", INDEX_SPECS)
async def test_all_exact_reverse_indexes_are_ready_nonunique_btrees(db_session, name, table, columns, predicate):
    row = (await db_session.execute(sa.text("""SELECT target.relname AS table_name, am.amname AS method,
        ix.indisvalid,ix.indisready,ix.indisunique,pg_get_expr(ix.indpred,ix.indrelid) AS predicate,
        ARRAY(SELECT a.attname FROM unnest(ix.indkey) WITH ORDINALITY k(attnum,ordinal)
              JOIN pg_attribute a ON a.attrelid=ix.indrelid AND a.attnum=k.attnum
              WHERE k.ordinal<=ix.indnkeyatts ORDER BY k.ordinal) AS columns
        FROM pg_index ix JOIN pg_class idx ON idx.oid=ix.indexrelid
        JOIN pg_class target ON target.oid=ix.indrelid JOIN pg_am am ON am.oid=idx.relam
        JOIN pg_namespace n ON n.oid=idx.relnamespace WHERE n.nspname='public' AND idx.relname=:name"""),
        {"name": name})).mappings().one()
    assert row["table_name"] == table and row["method"] == "btree"
    assert tuple(row["columns"]) == columns
    assert row["indisvalid"] is row["indisready"] is True and row["indisunique"] is False
    if predicate is None:
        assert row["predicate"] is None
    else:
        assert row["predicate"] is not None
        assert ("derives_from" in row["predicate"] and "link_type" in row["predicate"]) if "derives_from" in predicate else (
            columns[0] in row["predicate"] and "IS NOT NULL" in row["predicate"])


def test_additive_declarations_change_no_columns_unique_constraints_or_frozen_specs():
    from models.research_release_v1 import ALLOWED_TABLES
    from services.research_release_spec import SPEC
    assert len(INDEX_SPECS) == 11
    assert set(SCIENTIFIC_RESULT_IMPACT_INDEXES) == {spec[0] for spec in INDEX_SPECS}
    assert set(ALLOWED_TABLES) == set(SPEC)
    for name, table, columns, predicate in INDEX_SPECS:
        index = SCIENTIFIC_RESULT_IMPACT_INDEXES[name]
        sql = str(sa.schema.CreateIndex(index).compile(dialect=postgresql.dialect()))
        assert f"ON {table} USING btree" in sql
        assert "UNIQUE" not in sql and "CONCURRENTLY" not in sql
        assert list(index.columns.keys()) == list(columns)
        assert ("WHERE" in sql) is (predicate is not None)


async def test_actual_collector_reverse_queries_have_all_needed_paths_and_preserve_rows(db_session):
    context = await distribution_context(db_session)
    fixture = context["shared"]["source"]
    # Add the output before the input event is frozen in a separate source to
    # retain genuine derives_from rows without modifying any pinned old row.
    output = await add(db_session, "research_events", material_id=fixture["material"], state_id=fixture["state"],
        event_type="curation", knowledge_origin="Inferred", record_sha256="d" * 64)
    await add(db_session, "event_evidence", event_id=output["id"], link_type="derives_from",
        input_event_id=fixture["event"], input_property_id=fixture["children"]["property"])
    before = await state(db_session)
    report = await inspect(db_session, fixture)
    statements = query_statements(event_id=UUID(str(fixture["event"])),
        property_id=UUID(str(fixture["children"]["property"])), release_id=UUID(context["shared"]["capsule"]["release_id"]))
    # Tiny fixtures correctly prefer sequential scans by default. Disabling
    # that preference tests available access paths, not real-corpus speed.
    await db_session.execute(sa.text("SET LOCAL enable_seqscan=off"))
    expected = {"ml_inputs": {"idx_sri66_ml_input_event"}, "derivations": {"idx_sri66_derivation_input_event"},
                "objects": {"idx_sri66_distribution_object"},
                "capsules": {f"idx_sri66_distribution_capsule_{index}" for index in range(8)}}
    plans = {}
    for key, statement in statements.items():
        plans[key] = await explain(db_session, statement)
        nodes = list(plan_nodes(plans[key]["Plan"]))
        assert expected[key] <= {node.get("Index Name") for node in nodes}
        assert plans[key]["Plan"]["Actual Rows"] > 0
    assert "BitmapOr" in {node["Node Type"] for node in plan_nodes(plans["capsules"]["Plan"])}
    # Removing any one capsule branch leaves that OR predicate without a
    # complete bitmap-index path. The nested rollback restores the index.
    nested = await db_session.begin_nested()
    try:
        await db_session.execute(sa.text("DROP INDEX idx_sri66_distribution_capsule_7"))
        missing = await explain(db_session, statements["capsules"])
        assert "Seq Scan" in {node["Node Type"] for node in plan_nodes(missing["Plan"])}
    finally:
        await nested.rollback()
    assert await inspect(db_session, fixture) == report
    assert await state(db_session) == before


async def test_each_reverse_index_can_be_removed_and_rebuilt_without_rewriting_rows(db_session):
    before = await state(db_session)
    connection = await db_session.connection()
    for index in reversed(tuple(SCIENTIFIC_RESULT_IMPACT_INDEXES.values())):
        await connection.run_sync(lambda sync, current=index: current.drop(sync))
    for index in SCIENTIFIC_RESULT_IMPACT_INDEXES.values():
        await connection.run_sync(lambda sync, current=index: current.create(sync))
    assert await state(db_session) == before
