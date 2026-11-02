"""Real v2 origin/payload/current rights checks, never public route acceptance."""
from __future__ import annotations

import os
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from models.db import Chunk, Paper
from services import retrieval_activation as activation_service
from services import retrieval_content as content_service
from services import retrieval_members as service
from services.pgvector_query import CandidateBatch, ProjectionSpec, SqlNeighbor
from services.rag_evidence import register_chunk_evidence
from tests.test_index_generations import db_session as db_session
from tests.test_research_freeze import state
from tests.test_retrieval_activation import accepted, activation, prepared_build
from tests.test_retrieval_content import publication

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST') != '1', reason='Requires fresh owned vector runner')]


async def active_content(db, tmp_path=None):
    first = await prepared_build(db)
    event = await activation_service.activate_backend(db, **activation(first, await accepted(db, first)), dry_run=False)
    if tmp_path is not None:
        _, _, publication_result = await publication(db, tmp_path)
        plan = await content_service.stage_native_content(db, base_content_id=first['content_id'],
            publication_ids=[publication_result['publication_id']], dry_run=False)
        refs = await content_service.source_reference_page(db, content_id=plan['content_id'])
        await content_service.append_content_partition(db, content_id=plan['content_id'], partition_id=0, references=refs, dry_run=False)
        await content_service.seal_content(db, content_id=plan['content_id'], dry_run=False)
        second = await prepared_build(db, content_id=plan['content_id'], logical_index=first['logical_index'])
        await activation_service.activate_backend(db, **activation(second, await accepted(db, second),
            predecessor=event['activation_event_id'], old=False), dry_run=False)
    pin = await activation_service.load_active_backend(db, logical_index=first['logical_index'])
    ids = list((await db.execute(sa.text('SELECT vector_id FROM retrieval_content_members_v2 '
        'WHERE content_id=:id ORDER BY vector_id COLLATE "C"'), {'id': UUID(pin.content_id)})).scalars())
    return pin, ids, first


async def test_legacy_and_native_exact_origins_bytes_and_no_private_archive_paths(db_session, tmp_path):
    pin, ids, _ = await active_content(db_session, tmp_path)
    before = await state(db_session)
    rows = await service.load_members(db_session, pin, ids)
    assert len(rows) == 2 and {row['origin_kind'] for row in rows} == {'legacy_v1', 'native_v2'}
    for row in rows:
        assert row['content_id'] == pin.content_id and len(row['vector_bytes']) == 3072
        assert row['record_sha256'] == row['origin_record_sha256']
        assert 'archive_relative_path' not in row and 'source_uri' not in row
        if row['origin_kind'] == 'native_v2':
            assert row['vector_id'].startswith('rv2_') and 'generation_id' not in row
            assert row['origin_generation_id'] is None
        else:
            assert row['generation_id'] == row['origin_generation_id']
    assert await state(db_session) == before


async def test_hydration_survives_mutable_chunk_deletion_and_preserves_frozen_attribution(db_session, tmp_path):
    pin, ids, _ = await active_content(db_session, tmp_path)
    before = await service.hydrate(db_session, pin, ids)
    from services.index_retrieval import attribution
    for chunk in before.values():
        assert chunk.generation_pin['version'] == 'sclib-retrieval-pin/2.0.0'
        await db_session.execute(sa.delete(Chunk).where(Chunk.id == chunk.member['chunk_key']))
        await db_session.execute(sa.update(Paper).where(Paper.id == chunk.paper_id).values(title='Mutable changed title'))
    after = await service.hydrate(db_session, pin, ids)
    assert {key: row.text for key, row in after.items()} == {key: row.text for key, row in before.items()}
    for key, row in after.items():
        assert attribution(row).title == attribution(before[key]).title != 'Mutable changed title'
    evidence = await service.resolve_evidence(db_session, pin, list(after.values()))
    assert set(evidence) == set(ids)
    assert all(row['support_eligible'] is False and row['scientific_acceptance'] is False for row in evidence.values())


@pytest.mark.parametrize('change', ['permission', 'source', 'renderer'])
async def test_live_holds_survive_native_and_legacy_snapshot_hydration(db_session, tmp_path, monkeypatch, change):
    from services import rag_evidence
    pin, ids, _ = await active_content(db_session, tmp_path)
    chunks = await service.hydrate(db_session, pin, ids)
    for chunk in chunks.values():
        if change == 'permission':
            await register_chunk_evidence(db_session, chunk_id=chunk.member['chunk_key'], dry_run=False,
                candidate={'version': 'rag-evidence/1.0.0', 'chunk_kind': 'original_passage', 'permission_status': 'restricted'})
            await db_session.execute(sa.delete(Chunk).where(Chunk.id == chunk.member['chunk_key']))
        elif change == 'source':
            await db_session.execute(sa.update(Paper).where(Paper.id == chunk.paper_id).values(status='corrected'))
    if change == 'renderer':
        monkeypatch.setattr(rag_evidence, 'CURRENT_FACT_RENDERER_VERSION', 'changed-synthetic-renderer')
    result = await service.resolve_evidence(db_session, pin, list(chunks.values()))
    assert all(row['permission_status'] == 'restricted' if change == 'permission' else row['currentness'] == 'stale'
               for row in result.values())
    assert all(row['support_eligible'] is False for row in result.values())


async def test_vector_candidates_must_match_every_authoritative_binding_and_exact_pin(db_session):
    pin, ids, _ = await active_content(db_session)
    row, = await service.load_members(db_session, pin, ids)
    hit = SqlNeighbor(**{key: row[key] for key in ('vector_id', 'paper_id', 'content_sha256',
        'vector_sha256', 'chunk_revision_sha256')}, distance=0.25)
    batch = CandidateBatch(pin.projection, (hit,), 'hnsw', False)
    assert await service.verified_hits(db_session, pin, batch) == [(hit.vector_id, 0.75)]
    for key, value in [('paper_id', 'wrong-paper'), ('content_sha256', 'a' * 64),
                       ('vector_sha256', 'b' * 64), ('chunk_revision_sha256', 'c' * 64), ('distance', float('nan'))]:
        with pytest.raises(service.RetrievalMemberError, match='payload'):
            await service.verified_hits(db_session, pin, replace(batch, neighbors=(replace(hit, **{key: value}),)))
    wrong = ProjectionSpec(str(uuid4()), pin.content_id, pin.manifest_sha256)
    with pytest.raises(service.RetrievalMemberError, match='request backend pin'):
        await service.verified_hits(db_session, pin, replace(batch, projection=wrong))
    with pytest.raises(service.RetrievalMemberError, match='unique bounded'):
        await service.verified_hits(db_session, pin, replace(batch, neighbors=(hit, hit)))


async def test_unknown_member_and_forged_ref_or_origin_fail_closed(db_session):
    pin, ids, _ = await active_content(db_session)
    with pytest.raises(service.RetrievalMemberError, match='inventory unavailable'):
        await service.load_members(db_session, pin, ['unknown-member'])
    async with db_session.begin_nested() as savepoint:
        await db_session.execute(sa.text('ALTER TABLE retrieval_content_members_v2 DISABLE TRIGGER USER'))
        await db_session.execute(sa.text("UPDATE retrieval_content_members_v2 SET origin_record_sha256=:sha WHERE content_id=:content"),
                                 {'sha': '0' * 64, 'content': UUID(pin.content_id)})
        with pytest.raises(service.RetrievalMemberError, match='integrity mismatch'):
            await service.load_members(db_session, pin, ids)
        await savepoint.rollback()
    # Deliberate owner-only corruption fixture, not an allowed runtime action.
    await db_session.execute(sa.text('ALTER TABLE index_generation_members DISABLE TRIGGER USER'))
    await db_session.execute(sa.text("UPDATE index_generation_members SET snapshot_json=jsonb_set(snapshot_json,'{text}','\"corrupt\"') WHERE vector_id=:id"),
                             {'id': ids[0]})
    with pytest.raises(service.RetrievalMemberError, match='integrity mismatch'):
        await service.load_members(db_session, pin, ids)


async def test_bytea_settings_reset_and_select_only_reader_can_hydrate(db_session):
    pin, ids, _ = await active_content(db_session)
    await db_session.execute(sa.text("SET LOCAL bytea_output='escape'"))
    assert len(await service.load_members(db_session, pin, ids)) == 1
    assert await db_session.scalar(sa.text('SHOW bytea_output')) == 'escape'
    await db_session.execute(sa.text('GRANT SELECT ON ALL TABLES IN SCHEMA public TO sclib_retrieval_reader'))
    await db_session.execute(sa.text('GRANT USAGE ON SCHEMA retrieval_projection TO sclib_retrieval_reader'))
    async with db_session.begin_nested():
        await db_session.execute(sa.text('SET LOCAL ROLE sclib_retrieval_reader'))
        assert len(await service.load_members(db_session, pin, ids)) == 1
        await db_session.execute(sa.text('RESET ROLE'))


async def test_stale_backend_and_mixed_evidence_are_rejected(db_session):
    pin, ids, _ = await active_content(db_session)
    chunks = await service.hydrate(db_session, pin, ids)
    bad = replace(next(iter(chunks.values())), generation_pin={'version': 'index-read/1.0.0'})
    with pytest.raises(service.RetrievalMemberError, match='Mixed content'):
        await service.resolve_evidence(db_session, pin, [bad])
    next_build = await prepared_build(db_session, content_id=pin.content_id, logical_index=pin.logical_index)
    await activation_service.activate_backend(db_session, **activation(next_build, await accepted(db_session, next_build),
        predecessor=pin.activation_event_id, old=False), dry_run=False)
    with pytest.raises(activation_service.RetrievalActivationError, match='no longer current'):
        await service.load_members(db_session, pin, ids)
