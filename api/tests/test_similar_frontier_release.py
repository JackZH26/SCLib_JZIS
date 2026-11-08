"""Real source and target governance around a private, fully covered fixture."""

import asyncio
import hashlib
import json
import os
import threading
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from build_similar_frontier import build_slice
from publish_similar_frontier import publish, sealed_members

from models.db import Paper, get_engine, get_session_factory
from services import content_runtime, content_similarity, pgvector_query
from services import similar_frontier_checkpoint as checkpoint
from services.similar_frontier_release import SimilarFrontiers, graph_scope
from tests.test_content_similarity import many_sources as many_sources
from tests.test_index_generations import db_session as db_session

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("SCLIB_PGVECTOR_RUNTIME_TEST") != "1",
        reason="Requires disposable PostgreSQL with vector",
    ),
]


@pytest.mark.parametrize("many_sources", [75], indirect=True)
async def test_sealed_frontiers_preserve_live_results_rights_and_final_snapshot(
    many_sources, tmp_path, monkeypatch
):
    reader, pin, paper = many_sources
    witness = reader._readiness.prepared_witness(pin)
    async with get_session_factory()() as session:
        members = await session.run_sync(
            lambda db: list(sealed_members(db, UUID(pin.content_id), witness.member_count))
        )

    expected = await reader.similar(pin, paper, top_k=50)
    scope = graph_scope(witness)
    path = tmp_path / "builder.sqlite"
    settings = dict(
        logical_index=pin.logical_index,
        event=UUID(pin.activation_event_id),
        build=UUID(pin.build_id),
        content=UUID(pin.content_id),
        max_papers=128,
        interval=0.1,
        minimum_free_bytes=1,
    )
    first = await build_slice(
        get_session_factory(), reader._transport, path, max_sources=1, **settings
    )
    assert first["new_sources"] == 1 and not first["inventory_exhausted"]
    second = await build_slice(
        get_session_factory(), reader._transport, path, max_sources=256, **settings
    )
    assert second["inventory_exhausted"] and second["new_sources"] > 1

    release = publish(
        path, tmp_path, scope, iter(members), sealed_member_count=witness.member_count
    )
    # A second synthetic scope exercises the two-file admission and graph selection.
    standby = replace(
        witness, pin=replace(pin, build_id=str(uuid4())), graph_filenode=witness.graph_filenode + 1
    )
    other_scope = graph_scope(standby)
    with closing(checkpoint.open_existing(path, scope, writable=True)) as db, db:
        db.execute("UPDATE meta SET scope=?", (checkpoint.identity(other_scope),))
    other = publish(
        path, tmp_path, other_scope, iter(members), sealed_member_count=witness.member_count
    )
    reader.similar_frontiers = SimilarFrontiers(
        {pin.build_id: release["sha256"], standby.pin.build_id: other["sha256"]}, tmp_path,
        transport=reader._transport,
    )
    reader.similar_frontiers.require_graph(standby)
    with pytest.raises(ValueError, match="mismatch"):
        reader.similar_frontiers.require_graph(
            replace(witness, graph_filenode=witness.graph_filenode + 1)
        )
    with pytest.raises(ValueError, match="Complete live source"):
        await reader.similar_frontiers.candidates(
            witness, paper, ["0" * 64], ["1" * 64], 15, timeout=3
        )

    live_ann = AsyncMock(side_effect=AssertionError("Checkpoint path issued online ANN"))
    monkeypatch.setattr(reader._transport, "query_many", live_ann)
    reader.similar_carrier = AsyncMock()
    reader.similar_carrier.query_many = live_ann
    assert await reader.similar(pin, paper, top_k=50) == expected
    target = expected.results[0].paper_id
    async with get_session_factory()() as session:
        await session.execute(sa.update(Paper).where(Paper.id == target).values(status="retracted"))
        await session.commit()
    remaining = await reader.similar(pin, paper, top_k=50)
    assert remaining.results and all(row.paper_id != target for row in remaining.results)

    capture = content_similarity.capture

    async def revoke_after_selection(db, selected_pin, chunks):
        selected = await capture(db, selected_pin, chunks)
        if any(item.paper_id == remaining.results[0].paper_id for item in chunks):
            async with get_session_factory()() as fresh:
                await fresh.execute(
                    sa.update(Paper)
                    .where(Paper.id == remaining.results[0].paper_id)
                    .values(status="retracted")
                )
                await fresh.commit()
        return selected

    monkeypatch.setattr(content_similarity, "capture", revoke_after_selection)
    with pytest.raises(content_similarity.ContentSimilarityUnavailable):
        await reader.similar(pin, paper, top_k=50)
    live_ann.assert_not_awaited()
    published = tmp_path / (release["sha256"] + ".sqlite")
    published.unlink()
    with pytest.raises(FileNotFoundError):
        reader.similar_frontiers.require_graph(witness)


async def test_runtime_requires_both_sources_and_preserves_semantic_route(monkeypatch):
    from services.retrieval_readiness import ProjectionReadiness
    pin = SimpleNamespace(logical_index="sclib-main", profile_json="{}")
    witness = object()
    monkeypatch.setattr(content_runtime.ContentRetriever, "pin", AsyncMock(return_value=pin))
    monkeypatch.setattr(content_runtime.ContentRetriever, "_pin", lambda self, actual: None)
    monkeypatch.setattr(ProjectionReadiness, "prepare", AsyncMock(return_value=True))
    monkeypatch.setattr(ProjectionReadiness, "ready", AsyncMock(return_value=True))
    monkeypatch.setattr(ProjectionReadiness, "prepared_witness", lambda self, actual: witness)
    frontiers = MagicMock()
    frontiers.close = AsyncMock()
    carrier = AsyncMock()
    monkeypatch.setattr(content_runtime, "get_settings", lambda: SimpleNamespace(
        retrieval_backend="pgvector", retrieval_logical_index=pin.logical_index,
        retrieval_use_similar_frontiers=True, retrieval_use_similar_carrier=True,
    ))
    monkeypatch.setattr(content_runtime.SimilarFrontiers, "from_release", lambda transport: frontiers)
    monkeypatch.setattr(content_runtime.LiveSimilarCarrier, "from_release", lambda transport: carrier)
    from services import content_retrieval
    vector = object()
    monkeypatch.setattr(content_retrieval.provider_resilience, "run_blocking", AsyncMock(return_value=vector))
    async with content_runtime.managed_reader() as reader:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(content_reader=reader)))
        frontiers.require_graph.assert_called_once_with(witness)
        carrier.prepare.assert_awaited_once_with(witness)
        await content_runtime.check_ready(request)
        assert frontiers.require_graph.call_count == carrier.prepare.await_count == 2
        await reader._semantic(pin, "query", top_k=20, year_min=None, year_max=None)
        carrier.query.assert_awaited_once_with(witness, vector, top_k=20, year_min=None, year_max=None)
        frontiers.require_graph.side_effect = ValueError("Changed frontier")
        with pytest.raises(ValueError, match="Changed frontier"):
            await content_runtime.check_ready(request)
    carrier.close.assert_awaited_once()
    frontiers.close.assert_awaited_once()


async def test_signed_paper_subset_uses_native_once_on_miss_and_fails_closed_on_damage(
    many_sources, tmp_path, monkeypatch
):
    reader, pin, paper = many_sources
    witness = reader._readiness.prepared_witness(pin)
    standby = replace(witness, pin=replace(pin, build_id=str(uuid4())))
    approved = {}
    source = "1" * 64
    excluded = ["2" * 64]
    coverage = {"mode": "paper_subset", "members": 1, "papers": 1}
    hits = [
        dict(vector_id=f"v{i}", paper_id=f"p{i}", distance=i / 100,
             content_sha256="3" * 64, vector_sha256="4" * 64,
             chunk_revision_sha256="5" * 64)
        for i in range(checkpoint.WIDTH)
    ]
    for graph in (witness, standby):
        scope = graph_scope(graph)
        path = tmp_path / f"{graph.pin.build_id}.sqlite"
        checkpoint.create(path, scope)
        with closing(checkpoint.open_existing(path, scope, writable=True)) as db, db:
            checkpoint.save(db, "covered", source, checkpoint.exclusions_digest(excluded), hits)
            db.execute("CREATE TABLE publication(singleton INTEGER PRIMARY KEY,coverage TEXT)")
            db.execute("INSERT INTO publication VALUES(1,?)", (json.dumps(coverage),))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.rename(tmp_path / (digest + ".sqlite"))
        approved[graph.pin.build_id] = digest
    frontiers = SimilarFrontiers(approved, tmp_path, transport=reader._transport)
    assert frontiers.needs_live_carrier and frontiers.covers_paper(witness, "covered")
    assert not frontiers.covers_paper(witness, paper)
    found = await frontiers.candidates(witness, "covered", [source], excluded, 6, timeout=3)
    assert [hit.vector_id for hit in found[0].neighbors] == [f"v{i}" for i in range(6)]
    with pytest.raises(ValueError, match="Complete live source"):
        await frontiers.candidates(witness, "covered", [source], ["6" * 64], 6, timeout=3)
    expected = await reader.similar(pin, paper, top_k=6)
    async def native(graph, vectors, **options):
        return await reader._transport.query_many(graph.pin.projection, vectors, **options)
    carrier = AsyncMock()
    carrier.query_many.side_effect = native
    reader.similar_frontiers, reader.similar_carrier = frontiers, carrier
    monkeypatch.setattr(frontiers, "candidates", AsyncMock(side_effect=AssertionError("uncovered paper")))
    assert await reader.similar(pin, paper, top_k=6) == expected
    carrier.query_many.assert_awaited_once()
    frontiers.candidates.assert_not_awaited()
    (tmp_path / (approved[pin.build_id] + ".sqlite")).unlink()
    with pytest.raises(content_similarity.ContentSimilarityUnavailable):
        await reader.similar(pin, paper, top_k=6)
    carrier.query_many.assert_awaited_once()


@pytest.mark.parametrize("disconnect", [True, False])
async def test_interrupted_lookup_keeps_the_real_global_slot_until_file_read_ends(disconnect):
    transport = pgvector_query.PgvectorQueries(get_engine())
    # Exercise lifecycle and real advisory locks independently of the fixture's file format.
    frontiers = object.__new__(SimilarFrontiers)
    frontiers._transport = transport
    frontiers._pending = set()
    started, finish = threading.Event(), threading.Event()

    def read(*_):
        started.set()
        if not finish.wait(timeout=8):
            raise AssertionError("test did not release file read")

    frontiers._read = read

    async def available():
        async with get_engine().connect() as conn, conn.begin():
            rows = await conn.execute(sa.text("SELECT pg_try_advisory_xact_lock(k) "
                "FROM unnest(CAST(:keys AS bigint[])) AS s(k)"), {"keys": list(pgvector_query._SQL_SLOT_KEYS)})
            return sum(rows.scalars())

    call = asyncio.create_task(frontiers.candidates(None, None, (), (), 1, timeout=3))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        if disconnect:
            call.cancel()
        with pytest.raises(asyncio.CancelledError if disconnect else TimeoutError):
            await call
        assert await available() == 3
    finally:
        finish.set()
        await frontiers.close()
    assert await available() == 4
