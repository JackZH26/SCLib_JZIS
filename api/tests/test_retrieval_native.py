"""Native capture on fresh owned services; no publisher or scientific approval."""
from __future__ import annotations

import hashlib
import json
import os
from uuid import UUID

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, Chunk, get_session_factory
from services.embedding_receipts import append_embedding_receipt
from services.retrieval_native import (
    RetrievalNativeError,
    append_input_receipt,
    append_native_revisions,
    observe_archive_file,
)
from tests.test_embedding_receipts import prepared


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as db:
        yield db


async def native_state(db):
    return await db.scalar(sa.text("""SELECT jsonb_build_object(
      'inputs',(SELECT coalesce(jsonb_agg(to_jsonb(i) ORDER BY id),'[]') FROM retrieval_input_receipts_v2 i),
      'revisions',(SELECT coalesce(jsonb_agg(to_jsonb(n) ORDER BY id),'[]') FROM retrieval_native_revisions_v2 n),
      'legacy_generations',(SELECT count(*) FROM index_generations),
      'legacy_pointer',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY logical_index),'[]') FROM index_active_pointer p),
      'index_epoch',(SELECT epoch FROM index_generation_epoch WHERE id=1))"""))


async def native_inputs(db, tmp_path):
    chunk, vector, metadata, _ = await prepared(db)
    complete = await append_embedding_receipt(db, chunk_id=chunk, vector=vector, receipt=metadata, dry_run=False)
    source = (await db.execute(sa.text("""SELECT c.paper_id,c.text,e.rendering_version
       FROM chunks c JOIN chunk_evidence_current link ON link.chunk_id=c.id
       JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id WHERE c.id=:id"""),
       {"id": chunk})).mappings().one()
    # The retained file is a synthetic structured renderer input. It is not
    # asserted to be publisher full text or an independently verified result.
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"synthetic_renderer_input": source["text"]}))
    arguments = dict(archive_root=tmp_path, relative_path=path.name, paper_id=source["paper_id"],
                     source_uri="https://example.invalid/synthetic-input", source_scope="structured_record",
                     media_type="application/json", parser_version="synthetic-parser/2",
                     chunker_version=source["rendering_version"], expected_bytes=path.stat().st_size,
                     provider_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    items = [{"chunk_id": chunk, "receipt_id": complete["receipt_id"], "vector": vector}]
    return arguments, items, chunk


def test_observation_reads_exact_bytes_without_changing_the_archive(tmp_path):
    path = tmp_path / "input.xml"
    data = b"<synthetic>complete retained input</synthetic>"
    path.write_bytes(data)
    before = path.stat()
    result = observe_archive_file(tmp_path, path.name, expected_bytes=len(data),
                                  provider_sha256=hashlib.sha256(data).hexdigest())
    assert result.sha256 == hashlib.sha256(data).hexdigest() and result.bytes == len(data)
    assert path.read_bytes() == data and path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("case", ["absolute", "parent", "symlink_escape", "empty", "length", "checksum"])
def test_wrong_or_outside_inputs_are_refused_before_any_database_use(tmp_path, case):
    archive = tmp_path / "archive"
    archive.mkdir()
    path = archive / "input"
    path.write_bytes(b"synthetic input")
    selected, options = path.name, {}
    if case == "absolute":
        selected = str(path)
    elif case == "parent":
        selected = "../input"
    elif case == "symlink_escape":
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside private input")
        path.unlink()
        path.symlink_to(outside)
    elif case == "empty":
        path.write_bytes(b"")
    elif case == "length":
        options["expected_bytes"] = 1
    else:
        options["provider_sha256"] = "0" * 64
    with pytest.raises(RetrievalNativeError):
        observe_archive_file(archive, selected, **options)


def test_file_modified_during_observation_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "input"
    path.write_bytes(b"synthetic complete input")
    original_read, changed = os.read, False
    def changing_read(descriptor, size):
        nonlocal changed
        data = original_read(descriptor, size)
        if not changed:
            changed = True
            path.write_bytes(b"changed input")
        return data
    monkeypatch.setattr(os, "read", changing_read)
    with pytest.raises(RetrievalNativeError, match="changed during observation"):
        observe_archive_file(tmp_path, path.name)


def test_native_history_has_no_provider_generation_or_mutable_chunk_foreign_key():
    native = Base.metadata.tables["retrieval_native_revisions_v2"]
    assert not {"generation_id", "resource", "endpoint", "deployed_index_id"} & set(native.c.keys())
    assert all(key.column.table.name != "chunks" for key in native.foreign_keys)
    inputs = Base.metadata.tables["retrieval_input_receipts_v2"]
    assert not {"text", "vector_bytes", "raw_payload"} & set(inputs.c.keys())


async def test_input_preview_and_exact_replay_preserve_state(db_session, tmp_path):
    arguments, _, _ = await native_inputs(db_session, tmp_path)
    before = await native_state(db_session)
    preview = await append_input_receipt(db_session, **arguments)
    assert preview["committed"] is False and await native_state(db_session) == before
    first = await append_input_receipt(db_session, **arguments, dry_run=False)
    after = await native_state(db_session)
    assert await append_input_receipt(db_session, **arguments, dry_run=False) == first
    assert await native_state(db_session) == after
    assert preview["input_receipt_id"] == first["input_receipt_id"]


async def test_native_capture_dryrun_replay_and_outer_rollback_without_fake_generation(db_session, tmp_path):
    arguments, items, _ = await native_inputs(db_session, tmp_path)
    receipt = await append_input_receipt(db_session, **arguments, dry_run=False)
    before = await native_state(db_session)
    preview = await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"], items=items)
    assert preview["committed"] is False and await native_state(db_session) == before
    first = await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False)
    after = await native_state(db_session)
    assert after["legacy_generations"] == before["legacy_generations"] and after["legacy_pointer"] == before["legacy_pointer"]
    assert after["revisions"][0]["vector_id"].startswith("rv2_")
    assert first["revisions"] == preview["revisions"]
    assert await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False) == first
    assert await native_state(db_session) == after
    await db_session.rollback()
    assert (await native_state(db_session))["inputs"] == []
    assert (await native_state(db_session))["revisions"] == []


async def test_wrong_scope_cannot_bind_input_to_native_evidence(db_session, tmp_path):
    arguments, items, _ = await native_inputs(db_session, tmp_path)
    wrong = await append_input_receipt(db_session, **{**arguments, "source_scope": "full_text"}, dry_run=False)
    before = await native_state(db_session)
    with pytest.raises(DBAPIError, match="native_input_binding"):
        await append_native_revisions(db_session, input_receipt_id=wrong["input_receipt_id"], items=items, dry_run=False)
    assert await native_state(db_session) == before


async def test_vector_mismatch_cannot_capture_native_revision(db_session, tmp_path):
    arguments, items, _ = await native_inputs(db_session, tmp_path)
    receipt = await append_input_receipt(db_session, **arguments, dry_run=False)
    before = await native_state(db_session)
    with pytest.raises(ValueError, match="hash mismatch"):
        await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"],
                                      items=[{**items[0], "vector": [0.5] * 768}], dry_run=False)
    assert await native_state(db_session) == before


async def test_native_snapshots_survive_mutable_chunk_removal_without_changing_evidence(db_session, tmp_path):
    arguments, items, chunk = await native_inputs(db_session, tmp_path)
    receipt = await append_input_receipt(db_session, **arguments, dry_run=False)
    result = await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False)
    before = await native_state(db_session)
    evidence = await db_session.scalar(sa.text("SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM rag_evidence_revisions e"))
    await db_session.execute(sa.delete(Chunk).where(Chunk.id == chunk))
    assert (await native_state(db_session))["revisions"] == before["revisions"]
    assert await db_session.scalar(sa.text("SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM rag_evidence_revisions e")) == evidence
    assert result["active_pointer_changed"] is False


async def test_receipt_hashes_and_replay_are_independent_of_session_timezone_and_bytea_output(db_session, tmp_path):
    arguments, items, _ = await native_inputs(db_session, tmp_path)
    receipt = await append_input_receipt(db_session, **arguments, dry_run=False)
    first = await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"],
                                        items=items, dry_run=False)
    await db_session.execute(sa.text("SET LOCAL TimeZone='Pacific/Auckland'"))
    await db_session.execute(sa.text("SET LOCAL bytea_output='escape'"))
    for table in ("retrieval_input_receipts_v2", "retrieval_native_revisions_v2"):
        assert await db_session.scalar(sa.text(f"SELECT bool_and(record_sha256="
            f"public.sclib_retrieval_record_hash_v2(to_jsonb(n))) FROM {table} n")) is True
    assert await append_input_receipt(db_session, **arguments, dry_run=False) == receipt
    assert await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"],
                                        items=items, dry_run=False) == first


@pytest.mark.parametrize("table", ["retrieval_input_receipts_v2", "retrieval_native_revisions_v2"])
@pytest.mark.parametrize("operation", ["UPDATE {table} SET record_sha256=record_sha256", "DELETE FROM {table}", "TRUNCATE {table} CASCADE"])
async def test_native_history_is_append_only(db_session, tmp_path, table, operation):
    arguments, items, _ = await native_inputs(db_session, tmp_path)
    receipt = await append_input_receipt(db_session, **arguments, dry_run=False)
    await append_native_revisions(db_session, input_receipt_id=receipt["input_receipt_id"], items=items, dry_run=False)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(operation.format(table=table)))


async def test_missing_input_receipt_cannot_be_replaced_by_a_provider_resource(db_session, tmp_path):
    _, items, _ = await native_inputs(db_session, tmp_path)
    with pytest.raises(RetrievalNativeError, match="actual retained input receipt"):
        await append_native_revisions(db_session, input_receipt_id=UUID(int=1), items=items, dry_run=False)
