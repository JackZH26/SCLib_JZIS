"""Real source and target governance around a private, fully covered fixture."""

import os
from contextlib import closing
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from build_similar_frontier import build_slice
from publish_similar_frontier import publish, sealed_members

from models.db import Paper, get_session_factory
from services import content_similarity
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
        {pin.build_id: release["sha256"], standby.pin.build_id: other["sha256"]}, tmp_path
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
