"""Real database authorization/currentness around the new candidate boundary.

The small owned fixture exercises the exact-cohort branch. Native graph and
large-cohort parity are verified separately on the private captured graph.
"""
import os
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa

from models.db import Paper, get_session_factory
from services import content_similarity
from services.similar_frontier_release import graph_scope
from services.similar_live_carrier import LiveSimilarCarrier
from tests.test_content_similarity import many_sources as many_sources
from tests.test_index_generations import db_session as db_session

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST') != '1', reason='Requires owned PostgreSQL/vector')]


def select_live(reader, pin, monkeypatch):
    witness = reader._readiness.prepared_witness(pin)
    standby = replace(witness, pin=replace(pin, build_id=str(uuid4())), graph_filenode=witness.graph_filenode + 1)
    approved = {item.pin.build_id: {'scope': graph_scope(item), 'graph_bytes': item.graph_bytes,
                'segments': [{'part': 0, 'size': item.graph_bytes, 'source_stream_sha256': '3' * 64}],
                'reader_sha256': '4' * 64, 'postgres_image_digest': 'sha256:' + '5' * 64}
                for item in (witness, standby)}
    reader.similar_carrier = LiveSimilarCarrier(reader._transport, approved)
    monkeypatch.setattr(reader.similar_carrier, '_pool', AsyncMock(
        side_effect=AssertionError('Exact small cohort needs no graph connection')))
    monkeypatch.setattr(reader._transport, 'query_many', AsyncMock(
        side_effect=AssertionError('Selected live transport cannot fall back to old ANN')))


@pytest.mark.parametrize('many_sources', [75], indirect=True)
async def test_complete_source_batch_keeps_values_order_and_live_source_target_rights(many_sources, monkeypatch):
    reader, pin, paper = many_sources
    expected = await reader.similar(pin, paper, top_k=50)
    assert expected.source_vector_count == 20 and expected.results
    select_live(reader, pin, monkeypatch)
    assert await reader.similar(pin, paper, top_k=50) == expected
    target = expected.results[0].paper_id
    async with get_session_factory()() as session:
        await session.execute(sa.update(Paper).where(Paper.id == target).values(status='retracted'))
        await session.commit()
    value = await reader.similar(pin, paper, top_k=50)
    assert all(row.paper_id != target for row in value.results)
    async with get_session_factory()() as session:
        await session.execute(sa.update(Paper).where(Paper.id == paper).values(status='retracted'))
        await session.commit()
    spy = AsyncMock(side_effect=AssertionError('Retracted source must schedule no candidate work'))
    monkeypatch.setattr(reader.similar_carrier, 'query_many', spy)
    assert (await reader.similar(pin, paper, top_k=50)).results == ()
    spy.assert_not_awaited()


@pytest.mark.parametrize('many_sources', [75], indirect=True)
async def test_live_candidate_result_is_discarded_when_selected_target_changes(many_sources, monkeypatch):
    reader, pin, paper = many_sources
    expected = await reader.similar(pin, paper, top_k=50)
    select_live(reader, pin, monkeypatch)
    capture = content_similarity.capture
    changed = False

    async def change_after_capture(db, backend, chunks):
        nonlocal changed
        selected = await capture(db, backend, chunks)
        if not changed and any(chunk.paper_id == expected.results[0].paper_id for chunk in chunks):
            changed = True
            async with get_session_factory()() as session:
                await session.execute(sa.update(Paper).where(Paper.id == expected.results[0].paper_id).values(status='retracted'))
                await session.commit()
        return selected

    monkeypatch.setattr(content_similarity, 'capture', change_after_capture)
    with pytest.raises(content_similarity.ContentSimilarityUnavailable):
        await reader.similar(pin, paper, top_k=50)
    assert changed
