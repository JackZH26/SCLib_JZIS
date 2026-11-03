"""Synthetic bridge transactions on fresh runner-owned services only."""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
try:
    import native_publisher
except ImportError:
    sys.path[:0] = [str(ROOT / "publisher"), str(ROOT / "ingestion")]

from ingestion.index import indexer
from ingestion.models import PaperMetadata, ParsedPaper, Chunk, ApsArticleMeta
from native_publisher import producer
from native_publisher.cli import load_prepared
from models.db import get_engine, get_session_factory
from services.schema_lifecycle import expected_heads, SchemaLifecycleError
from services.retrieval_native import RetrievalNativeError
from sqlalchemy.exc import DBAPIError
from tests.test_embedding_receipts import completion
from tests.test_retrieval_activation import prepared_build
from tests.test_index_generations import db_session as db_session

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get("SCLIB_PGVECTOR_RUNTIME_TEST") != "1",
    reason="Requires freshly owned PostgreSQL/vector services")]


@pytest_asyncio.fixture
async def bridge(monkeypatch):
    # This is a synthetic runtime stamp, not proof that a migration ran.
    # Complete migration rehearsals are separately executed by the runner.
    engine = get_engine()
    async with engine.begin() as connection:
        version_table_existed = await connection.scalar(sa.text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
        await connection.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version(version_num varchar(32) PRIMARY KEY)"))
        prior = (await connection.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars().all()
        await connection.execute(sa.text("DELETE FROM alembic_version"))
        await connection.execute(sa.text("INSERT INTO alembic_version VALUES(:head)"), {"head": expected_heads()[0]})
    monkeypatch.setattr(indexer, "_engine", lambda: engine)
    monkeypatch.setattr(indexer, "_session_factory", get_session_factory)
    monkeypatch.setattr(producer, "get_settings", lambda: SimpleNamespace(retrieval_backend="pgvector"))
    def forbidden(*args, **kwargs):
        raise AssertionError("No Google writer or provider is permitted")
    for name in ("_index", "upsert_chunks_to_vector_search", "upsert_aps_chunks_to_vector_search"):
        monkeypatch.setattr(indexer, name, forbidden)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(sa.text("DELETE FROM alembic_version"))
        for value in prior:
            await connection.execute(sa.text("INSERT INTO alembic_version VALUES(:head)"), {"head": value})
        if not version_table_existed:
            await connection.execute(sa.text("DROP TABLE alembic_version"))
    await engine.dispose()


def prepared(tmp_path, *, source="arxiv", text="Synthetic abstract about superconductivity.", paper=None):
    import tiktoken
    metadata = paper or PaperMetadata("2601." + str(10000 + uuid4().int % 90000),
        "Synthetic bridge fixture", [], text, None, [], None)
    if source == "aps" and paper is None:
        metadata = ApsArticleMeta("10.1103/Synthetic." + uuid4().hex, "Synthetic APS fixture", [], text)
    if type(metadata) is ParsedPaper:
        metadata = metadata.meta
    metadata.abstract = text
    value = ParsedPaper(metadata, []) if type(metadata) is PaperMetadata else metadata
    vector, report = completion(text)
    chunk = Chunk(metadata.paper_id + "_abstract", metadata.paper_id, 0, "Abstract", text,
        len(tiktoken.get_encoding("cl100k_base").encode(text)), embedding=vector, embedding_provenance=report,
        evidence_candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "abstract",
            "rendering_version": "synthetic-chunker/1"})
    path = tmp_path / (uuid4().hex + ".txt")
    path.write_text(text)
    item = producer.RetainedInput(path.name, "https://example.invalid/synthetic-input", "text/plain",
        "synthetic-parser/1", "synthetic-chunker/1", path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    return value, [chunk], {"abstract": item}


async def visible(db, paper_id):
    return await db.scalar(sa.text("""SELECT jsonb_build_object(
      'paper',(SELECT to_jsonb(p) FROM papers p WHERE id=:paper),
      'chunks',(SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY id),'[]') FROM chunks c WHERE paper_id=:paper),
      'native',(SELECT coalesce(jsonb_agg(to_jsonb(n) ORDER BY id),'[]') FROM retrieval_native_revisions_v2 n WHERE paper_id=:paper),
      'jobs',(SELECT coalesce(jsonb_agg(to_jsonb(j) ORDER BY id),'[]') FROM retrieval_publication_jobs_v2 j WHERE paper_id=:paper))"""),
      {"paper": paper_id})


async def logical(db):
    build = await prepared_build(db)
    await db.commit()
    return build["logical_index"]


@pytest.mark.parametrize("source", ["arxiv", "aps"])
async def test_preview_complete_commit_replay_and_file_preservation(bridge, db_session, tmp_path, source):
    index = await logical(db_session)
    paper, chunks, inputs = prepared(tmp_path, source=source)
    paper_id = chunks[0].paper_id
    path = tmp_path / inputs["abstract"].relative_path
    contents, modified = path.read_bytes(), path.stat().st_mtime_ns
    before = await visible(db_session, paper_id)
    dry = await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index=index)
    assert not dry["committed"] and dry["dry_run"] and await visible(db_session, paper_id) == before
    first = await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index=index, dry_run=False)
    assert first["committed"] and first["publication"]["member_count"] == 1
    second = await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index=index, dry_run=False)
    assert first == second
    state = await visible(db_session, paper_id)
    assert len(state["jobs"]) == len(state["native"]) == 1
    assert path.read_bytes() == contents and path.stat().st_mtime_ns == modified
    assert first["active_pointer_changed"] is first["archive_files_deleted"] is first["google_ann_calls"] is False


async def test_corrected_paper_keeps_both_sealed_versions(bridge, db_session, tmp_path):
    index = await logical(db_session)
    paper, chunks, inputs = prepared(tmp_path)
    first = await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index=index, dry_run=False)
    revised, new_chunks, new_inputs = prepared(tmp_path, paper=paper, text="Synthetic corrected superconductivity abstract.")
    second = await producer.publish_prepared(revised, new_chunks, [], archive_root=tmp_path, inputs=new_inputs, logical_index=index, dry_run=False)
    assert first["job"]["job_id"] != second["job"]["job_id"]
    assert first["publication"]["publication_id"] != second["publication"]["publication_id"]
    state = await visible(db_session, chunks[0].paper_id)
    assert len(state["jobs"]) == len(state["native"]) == 2
    assert await db_session.scalar(sa.text("SELECT count(*) FROM retrieval_activation_events_v2 WHERE logical_index=:index"), {"index": index}) == 0


@pytest.mark.parametrize("failure", ["missing_file", "checksum", "queue"])
async def test_failure_rolls_back_paper_chunks_and_all_history(bridge, db_session, tmp_path, failure):
    index = await logical(db_session)
    paper, chunks, inputs = prepared(tmp_path)
    path = tmp_path / inputs["abstract"].relative_path
    before = await visible(db_session, chunks[0].paper_id)
    if failure == "missing_file":
        path.unlink()  # This synthetic test owns its fixture file.
    elif failure == "checksum":
        path.write_text("Synthetic changed representation")
    else:
        index = "unregistered-synthetic-logical"
    expected = DBAPIError if failure == "queue" else RetrievalNativeError
    with pytest.raises(expected):
        await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index=index, dry_run=False)
    assert await visible(db_session, chunks[0].paper_id) == before


async def test_wrong_backend_and_original_aps_evidence_refused_before_db(tmp_path, monkeypatch):
    paper, chunks, inputs = prepared(tmp_path, source="aps")
    monkeypatch.setattr(producer, "get_settings", lambda: SimpleNamespace(retrieval_backend="google"))
    with pytest.raises(producer.NativePublisherError, match="explicit pgvector"):
        await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index="synthetic")
    monkeypatch.setattr(producer, "get_settings", lambda: SimpleNamespace(retrieval_backend="pgvector"))
    chunks[0].evidence_candidate = {"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage"}
    with pytest.raises(ValueError):
        await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index="synthetic")


async def test_schema_admission_refuses_write(bridge, db_session, tmp_path):
    index = await logical(db_session)
    async with bridge.begin() as connection:
        await connection.execute(sa.text("UPDATE alembic_version SET version_num='0106_materials_source_notation'"))
    paper, chunks, inputs = prepared(tmp_path)
    with pytest.raises(SchemaLifecycleError):
        await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index=index, dry_run=False)
    assert (await visible(db_session, chunks[0].paper_id))["paper"] is None


async def test_prepared_file_closed_fields_and_no_symlink(tmp_path):
    from dataclasses import asdict
    paper, chunks, inputs = prepared(tmp_path)
    package = {"version": "native-prepared-paper/1.0.0", "source": "arxiv", "metadata": paper.meta.to_dict(),
        "chunks": [asdict(chunk) for chunk in chunks], "materials": [],
        "inputs": {kind: asdict(item) for kind, item in inputs.items()}}
    file = tmp_path / "prepared.json"
    file.write_text(json.dumps(package))
    loaded = load_prepared(file)
    assert loaded[0].meta.paper_id == paper.meta.paper_id and loaded[-1] == hashlib.sha256(file.read_bytes()).hexdigest()
    link = tmp_path / "link.json"
    link.symlink_to(file)
    with pytest.raises(OSError):
        load_prepared(link)
    package["unknown_privilege"] = True
    file.write_text(json.dumps(package))
    with pytest.raises(producer.NativePublisherError):
        load_prepared(file)


async def test_mixed_inputs_and_removed_chunk_keep_immutable_versions(bridge, db_session, tmp_path):
    import tiktoken
    from services.rag_evidence import CURRENT_FACT_RENDERER_VERSION
    index = await logical(db_session)
    paper, chunks, inputs = prepared(tmp_path)
    record = {"formula": "MgB2", "tc_kelvin": "<100 K", "evidence_role": "primary_theoretical"}
    text = "Synthetic derived quantity Tc < 100 K."
    vector, report = completion(text)
    fact = Chunk(paper.meta.paper_id + "_fact", paper.meta.paper_id, 1, "Facts", text,
        len(tiktoken.get_encoding("cl100k_base").encode(text)), embedding=vector,
        embedding_provenance=report, materials_mentioned=[record], evidence_candidate={
            "version": "rag-evidence/1.0.0", "chunk_kind": "derived_fact", "parent_record": record,
            "extraction_version": "synthetic-extraction/1", "rendering_version": CURRENT_FACT_RENDERER_VERSION})
    path = tmp_path / "structured.json"
    path.write_text(json.dumps(record))
    inputs["derived_fact"] = producer.RetainedInput(path.name, "https://example.invalid/structured",
        "application/json", "synthetic-parser/1", CURRENT_FACT_RENDERER_VERSION,
        path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    first = await producer.publish_prepared(paper, [*chunks, fact], [record], archive_root=tmp_path,
        inputs=inputs, logical_index=index, dry_run=False)
    assert first["publication"]["member_count"] == 2 and len(first["inputs"]) == 2
    second = await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path,
        inputs={"abstract": inputs["abstract"]}, logical_index=index, dry_run=False)
    assert second["publication"]["member_count"] == 1
    state = await visible(db_session, chunks[0].paper_id)
    assert len(state["chunks"]) == 1 and len(state["native"]) == 3 and len(state["jobs"]) == 2
    assert path.exists()


async def test_foreign_chunk_identity_cannot_move_between_papers(bridge, db_session, tmp_path):
    index = await logical(db_session)
    first, chunks, inputs = prepared(tmp_path)
    await producer.publish_prepared(first, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index=index, dry_run=False)
    before = await visible(db_session, chunks[0].paper_id)
    other, foreign, other_inputs = prepared(tmp_path)
    foreign[0].id = chunks[0].id
    with pytest.raises(ValueError, match="another paper"):
        await producer.publish_prepared(other, foreign, [], archive_root=tmp_path, inputs=other_inputs, logical_index=index, dry_run=False)
    assert await visible(db_session, chunks[0].paper_id) == before
    assert (await visible(db_session, other.meta.paper_id))["paper"] is None


async def test_failure_after_enqueue_rolls_back_everything(bridge, db_session, tmp_path, monkeypatch):
    index = await logical(db_session)
    paper, chunks, inputs = prepared(tmp_path)
    before = await visible(db_session, chunks[0].paper_id)
    original = producer.retrieval_publication_queue.enqueue_publication
    async def fail_after_enqueue(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("Synthetic crash after actual enqueue")
    monkeypatch.setattr(producer.retrieval_publication_queue, "enqueue_publication", fail_after_enqueue)
    with pytest.raises(RuntimeError, match="Synthetic crash"):
        await producer.publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs, logical_index=index, dry_run=False)
    assert await visible(db_session, chunks[0].paper_id) == before
