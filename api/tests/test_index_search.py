"""Real owned PostgreSQL ranking parity and derived-document integrity."""

from datetime import date
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, get_session_factory
from services.retrieval import lexical_search
from tests.index_generation_fixtures import ApsArticleMeta, write_generation


async def test_projection_matches_original_rank_filters_and_current_retraction(monkeypatch):
    meta = ApsArticleMeta(doi="10.0000/Search." + uuid4().hex,
        title="Synthetic superconductivity generation", authors=["Synthetic Fixture"],
        abstract="Synthetic abstract.", date_published=date(2024, 5, 1))
    meta, _, pin = await write_generation(monkeypatch, logical_index="search-" + uuid4().hex, meta=meta)
    # A second generation must never leak into this pinned ranking.
    await write_generation(monkeypatch, logical_index="other-search-" + uuid4().hex)
    old = sa.text("""SELECT m.vector_id,
      ts_rank_cd(to_tsvector('english'::regconfig,coalesce(m.snapshot_json->>'title','')||' '||
        (m.snapshot_json->>'text')),websearch_to_tsquery('english'::regconfig,:query)) AS rank
      FROM index_generation_members m JOIN papers p ON p.id=m.paper_id
      WHERE m.generation_id=:generation
        AND to_tsvector('english'::regconfig,coalesce(m.snapshot_json->>'title','')||' '||
          (m.snapshot_json->>'text')) @@ websearch_to_tsquery('english'::regconfig,:query)
        AND (NOT :exclude OR p.status<>'retracted')
        AND (CAST(:year AS integer) IS NULL OR (m.snapshot_json->>'year')::integer>=:year)
      ORDER BY rank DESC,m.vector_id LIMIT 3""")
    async with get_session_factory()() as db:
        for query in ("superconductivity", '"old snapshot"', "old OR impossible", "old -snapshot"):
            for year in (None, 2020, 2099):
                expected = (await db.execute(old, {"generation": pin["generation_id"],
                    "query": query, "year": year, "exclude": True})).all()
                actual = await lexical_search(db, query, limit=3, generation_id=pin["generation_id"], year_min=year)
                assert [(row.chunk_id, row.score) for row in actual] == [(row.vector_id, row.rank) for row in expected]
        await db.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"), {"id": meta.paper_id})
        assert not await lexical_search(db, "superconductivity", limit=3, generation_id=pin["generation_id"])
        assert len(await lexical_search(db, "superconductivity", limit=3,
            generation_id=pin["generation_id"], exclude_retracted=False)) == 3
        await db.rollback()


async def test_backfill_keeps_parent_rows_hashes_and_exact_documents(monkeypatch):
    _, _, pin = await write_generation(monkeypatch, logical_index="backfill-" + uuid4().hex)
    table = Base.metadata.tables["index_generation_search"]
    async with get_session_factory()() as db:
        original = (await db.execute(sa.text("SELECT to_jsonb(m) FROM index_generation_members m "
            "WHERE generation_id=:id ORDER BY vector_id"), {"id": pin["generation_id"]})).scalars().all()
        connection = await db.connection()
        await connection.run_sync(lambda c: table.drop(c))
        await connection.run_sync(lambda c: table.create(c))
        assert (await db.execute(sa.text("SELECT to_jsonb(m) FROM index_generation_members m "
            "WHERE generation_id=:id ORDER BY vector_id"), {"id": pin["generation_id"]})).scalars().all() == original
        row = (await db.execute(sa.text("""SELECT count(*),bool_and(s.vector_id IS NOT NULL AND
          s.document=to_tsvector('english'::regconfig,coalesce(m.snapshot_json->>'title','')||' '||(m.snapshot_json->>'text'))
          AND s.year IS NOT DISTINCT FROM (m.snapshot_json->>'year')::integer
          AND s.paper_id=m.paper_id AND m.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(m)))
          FROM index_generation_members m LEFT JOIN index_generation_search s USING(generation_id,vector_id)
          WHERE m.generation_id=:id"""), {"id": pin["generation_id"]})).one()
        assert row == (5, True)
        await db.rollback()


async def test_projection_rejects_orphans_and_cannot_be_rewritten(monkeypatch):
    _, _, pin = await write_generation(monkeypatch, logical_index="guards-" + uuid4().hex)
    async with get_session_factory()() as db:
        for statement in (
            "UPDATE index_generation_search SET document=to_tsvector('forged') WHERE generation_id=:id",
            "DELETE FROM index_generation_search WHERE generation_id=:id",
            "TRUNCATE index_generation_search",
            "INSERT INTO index_generation_search(generation_id,vector_id,paper_id,year,document) "
            "VALUES(:id,'missing-member','forged-paper',2099,to_tsvector('forged'))",
        ):
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await db.execute(sa.text(statement), {"id": pin["generation_id"]})
        assert await db.scalar(sa.text("SELECT count(*) FROM index_generation_search WHERE generation_id=:id"),
            {"id": pin["generation_id"]}) == 5


async def test_projection_rolls_back_with_interrupted_member_staging(monkeypatch):
    identifier = str(uuid4())
    with pytest.raises(RuntimeError, match="interrupted SQL generation staging"):
        await write_generation(monkeypatch, logical_index="rollback-" + uuid4().hex,
            generation_id=identifier, fail_after_stage=True)
    async with get_session_factory()() as db:
        for table in ("index_generation_members", "index_generation_search"):
            assert await db.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE generation_id=:id"),
                {"id": identifier}) == 0
