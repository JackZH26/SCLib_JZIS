"""Actual SQL replay never upgrades unknown historical text into original evidence."""

from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import get_session_factory
from models.retained_legacy_v1 import PARSER, RENDERER
from services.retained_legacy import canonical, digest, retain_window
from services.rag_evidence import register_chunk_evidence, resolve_chunk_evidence
from services.rag_evidence_contract import validate_candidate
from tests.test_rag_evidence import seed
from tests.test_embedding_receipts import completion
from services.embedding_receipts import append_embedding_receipt
from services.index_generations import stage_generation, load_generation_members
from tests.test_index_generations import resource


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


async def input_window(db):
    import tiktoken

    chunk_id, _ = await seed(db, text="Retained legacy Unicode 超导 text\nwith whitespace.\t")
    chunk, paper = (
        await db.execute(
            sa.text(
                "SELECT to_jsonb(c),public.sclib_index_paper_snapshot_v1(to_jsonb(p)) "
                "FROM chunks c JOIN papers p ON p.id=c.paper_id WHERE c.id=:id"
            ),
            {"id": chunk_id},
        )
    ).one()
    paper_raw = canonical(paper)
    source_raw = canonical({"chunk": chunk, "paper_sha256": digest(paper_raw)})
    text = chunk["text"]
    value = {
        "source_sha256": digest(source_raw),
        "char_start": 0,
        "char_end": len(text),
        "prefix": "",
        "content_sha256": digest(text),
        "local_tokens": len(tiktoken.get_encoding("cl100k_base").encode(text)),
        "input_characters": len(text),
        "input_utf8_bytes": len(text.encode()),
        "embedding_input_admissible": True,
    }
    value["id"] = "ls1_" + digest(canonical({"version": RENDERER, **value}))
    return (
        chunk,
        value,
        dict(
            pack_sha256="a" * 64,
            source_seq=1,
            source_raw=source_raw,
            paper_raw=paper_raw,
            member_seq=1,
            input_partition=1,
            member_raw=canonical(value),
        ),
    )


async def test_retained_window_can_be_embedded_and_staged_without_fabricated_parser(db_session):
    chunk, value, args = await input_window(db_session)
    first = await retain_window(db_session, **args)
    assert await retain_window(db_session, **args) == first
    original = await db_session.scalar(
        sa.text("SELECT to_jsonb(c) FROM chunks c WHERE id=:id"), {"id": chunk["id"]}
    )
    assert original == chunk
    descriptor = (await resolve_chunk_evidence(db_session, [value["id"]]))[value["id"]]
    assert descriptor["chunk_kind"] == "retained_legacy_snapshot"
    assert descriptor["permission_status"] == descriptor["root_status"] == "unresolved"
    assert (
        descriptor["parent_result_revision_id"] is None and descriptor["extraction_version"] is None
    )
    assert not descriptor["scientific_acceptance"] and not descriptor["support_eligible"]
    vector, receipt = completion(chunk["text"])
    completed = await append_embedding_receipt(
        db_session, chunk_id=value["id"], vector=vector, receipt=receipt, dry_run=False
    )
    staged = await stage_generation(
        db_session,
        generation_id=uuid4(),
        resource=resource(),
        dry_run=False,
        items=[
            {
                "chunk_id": value["id"],
                "receipt_id": completed["receipt_id"],
                "vector": vector,
                "parser_version": PARSER,
            }
        ],
    )
    members = await load_generation_members(db_session, generation_id=staged["generation_id"])
    assert len(members) == 1 and members[0]["snapshot_json"]["text"] == chunk["text"]


@pytest.mark.parametrize(
    "field,value", [("source_raw", "{}"), ("paper_raw", "{}"), ("member_seq", 0)]
)
async def test_invalid_replay_leaves_no_rows(db_session, field, value):
    _, _, args = await input_window(db_session)
    args[field] = value
    with pytest.raises((ValueError, KeyError)):
        await retain_window(db_session, **args)
    assert await db_session.scalar(sa.text("SELECT count(*) FROM legacy_index_windows")) == 0


async def test_bare_kind_label_cannot_bypass_retained_source_binding(db_session):
    chunk, value, _ = await input_window(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await register_chunk_evidence(
                db_session,
                chunk_id=chunk["id"],
                dry_run=False,
                candidate={
                    "version": "rag-evidence/1.0.0",
                    "chunk_kind": "retained_legacy_snapshot",
                    "rendering_version": RENDERER,
                    "source_locator": {"char_start": 0, "char_end": len(chunk["text"])},
                    "unresolved_reason": "legacy_unresolved",
                },
            )


async def test_retained_history_is_immutable_and_source_drift_rejected(db_session):
    chunk, value, args = await input_window(db_session)
    await db_session.execute(
        sa.text("UPDATE chunks SET text='changed' WHERE id=:id"), {"id": chunk["id"]}
    )
    with pytest.raises(DBAPIError):
        await retain_window(db_session, **args)
    assert await db_session.scalar(sa.text("SELECT count(*) FROM legacy_index_sources")) == 0
    await db_session.execute(
        sa.text("UPDATE chunks SET text=:text WHERE id=:id"),
        {"id": chunk["id"], "text": chunk["text"]},
    )
    await retain_window(db_session, **args)
    for table in ("legacy_index_papers", "legacy_index_sources", "legacy_index_windows"):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(sa.text(f"DELETE FROM {table}"))


@pytest.mark.parametrize(
    "change",
    [
        {"rendering_version": "old-parser/1"},
        {"source_capture_id": str(uuid4())},
        {"unresolved_reason": "original_binding_unreviewed"},
        {"source_locator": {}},
    ],
)
def test_candidate_cannot_claim_historical_parser_or_capture(change):
    with pytest.raises(ValueError):
        validate_candidate(
            {
                "version": "rag-evidence/1.0.0",
                "chunk_kind": "retained_legacy_snapshot",
                "rendering_version": RENDERER,
                "source_locator": {"char_start": 0, "char_end": 1},
                "unresolved_reason": "legacy_unresolved",
                **change,
            }
        )


async def test_bulk_completion_replay_matches_single_receipt_and_removes_only_new_chunks(
    db_session,
):
    from services.retained_corpus_import import import_completions, remove_replayed_chunks
    from services.embedding_receipts import append_embedding_receipt
    from tests.test_embedding_receipts import completion

    chunk, value, args = await input_window(db_session)
    vector, receipt = completion(chunk["text"])
    items = await import_completions(
        db_session, entries=[{**args, "vector": vector, "receipt": receipt}]
    )
    single = await append_embedding_receipt(
        db_session, chunk_id=value["id"], vector=vector, receipt=receipt, dry_run=False
    )
    assert items[0]["receipt_id"] == single["receipt_id"]
    assert (
        await import_completions(
            db_session, entries=[{**args, "vector": vector, "receipt": receipt}]
        )
        == items
    )
    with pytest.raises(ValueError):
        await remove_replayed_chunks(db_session, chunk_ids=[chunk["id"]])
    await remove_replayed_chunks(db_session, chunk_ids=[value["id"]])
    assert (
        await db_session.scalar(
            sa.text("SELECT count(*) FROM chunks WHERE id=:id"), {"id": chunk["id"]}
        )
        == 1
    )
    assert (
        await import_completions(
            db_session, entries=[{**args, "vector": vector, "receipt": receipt}]
        )
        == items
    )


async def test_rewindowing_cannot_escape_original_chunk_restriction(db_session):
    from services import index_retrieval
    from services.retained_corpus_import import remove_replayed_chunks

    chunk, value, args = await input_window(db_session)
    await register_chunk_evidence(
        db_session,
        chunk_id=chunk["id"],
        dry_run=False,
        candidate={
            "version": "rag-evidence/1.0.0",
            "chunk_kind": "abstract",
            "permission_status": "restricted",
        },
    )
    await retain_window(db_session, **args)
    descriptor = (await resolve_chunk_evidence(db_session, [value["id"]]))[value["id"]]
    assert descriptor["permission_status"] == "restricted"
    vector, receipt = completion(chunk["text"])
    completed = await append_embedding_receipt(
        db_session, chunk_id=value["id"], vector=vector, receipt=receipt, dry_run=False
    )
    pin = await stage_generation(
        db_session,
        generation_id=uuid4(),
        resource=resource(),
        dry_run=False,
        items=[
            {
                "chunk_id": value["id"],
                "receipt_id": completed["receipt_id"],
                "vector": vector,
                "parser_version": PARSER,
            }
        ],
    )
    members = await load_generation_members(db_session, generation_id=pin["generation_id"])
    await remove_replayed_chunks(db_session, chunk_ids=[value["id"]])
    await db_session.execute(sa.text("DELETE FROM chunks WHERE id=:id"), {"id": chunk["id"]})
    hydrated = await index_retrieval.hydrate(db_session, pin, [members[0]["vector_id"]])
    evidence = await index_retrieval.resolve_evidence(db_session, list(hydrated.values()))
    assert evidence[members[0]["vector_id"]]["permission_status"] == "restricted"


async def test_readonly_plan_matches_guarded_sql_members_and_rejects_source_drift(db_session):
    from services.retained_corpus_import import plan_completions, import_completions
    from services.index_corpus import prepare_members

    entries, originals = [], []
    identifier = uuid4()
    for n in (1, 2):
        chunk, member, args = await input_window(db_session)
        vector, receipt = completion(chunk["text"])
        entries.append(
            {**args, "source_seq": n, "member_seq": n, "vector": vector, "receipt": receipt}
        )
        originals.append(chunk["id"])
    tables = (
        "chunks",
        "legacy_index_papers",
        "legacy_index_sources",
        "legacy_index_windows",
        "rag_evidence_revisions",
        "embedding_completion_receipts",
        "index_generation_members",
    )

    async def counts():
        return [await db_session.scalar(sa.text("SELECT count(*) FROM " + name)) for name in tables]

    before = await counts()
    plan = await plan_completions(db_session, generation_id=identifier, entries=entries)
    assert await counts() == before
    items = await import_completions(db_session, entries=entries)
    actual = await prepare_members(db_session, generation_id=identifier, items=items)
    assert plan == actual  # Every typed snapshot, receipt ID/hash and vector ID.
    await db_session.execute(
        sa.text("UPDATE chunks SET text=text||' changed' WHERE id=:id"), {"id": originals[0]}
    )
    changed = await counts()
    with pytest.raises(ValueError):
        await plan_completions(db_session, generation_id=identifier, entries=entries)
    assert await counts() == changed
