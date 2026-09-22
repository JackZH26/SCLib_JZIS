"""Real owned SQL through resumable corpus operator phases; synthetic vectors."""

import json
import sqlite3
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest_asyncio
import sqlalchemy as sa
from models.db import get_session_factory
from tests.test_retained_legacy import input_window
from tests.test_embedding_receipts import completion
from tests.test_index_vector_adapter import fixture_generation
from services import index_generations, index_vector_adapter, schema_lifecycle

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from legacy_index_pack import Pack, specification, canonical
from embed_legacy_index_pack import file_sha
from repair_legacy_index_pack import private_db, VERSION
from publish_legacy_corpus import Inputs, run


@pytest_asyncio.fixture(loop_scope="function")
async def operator_transactions(monkeypatch):
    from models import db as models
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = models.get_engine()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        monkeypatch.setattr(models, "get_session_factory", lambda: factory)
        monkeypatch.setattr(sys.modules[__name__], "get_session_factory", lambda: factory)
        try:
            yield
        finally:
            await transaction.rollback()
    await engine.dispose()


async def test_resumable_operator_preserves_originals_and_activates_only_after_full_readback(
    tmp_path, monkeypatch, operator_transactions, client
):
    tmp_path.chmod(0o700)
    rows = []
    async with get_session_factory()() as db:
        for _ in range(3):
            chunk, member, args = await input_window(db)
            rows.append((chunk, json.loads(args["paper_raw"])))
        await db.commit()
    pack = Pack(tmp_path / "pack.sqlite", specification({"synthetic": True}))
    for n, (chunk, paper) in enumerate(sorted(rows, key=lambda row: row[0]["id"]), 1):
        pack.append(n, chunk, paper)
    pack.seal(3)
    pack.close()
    pack = Pack(tmp_path / "pack.sqlite", readonly=True)
    data = private_db(tmp_path / "completions.sqlite", create=True)
    data.executescript(
        "CREATE TABLE completions(seq INTEGER PRIMARY KEY,member_id TEXT,partition_id INTEGER,vector BLOB,receipt TEXT); CREATE TABLE metadata(key TEXT PRIMARY KEY,body TEXT);"
    )
    for seq, part, key, body in pack.db.execute(
        "SELECT seq,partition_id,id,body FROM members ORDER BY seq"
    ):
        source = pack.db.execute(
            "SELECT s.body FROM sources s JOIN members m ON m.source_seq=s.seq WHERE m.seq=?",
            (seq,),
        ).fetchone()[0]
        vector, receipt = completion(json.loads(source)["text"])
        data.execute(
            "INSERT INTO completions VALUES(?,?,?,?,?)",
            (seq, key, part, struct.pack(">768f", *vector), canonical(receipt).decode()),
        )
    data.execute(
        "INSERT INTO metadata VALUES('report',?)",
        (
            canonical(
                {
                    "version": VERSION,
                    "input_pack_sha256": file_sha(pack.path),
                    "members": 3,
                    "embedding_completion_verified": True,
                    "retained_text_coverage_complete": True,
                }
            ).decode(),
        ),
    )
    data.commit()
    data.close()
    pack.close()
    target = fixture_generation()[0]["resource"]
    (tmp_path / "resource.json").write_text(json.dumps(target))
    args = SimpleNamespace(
        command="plan",
        apply=True,
        pack=tmp_path / "pack.sqlite",
        completions=tmp_path / "completions.sqlite",
        completion_sha256=file_sha(tmp_path / "completions.sqlite"),
        resource=tmp_path / "resource.json",
        generation_id=str(uuid4()),
        journal=tmp_path / "journal.sqlite",
        max_new_partitions=1,
        validation_id=None,
        expected_event_id="none",
        idempotency_key="synthetic-corpus-operator",
    )
    # API tests construct the exact model metadata; Alembic admission itself is
    # covered by the separate native migration rehearsal, not mocked cloud I/O.
    monkeypatch.setattr(
        schema_lifecycle, "check_connection_schema", lambda connection: {"test_metadata": True}
    )
    monkeypatch.setattr(
        Inputs,
        "batches",
        lambda self, after=0, until=None: ([entry] for entry in self.entries(after, until)),
    )
    for _ in range(3):
        await run(args)
    async with get_session_factory()() as db:
        assert await db.scalar(sa.text("SELECT count(*) FROM chunks")) == 3
        for table in (
            "legacy_index_papers",
            "legacy_index_sources",
            "legacy_index_windows",
            "rag_evidence_revisions",
            "embedding_completion_receipts",
            "index_generations",
        ):
            assert await db.scalar(sa.text("SELECT count(*) FROM " + table)) == 0
    args.command = "stage"
    for _ in range(3):
        await run(args)
    async with get_session_factory()() as db:
        assert await db.scalar(sa.text("SELECT count(*) FROM chunks")) == 3
        assert await index_generations.load_active_generation(db) is None
    index_vector_adapter.register_disposable(target)
    args.command = "publish"
    await run(args)
    args.command = "observe"
    await run(args)
    with sqlite3.connect(args.journal) as journal:
        events = [
            json.loads(row[0]) for row in journal.execute("SELECT body FROM events ORDER BY seq")
        ]
    args.validation_id = next(
        row["validation_id"] for row in reversed(events) if row["stage"] == "validated"
    )
    async with get_session_factory()() as db:
        assert await index_generations.load_active_generation(db) is None
    args.command = "activate"
    await run(args)
    async with get_session_factory()() as db:
        assert (await index_generations.load_active_generation(db))[
            "generation_id"
        ] == args.generation_id
        assert await db.scalar(sa.text("SELECT count(*) FROM chunks")) == 3
    from services import rag, retrieval_currentness

    # This fixture keeps all operator commits in one rollback-only outer
    # transaction. Re-run the real selection comparison on that connection;
    # fresh physical snapshot/ABA races have dedicated HTTP integration tests.
    async def selected(pins, *, evidence_resolver=None, **kwargs):
        async with get_session_factory()() as db:
            return await retrieval_currentness._check_snapshot(db, pins, evidence_resolver)

    monkeypatch.setattr(retrieval_currentness, "check_selected_sources", selected)

    captured = []

    def generate(question, sources, **kwargs):
        captured.extend(sources)
        return rag.extractive_fallback(sources)

    monkeypatch.setattr(rag, "generate_answer", generate)
    search = await client.post("/v1/search", json={"query": "Retained legacy text"})
    assert search.status_code == 200 and search.json()["results"]
    ask = await client.post("/v1/ask", json={"question": "Explain superconductivity"})
    assert ask.status_code == 200 and ask.json()["sources"], ask.text
    assert captured and all(
        source.evidence_provenance["chunk_kind"] == "retained_legacy_snapshot"
        for source in captured
    )
    assert ask.json()["scientific_support_status"] == "not_checked"
    assert all(
        source["evidence_provenance"]["scientific_acceptance"] is False
        for source in ask.json()["sources"]
    )
    assert "Unverified indexed text" in ask.json()["answer"]
    similar = await client.get("/v1/similar/" + rows[0][0]["paper_id"])
    assert similar.status_code == 200 and similar.json()["results"], similar.text
    for response in (search, ask, similar):
        assert response.json()["retrieval_generation"]["generation_id"] == args.generation_id
    index_vector_adapter.clear_disposable()
