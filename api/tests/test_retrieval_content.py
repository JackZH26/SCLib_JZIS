"""Actual content/reference guards on fresh owned synthetic services only."""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.retrieval_content_v2 import TABLE_ORDER
from services import retrieval_content as service
from services.index_generations import stage_generation
from services.retrieval_native import append_input_receipt, append_native_revisions
from tests.test_index_generations import db_session as db_session
from tests.test_index_generations import resource, staged
from tests.test_research_freeze import state
from tests.test_retrieval_native import native_inputs


async def legacy_content(db, *, complete=True):
    generation, _ = await staged(db)
    plan = await service.stage_legacy_content(db, generation_id=generation["generation_id"], dry_run=False)
    if complete:
        page = await service.source_reference_page(db, content_id=plan["content_id"])
        await service.append_content_partition(db, content_id=plan["content_id"], partition_id=0, references=page, dry_run=False)
        await service.seal_content(db, content_id=plan["content_id"], dry_run=False)
    return generation, plan


async def publication(db, tmp_path):
    arguments, items, _ = await native_inputs(db, tmp_path)
    receipt = await append_input_receipt(db, **arguments, dry_run=False)
    revisions = await append_native_revisions(db, input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False)
    result = await service.seal_native_publication(db, paper_id=arguments["paper_id"],
        native_revision_ids=[row["revision_id"] for row in revisions["revisions"]], dry_run=False)
    return arguments, items, result


async def test_complete_legacy_reference_import_preview_replay_and_no_provider_generation(db_session):
    generation, _ = await staged(db_session)
    before = await state(db_session)
    preview = await service.stage_legacy_content(db_session, generation_id=generation["generation_id"])
    assert await state(db_session) == before and not preview["committed"]
    plan = await service.stage_legacy_content(db_session, generation_id=generation["generation_id"], dry_run=False)
    page = await service.source_reference_page(db_session, content_id=plan["content_id"])
    assert len(page) == 1 and page[0]["origin_kind"] == "legacy_v1"
    await service.append_content_partition(db_session, content_id=plan["content_id"], partition_id=0, references=page, dry_run=False)
    sealed = await service.seal_content(db_session, content_id=plan["content_id"], dry_run=False)
    after = await state(db_session)
    assert sealed["member_count"] == sealed["partition_count"] == 1
    await service.stage_legacy_content(db_session, generation_id=generation["generation_id"], dry_run=False)
    await service.append_content_partition(db_session, content_id=plan["content_id"], partition_id=0, references=page, dry_run=False)
    assert await service.seal_content(db_session, content_id=plan["content_id"], dry_run=False) == sealed
    assert await state(db_session) == after
    for name in ("index_generations", "index_generation_members", "index_active_pointer", "index_generation_epoch"):
        assert after[name] == before[name]
    assert await service.source_reference_page(db_session, content_id=plan["content_id"], after=page[0]["vector_id"]) == []


async def test_complete_new_paper_batch_reuses_base_and_has_no_provider_resource(db_session, tmp_path):
    _, base = await legacy_content(db_session)
    arguments, _, event = await publication(db_session, tmp_path)
    before = await state(db_session)
    planned = await service.stage_native_content(db_session, base_content_id=base["content_id"], publication_ids=[event["publication_id"]])
    assert await state(db_session) == before and planned["expected_member_count"] == 2
    plan = await service.stage_native_content(db_session, base_content_id=base["content_id"], publication_ids=[event["publication_id"]], dry_run=False)
    page = await service.source_reference_page(db_session, content_id=plan["content_id"])
    assert {row["origin_kind"] for row in page} == {"legacy_v1", "native_v2"}
    await service.append_content_partition(db_session, content_id=plan["content_id"], partition_id=0, references=page, dry_run=False)
    seal = await service.seal_content(db_session, content_id=plan["content_id"], dry_run=False)
    assert seal["member_count"] == 2 and not seal["active_pointer_changed"]
    after = await state(db_session)
    await service.stage_native_content(db_session, base_content_id=base["content_id"], publication_ids=[event["publication_id"]], dry_run=False)
    await service.append_content_partition(db_session, content_id=plan["content_id"], partition_id=0, references=page, dry_run=False)
    await service.seal_content(db_session, content_id=plan["content_id"], dry_run=False)
    assert await state(db_session) == after
    for name in ("index_generations", "index_generation_members", "index_active_pointer", "index_generation_epoch"):
        assert after[name] == before[name]
    assert arguments["paper_id"] in {row["paper_id"] for row in after[TABLE_ORDER[5]]}


async def test_publication_refuses_missing_current_chunk_inventory(db_session, tmp_path):
    arguments, items, _ = await native_inputs(db_session, tmp_path)
    receipt = await append_input_receipt(db_session, **arguments, dry_run=False)
    captured = await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False)
    # A second genuine current chunk for this same synthetic paper makes the
    # declared one-revision event incomplete, even though its count is honest.
    await db_session.execute(sa.text("INSERT INTO chunks(id,paper_id,title,text,materials_mentioned,has_equation,has_table) "
        "SELECT :id,paper_id,title,text,materials_mentioned,has_equation,has_table FROM chunks WHERE id=:old"),
        {"id": "synthetic-extra-" + uuid4().hex, "old": items[0]["chunk_id"]})
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="full_current_inventory"):
        await service.seal_native_publication(db_session, paper_id=arguments["paper_id"],
            native_revision_ids=[row["revision_id"] for row in captured["revisions"]], dry_run=False)
    assert await state(db_session) == before


async def test_subset_cannot_seal_its_own_declaration(db_session):
    first, items = await staged(db_session)
    _, other_items = await staged(db_session)
    source = await stage_generation(db_session, generation_id=uuid4(), items=items + other_items,
                                    resource=resource(), logical_index="sclib-main", dry_run=False)
    content = Base.metadata.tables[TABLE_ORDER[3]]
    identifier = uuid4()
    await db_session.execute(content.insert().values(id=identifier, logical_index="sclib-main",
        source_generation_id=UUID(source["generation_id"]), base_content_id=None,
        expected_member_count=1, profile=source["profile"]))
    page = await service.source_reference_page(db_session, content_id=identifier)
    assert len(page) == 2
    await service.append_content_partition(db_session, content_id=identifier, partition_id=0, references=page[:1], dry_run=False)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="complete_source_universe"):
        await service.seal_content(db_session, content_id=identifier, dry_run=False)
    assert await state(db_session) == before and first["generation_id"] != source["generation_id"]


async def test_same_paper_native_publication_replaces_legacy_references(db_session, tmp_path):
    generation, items = await staged(db_session)
    base = await service.stage_legacy_content(db_session, generation_id=generation["generation_id"], dry_run=False)
    old_page = await service.source_reference_page(db_session, content_id=base["content_id"])
    await service.append_content_partition(db_session, content_id=base["content_id"], partition_id=0, references=old_page, dry_run=False)
    await service.seal_content(db_session, content_id=base["content_id"], dry_run=False)
    source = (await db_session.execute(sa.text("SELECT c.paper_id,c.text,e.rendering_version FROM chunks c "
        "JOIN chunk_evidence_current l ON l.chunk_id=c.id JOIN rag_evidence_revisions e ON e.id=l.evidence_revision_id "
        "WHERE c.id=:id"), {"id": items[0]["chunk_id"]})).mappings().one()
    path = tmp_path / "retained-renderer-input.json"
    path.write_text(source["text"])
    captured_input = await append_input_receipt(db_session, archive_root=tmp_path, relative_path=path.name,
        paper_id=source["paper_id"], source_uri="https://example.invalid/synthetic-correction",
        source_scope="structured_record", media_type="application/json", parser_version="synthetic-parser/2",
        chunker_version=source["rendering_version"], dry_run=False)
    captured = await append_native_revisions(db_session, input_receipt_id=captured_input["input_receipt_id"],
        items=[{key: items[0][key] for key in ("chunk_id", "receipt_id", "vector")}], dry_run=False)
    event = await service.seal_native_publication(db_session, paper_id=source["paper_id"],
        native_revision_ids=[row["revision_id"] for row in captured["revisions"]], dry_run=False)
    plan = await service.stage_native_content(db_session, base_content_id=base["content_id"],
        publication_ids=[event["publication_id"]], dry_run=False)
    page = await service.source_reference_page(db_session, content_id=plan["content_id"])
    assert len(page) == 1 and page[0]["origin_kind"] == "native_v2" and page[0]["vector_id"] != old_page[0]["vector_id"]
    await service.append_content_partition(db_session, content_id=plan["content_id"], partition_id=0, references=page, dry_run=False)
    assert (await service.seal_content(db_session, content_id=plan["content_id"], dry_run=False))["member_count"] == 1
    assert await service.source_reference_page(db_session, content_id=base["content_id"]) == old_page
    assert path.read_text() == source["text"]


async def test_publication_preview_and_replay_preserve_all_state(db_session, tmp_path):
    arguments, items, _ = await native_inputs(db_session, tmp_path)
    receipt = await append_input_receipt(db_session, **arguments, dry_run=False)
    captured = await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False)
    values = dict(paper_id=arguments["paper_id"], native_revision_ids=[row["revision_id"] for row in captured["revisions"]])
    before = await state(db_session)
    await service.seal_native_publication(db_session, **values)
    assert await state(db_session) == before
    event = await service.seal_native_publication(db_session, **values, dry_run=False)
    after = await state(db_session)
    assert await service.seal_native_publication(db_session, **values, dry_run=False) == event
    assert await state(db_session) == after


async def test_changed_current_text_cannot_be_sealed_as_old_native_revision(db_session, tmp_path):
    arguments, items, _ = await native_inputs(db_session, tmp_path)
    receipt = await append_input_receipt(db_session, **arguments, dry_run=False)
    captured = await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False)
    await db_session.execute(sa.text("UPDATE chunks SET text=text||' changed fixture text' WHERE id=:id"),
                             {"id": items[0]["chunk_id"]})
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="full_current_inventory"):
        await service.seal_native_publication(db_session, paper_id=arguments["paper_id"],
            native_revision_ids=[row["revision_id"] for row in captured["revisions"]], dry_run=False)
    assert await state(db_session) == before


async def test_change_plan_cannot_expand_after_first_member(db_session, tmp_path):
    _, base = await legacy_content(db_session)
    _, _, first = await publication(db_session, tmp_path)
    plan = await service.stage_native_content(db_session, base_content_id=base["content_id"],
        publication_ids=[first["publication_id"]], dry_run=False)
    page = await service.source_reference_page(db_session, content_id=plan["content_id"])
    # One staged member is enough to freeze the change inventory.
    await service.append_content_partition(db_session, content_id=plan["content_id"], partition_id=0, references=page, dry_run=False)
    second_root = tmp_path / "second"
    second_root.mkdir()
    arguments, _, second = await publication(db_session, second_root)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match="frozen_native_change_plan"):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLE_ORDER[4]].insert().values(
                content_id=UUID(plan["content_id"]), paper_id=arguments["paper_id"], publication_id=UUID(second["publication_id"])))
    assert await state(db_session) == before


@pytest.mark.parametrize("mode", ["wrong_origin", "wrong_vector", "outside_partition", "duplicate", "unknown_field"])
async def test_partition_rejects_foreign_or_unbounded_references(db_session, mode):
    _, plan = await legacy_content(db_session, complete=False)
    page = await service.source_reference_page(db_session, content_id=plan["content_id"])
    selected = deepcopy(page)
    partition_id = 0
    if mode == "wrong_origin":
        selected[0]["origin_generation_id"] = uuid4()
    elif mode == "wrong_vector":
        selected[0]["vector_id"] = "unknown-member"
    elif mode == "outside_partition":
        partition_id = 1
    elif mode == "duplicate":
        selected *= 2
    else:
        selected[0]["sql_table"] = "arbitrary"
    before = await state(db_session)
    with pytest.raises((DBAPIError, service.RetrievalContentError)):
        await service.append_content_partition(db_session, content_id=plan["content_id"],
            partition_id=partition_id, references=selected, dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("table", TABLE_ORDER)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_content_and_publication_history_is_append_only(db_session, tmp_path, table, operation):
    _, base = await legacy_content(db_session)
    arguments, _, event = await publication(db_session, tmp_path)
    plan = await service.stage_native_content(db_session, base_content_id=base["content_id"],
        publication_ids=[event["publication_id"]], dry_run=False)
    await service.append_content_partition(db_session, content_id=plan["content_id"], partition_id=0,
        references=await service.source_reference_page(db_session, content_id=plan["content_id"]), dry_run=False)
    await service.seal_content(db_session, content_id=plan["content_id"], dry_run=False)
    before = await state(db_session)
    query = f"UPDATE {table} SET record_sha256=record_sha256" if operation == "UPDATE" else (
        f"DELETE FROM {table}" if operation == "DELETE" else f"TRUNCATE {table} CASCADE")
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(query))
    assert await state(db_session) == before and arguments["paper_id"]
