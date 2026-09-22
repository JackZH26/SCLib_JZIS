"""Partition root, complete readback and activation with owned synthetic SQL."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import get_session_factory
from services import index_corpus as corpus, index_generations as generations
from services.embedding_receipts import append_embedding_receipt
from services.retained_legacy import retain_window, canonical, digest
from tests.test_embedding_receipts import completion
from tests.test_index_generations import resource
from tests.test_retained_legacy import input_window


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


async def setup_corpus(db, count=2):
    identifier = uuid4()
    plans, inputs = [], []
    for n in range(1, count + 1):
        chunk, value, args = await input_window(db)
        args.update(source_seq=n, member_seq=n)
        await retain_window(db, **args)
        vector, receipt = completion(chunk["text"])
        received = await append_embedding_receipt(
            db, chunk_id=value["id"], vector=vector, receipt=receipt, dry_run=False
        )
        item = {"chunk_id": value["id"], "receipt_id": received["receipt_id"], "vector": vector}
        members = await corpus.prepare_members(db, generation_id=identifier, items=[item])
        plans.append(corpus.partition_plan(members, n))
        inputs.append([item])
    pin = await corpus.create_corpus(
        db,
        generation_id=identifier,
        resource=resource(),
        pack_sha256="a" * 64,
        input_manifest_sha256="b" * 64,
        expected_sources=count,
        partitions=plans,
    )
    return pin, plans, inputs


async def observe(db, pin, part, *, wrong=False):
    members = await corpus.partition_members(
        db, generation_id=pin["generation_id"], partition_id=part
    )
    vectors = [
        {key: row[key] for key in ("vector_id", "content_sha256", "vector_sha256")}
        for row in members
    ]
    if wrong:
        vectors[0]["content_sha256"] = "0" * 64
    return await corpus.record_partition_observation(
        db,
        generation_id=pin["generation_id"],
        partition_id=part,
        observation={
            "version": "sclib-index-observation/1.0.0",
            "observation_id": str(uuid4()),
            "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "resource": pin["resource"],
            "profile": pin["profile"],
            "adapter_version": "synthetic/1",
            "full_inventory_observed": False,
            "vectors": vectors,
        },
    )


async def test_complete_partition_root_activates_without_changing_original_sources(db_session):
    pin, plans, inputs = await setup_corpus(db_session)
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    observations = []
    for part, items in enumerate(inputs, 1):
        assert (
            await corpus.stage_partition(
                db_session, generation_id=pin["generation_id"], partition_id=part, items=items
            )
            == plans[part - 1]
        )
        assert (
            await corpus.stage_partition(
                db_session, generation_id=pin["generation_id"], partition_id=part, items=items
            )
            == plans[part - 1]
        )
        observations.append((await observe(db_session, pin, part))["id"])
    actual_root = await db_session.scalar(
        sa.text("SELECT public.sclib_corpus_root_v1(:id)"), {"id": pin["generation_id"]}
    )
    assert actual_root == pin["manifest_sha256"] == corpus.root_manifest(plans)
    result = await corpus.validate_corpus(
        db_session,
        generation_id=pin["generation_id"],
        observation_ids=observations,
        started_at=start,
    )
    assert result["outcome"] == "validated"
    active = await generations.activate_generation(
        db_session,
        generation_id=pin["generation_id"],
        validation_id=result["validation_id"],
        expected_event_id=None,
        idempotency_key="synthetic-corpus-first",
        dry_run=False,
    )
    assert (await generations.load_active_generation(db_session))["generation_id"] == pin[
        "generation_id"
    ]
    assert active["manifest_sha256"] == actual_root


async def test_partial_or_bad_readback_cannot_validate_or_activate(db_session):
    pin, plans, inputs = await setup_corpus(db_session)
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    await corpus.stage_partition(
        db_session, generation_id=pin["generation_id"], partition_id=1, items=inputs[0]
    )
    assert (
        await db_session.scalar(
            sa.text("SELECT public.sclib_corpus_root_v1(:id)"), {"id": pin["generation_id"]}
        )
        is None
    )
    first = await observe(db_session, pin, 1)
    with pytest.raises(DBAPIError):
        await corpus.validate_corpus(
            db_session,
            generation_id=pin["generation_id"],
            observation_ids=[first["id"]],
            started_at=start,
        )
    await corpus.stage_partition(
        db_session, generation_id=pin["generation_id"], partition_id=2, items=inputs[1]
    )
    bad = await observe(db_session, pin, 2, wrong=True)
    assert bad["outcome"] == "rejected"
    with pytest.raises(DBAPIError):
        await corpus.validate_corpus(
            db_session,
            generation_id=pin["generation_id"],
            observation_ids=[first["id"], bad["id"]],
            started_at=start,
        )
    assert await generations.load_active_generation(db_session) is None


async def test_plan_member_change_and_seal_mutation_rejected(db_session):
    pin, _, inputs = await setup_corpus(db_session)
    changed = [{**inputs[0][0], "vector": [0.3] * 768}]
    with pytest.raises(ValueError):
        await corpus.stage_partition(
            db_session, generation_id=pin["generation_id"], partition_id=1, items=changed
        )
    assert await db_session.scalar(sa.text("SELECT count(*) FROM index_corpus_member_routes")) == 0
    await corpus.stage_partition(
        db_session, generation_id=pin["generation_id"], partition_id=1, items=inputs[0]
    )
    for table in (
        "index_corpora",
        "index_corpus_partitions",
        "index_corpus_member_routes",
        "index_corpus_seals",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(sa.text(f"DELETE FROM {table}"))


async def test_route_prefix_cannot_skip_forge_or_understate_actual_member_bytes(db_session):
    from models.db import Base

    _, _, batches = await setup_corpus(db_session)
    identifier = uuid4()
    items = [item for batch in batches for item in batch]
    members = await corpus.prepare_members(db_session, generation_id=identifier, items=items)
    plan = corpus.partition_plan(members, 1)
    await corpus.create_corpus(
        db_session,
        generation_id=identifier,
        resource=resource(),
        pack_sha256="a" * 64,
        input_manifest_sha256="b" * 64,
        expected_sources=2,
        partitions=[plan],
    )
    routes, cumulative = [], 0
    for ordinal, member in enumerate(members, 1):
        cumulative += member["snapshot_bytes"]
        routes.append(
            dict(
                generation_id=identifier,
                chunk_key=member["chunk_key"],
                partition_id=1,
                ordinal=ordinal,
                snapshot_bytes=member["snapshot_bytes"],
                cumulative_snapshot_bytes=cumulative,
            )
        )
    table = Base.metadata.tables["index_corpus_member_routes"]
    for attack in (
        [routes[1]],  # Missing preceding slot.
        [{**routes[0], "cumulative_snapshot_bytes": routes[0]["snapshot_bytes"] + 1}],
        [routes[0], {**routes[1], "cumulative_snapshot_bytes": cumulative - 1}],
        [routes[0], {**routes[1], "ordinal": 3}],
        [routes[0], {**routes[1], "ordinal": 1}],
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(table.insert(), attack)
    # A malicious route can balance its total while understating one member;
    # insertion of the actual immutable member must still reject it.
    balanced = [
        {
            **routes[0],
            "snapshot_bytes": routes[0]["snapshot_bytes"] - 1,
            "cumulative_snapshot_bytes": routes[0]["cumulative_snapshot_bytes"] - 1,
        },
        {**routes[1], "snapshot_bytes": routes[1]["snapshot_bytes"] + 1},
    ]
    with pytest.raises(DBAPIError, match="corpus_exact_planned_retained_member_required"):
        async with db_session.begin_nested():
            await db_session.execute(table.insert(), balanced)
            await db_session.execute(
                Base.metadata.tables["index_generation_members"].insert(),
                [{k: v for k, v in members[0].items() if k != "snapshot_bytes"}],
            )
    await corpus.stage_partition(db_session, generation_id=identifier, partition_id=1, items=items)
    assert await db_session.scalar(
        sa.text("SELECT public.sclib_corpus_root_v1(:id)"), {"id": identifier}
    ) == corpus.root_manifest([plan])


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [
            {
                "partition_id": 2,
                "expected_member_count": 1,
                "snapshot_bytes": 1,
                "manifest_sha256": "a" * 64,
            }
        ],
        [
            {
                "partition_id": 1,
                "expected_member_count": 1001,
                "snapshot_bytes": 1,
                "manifest_sha256": "a" * 64,
            }
        ],
    ],
)
def test_root_requires_bounded_contiguous_complete_plan(bad):
    with pytest.raises(ValueError):
        corpus.root_manifest(bad)


async def test_1001_members_keep_selected_formula_and_paper_reads_bounded(db_session, monkeypatch):
    import tiktoken
    from models.retained_legacy_v1 import RENDERER
    from tests.test_rag_evidence import seed
    from services import retrieval, index_retrieval, scientific_query_lookup
    from services.scientific_query import interpret_scientific_query

    identifier = uuid4()
    original_id, _ = await seed(db_session, text="H3S " * 1001)
    original, paper = (
        await db_session.execute(
            sa.text(
                "SELECT to_jsonb(c),public.sclib_index_paper_snapshot_v1(to_jsonb(p)) "
                "FROM chunks c JOIN papers p ON p.id=c.paper_id WHERE c.id=:id"
            ),
            {"id": original_id},
        )
    ).one()
    paper_raw = canonical(paper)
    source_raw = canonical({"chunk": original, "paper_sha256": digest(paper_raw)})
    vector, receipt = completion("H3S ")
    entries = []
    from services.retained_corpus_import import import_completions, remove_replayed_chunks

    for n in range(1001):
        value = {
            "source_sha256": digest(source_raw),
            "char_start": n * 4,
            "char_end": (n + 1) * 4,
            "prefix": "",
            "content_sha256": digest("H3S "),
            "local_tokens": len(tiktoken.get_encoding("cl100k_base").encode("H3S ")),
            "input_characters": 4,
            "input_utf8_bytes": 4,
            "embedding_input_admissible": True,
        }
        value["id"] = "ls1_" + digest(canonical({"version": RENDERER, **value}))
        entries.append(
            dict(
                pack_sha256="a" * 64,
                source_seq=1,
                source_raw=source_raw,
                paper_raw=paper_raw,
                member_seq=n + 1,
                input_partition=n // 1000 + 1,
                member_raw=canonical(value),
                vector=vector,
                receipt=receipt,
            )
        )
    inputs = []
    for offset in range(0, len(entries), 100):
        inputs.extend(await import_completions(db_session, entries=entries[offset : offset + 100]))
    batches = [inputs[:1000], inputs[1000:]]
    plans = [
        corpus.partition_plan(
            await corpus.prepare_members(db_session, generation_id=identifier, items=items), n
        )
        for n, items in enumerate(batches, 1)
    ]
    pin = await corpus.create_corpus(
        db_session,
        generation_id=identifier,
        resource=resource(),
        pack_sha256="a" * 64,
        input_manifest_sha256="b" * 64,
        expected_sources=1,
        partitions=plans,
    )
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    observations = []
    for n, items in enumerate(batches, 1):
        await corpus.stage_partition(
            db_session, generation_id=identifier, partition_id=n, items=items
        )
        observations.append((await observe(db_session, pin, n))["id"])
    for batch in batches:
        await remove_replayed_chunks(db_session, chunk_ids=[item["chunk_id"] for item in batch])
    assert (
        await db_session.scalar(
            sa.text("SELECT count(*) FROM chunks WHERE id=:id"), {"id": original_id}
        )
        == 1
    )
    validated = await corpus.validate_corpus(
        db_session, generation_id=identifier, observation_ids=observations, started_at=started
    )
    active = await generations.activate_generation(
        db_session,
        generation_id=identifier,
        validation_id=validated["validation_id"],
        expected_event_id=None,
        idempotency_key="synthetic-1001",
        dry_run=False,
    )
    pin["activation_event_id"] = active["activation_event_id"]
    with pytest.raises(generations.IndexGenerationError, match="bounded"):
        await generations.load_generation_members(db_session, generation_id=identifier)
    real = generations.load_generation_members
    selections = []

    async def selected(db, *, generation_id, vector_ids=None, **kwargs):
        assert vector_ids is not None and len(vector_ids) <= 20
        selections.append(len(vector_ids))
        return await real(db, generation_id=generation_id, vector_ids=vector_ids, **kwargs)

    monkeypatch.setattr(generations, "load_generation_members", selected)
    hits = await retrieval.formula_lexical_search(
        db_session, interpret_scientific_query("H3S"), pin, limit=7
    )
    assert len(hits) == 7 and all(hit.score == 1 for hit in hits)
    assert len(await index_retrieval.paper_chunks(db_session, pin, paper["id"])) == 20
    assert selections == [7, 20]
    prepared = await scientific_query_lookup.prepare_scientific_lookup(
        db_session, pin, interpret_scientific_query("H3S Tc > 100 K")
    )
    assert prepared.outcome.status.status == "completed" and prepared.outcome.results == []
    assert prepared.outcome.status.reason_codes == ["retained_legacy_no_extraction_parents"]
