"""Actual ingestion staging atomicity and retained rollback bytes on native PG."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from models.db import get_session_factory
from services import index_generations
from tests.index_generation_fixtures import (
    RESOURCE,
    corpus,
    indexer,
    prepare_generation_items,
    publish_and_activate,
    write_generation,
)


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


@pytest.fixture
def transport():
    from services import index_vector_adapter
    index_vector_adapter.clear_disposable()
    value = index_vector_adapter.register_disposable(RESOURCE)
    yield value
    index_vector_adapter.clear_disposable()


async def test_actual_sql_stager_preserves_old_bytes_after_five_to_three_replacement(monkeypatch, db_session, transport):
    logical = "ingestion-fixture-" + uuid4().hex
    meta, old_chunks, old = await write_generation(monkeypatch, logical_index=logical, count=5)
    old_members = await index_generations.load_generation_members(db_session, generation_id=old["generation_id"])
    assert len(old_members) == 5
    assert {member["snapshot_json"]["text"] for member in old_members} == {chunk.text for chunk in old_chunks}
    active1, _, _ = await publish_and_activate(db_session, old)
    _, new_chunks, new = await write_generation(monkeypatch, logical_index=logical, count=3, meta=meta, label="new")
    new_members = await index_generations.load_generation_members(db_session, generation_id=new["generation_id"])
    assert await db_session.scalar(text("SELECT count(*) FROM chunks WHERE paper_id=:paper"), {"paper": meta.paper_id}) == 3
    assert not {m["vector_id"] for m in old_members} & {m["vector_id"] for m in new_members}
    assert await index_generations.load_generation_members(db_session, generation_id=old["generation_id"]) == old_members
    assert (await index_generations.load_active_generation(db_session, logical_index=logical))["generation_id"] == old["generation_id"]
    active2, _, _ = await publish_and_activate(db_session, new, expected_event_id=active1["activation_event_id"])
    assert len(transport.points) == 8  # retained rollback bytes, not eight active members
    assert {m["snapshot_json"]["text"] for m in new_members} == {chunk.text for chunk in new_chunks}
    restored, _, _ = await publish_and_activate(db_session, old, expected_event_id=active2["activation_event_id"], action="rollback")
    assert restored["generation_id"] == active1["generation_id"]
    assert restored["activation_event_id"] != active1["activation_event_id"]
    assert (await index_generations.load_active_generation(db_session, logical_index=logical))["generation_id"] == old["generation_id"]


async def test_interrupted_stager_rolls_back_every_sql_layer_and_preserves_old_generation(monkeypatch, db_session):
    logical = "rollback-fixture-" + uuid4().hex
    meta, chunks, staged = await write_generation(monkeypatch, logical_index=logical, count=2)
    before = await index_generations.load_generation_members(db_session, generation_id=staged["generation_id"])
    interrupted = str(uuid4())
    with pytest.raises(RuntimeError, match="Synthetic interrupted"):
        await write_generation(monkeypatch, logical_index=logical, count=3, meta=meta, label="uncommitted",
                               generation_id=interrupted, fail_after_stage=True)
    await db_session.rollback()
    assert await db_session.scalar(text("SELECT count(*) FROM index_generations WHERE id=:id"), {"id": interrupted}) == 0
    actual = (await db_session.execute(text("SELECT text FROM chunks WHERE paper_id=:paper ORDER BY id"), {"paper": meta.paper_id})).scalars().all()
    assert actual == [chunk.text for chunk in chunks]
    assert await index_generations.load_generation_members(db_session, generation_id=staged["generation_id"]) == before


async def test_preparation_is_read_only_exact_and_does_not_mutate_chunk_objects(monkeypatch, db_session):
    logical = "prepare-fixture-" + uuid4().hex
    _, chunks, _ = await write_generation(monkeypatch, logical_index=logical, count=3)
    original = deepcopy(chunks)
    items = await prepare_generation_items(db_session, chunks)
    assert chunks == original
    assert len(items) == 3 and all(set(item) == {"chunk_id", "receipt_id", "vector", "parser_version"} for item in items)
    assert all(item["parser_version"] == "synthetic-parser/1" for item in items)
    chunks[0].text += " Changed outside the completed embedding."
    with pytest.raises(ValueError):
        await prepare_generation_items(db_session, chunks)


@pytest.mark.parametrize("bad", ["missing_parser", "unknown_parser", "missing_vector", "missing_receipt", "wrong_count", "duplicate"])
async def test_candidate_preflight_rejects_before_database_access(bad):
    _, _, chunks = corpus(count=1)
    if bad == "missing_parser": chunks[0].parser_version = None
    elif bad == "unknown_parser": chunks[0].parser_version = "unknown"
    elif bad == "missing_vector": chunks[0].embedding = None
    elif bad == "missing_receipt": chunks[0].embedding_provenance = None
    elif bad == "wrong_count": chunks[0].token_count += 1
    elif bad == "duplicate": chunks.append(deepcopy(chunks[0]))
    async def forbidden(*args, **kwargs):
        raise AssertionError("Candidate preflight must precede SQL")
    db = SimpleNamespace(new=(), dirty=(), deleted=(), execute=forbidden)
    with pytest.raises(ValueError):
        await prepare_generation_items(db, chunks)


async def test_arxiv_real_writer_uses_the_same_atomic_staging_hook(monkeypatch, db_session):
    from ingestion.models import PaperMetadata, ParsedPaper

    meta = PaperMetadata(arxiv_id="2609.99621", title="Synthetic generation bridge", authors=[], abstract="",
                         date_submitted=None, categories=[], primary_category=None)
    _, record, chunks = corpus(count=1, meta=meta)
    monkeypatch.setattr(indexer, "_session_factory", get_session_factory)
    identifier = str(uuid4())
    async def stager(session, selected):
        items = await prepare_generation_items(session, selected)
        await index_generations.stage_generation(session, generation_id=identifier, items=items,
            resource=RESOURCE, logical_index="arxiv-fixture-" + uuid4().hex, dry_run=False)
    await indexer.upsert_paper_with_chunks(ParsedPaper(meta, []), chunks, [record], generation_stager=stager)
    members = await index_generations.load_generation_members(db_session, generation_id=identifier)
    assert len(members) == 1 and members[0]["snapshot_json"]["text"] == chunks[0].text
    assert members[0]["paper_snapshot_json"]["source"] == "arxiv"
