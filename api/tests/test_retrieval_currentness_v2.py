"""V2 fresh final barriers, using only the fresh owned vector test runner."""
from dataclasses import replace
import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Chunk, Paper, PaperWorkMap, Work, get_engine
from services import retrieval_activation as activation_service
from services import retrieval_currentness as currentness
from services import retrieval_members
from services.retrieval_groups import resolve_grouping_bindings
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import project_source_occurrences, resolve_explicit_materials, source_visibility
from tests.test_index_generations import db_session as db_session
from tests.test_retrieval_members import active_content
from tests.test_retrieval_activation import accepted, activation, prepared_build

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST') != '1', reason='Requires fresh owned vector runner')]


async def selected(db, backend):
    ids = list((await db.execute(sa.text('SELECT vector_id FROM retrieval_content_members_v2 '
        'WHERE content_id=CAST(:id AS uuid) ORDER BY vector_id COLLATE "C"'), {'id': backend.content_id})).scalars())
    chunks = list((await retrieval_members.hydrate(db, backend, ids)).values())
    descriptors = await retrieval_members.resolve_evidence(db, backend, chunks)
    statuses = await resolve_paper_lifecycle(db, {chunk.paper_id for chunk in chunks})
    groups = await resolve_grouping_bindings(db, {chunk.paper_id for chunk in chunks})
    linked = await resolve_explicit_materials(db, [chunk.materials_mentioned for chunk in chunks])
    pins = []
    for chunk in chunks:
        status = statuses[chunk.paper_id]
        occurrences, summary = project_source_occurrences(chunk.materials_mentioned, paper_status=status,
            linked_materials=linked, container_paper_id=chunk.paper_id)
        visibility = source_visibility(status)
        visibility['warning_codes'] = sorted(set(visibility['warning_codes'] + summary['warning_codes']))
        pins.append(currentness.selection_pin(chunk, material_evidence=occurrences,
            source_review=visibility, evidence=descriptors[chunk.id], grouping_binding=groups[chunk.paper_id]))
    return pins, chunks


async def check(pins, backend, **kwargs):
    async def resolver(db, chunks):
        return await retrieval_members.resolve_evidence(db, backend, chunks)
    return await currentness.check_selected_sources(pins, backend_pin=backend, evidence_resolver=resolver, **kwargs)


async def test_fresh_native_and_legacy_barrier_survives_mutable_chunk_deletion(db_session, tmp_path):
    backend, _, _ = await active_content(db_session, tmp_path)
    pins, chunks = await selected(db_session, backend)
    await db_session.commit()
    assert (await check(pins, backend)).status == 'unchanged'
    async with AsyncSession(get_engine()) as writer:
        await writer.execute(sa.delete(Chunk).where(Chunk.id.in_([chunk.member['chunk_key'] for chunk in chunks])))
        await writer.commit()
    checked = await check(pins, backend)
    assert checked.status == 'unchanged' and checked.snapshot_at
    assert 'scientific_acceptance' not in checked.__slots__


@pytest.mark.parametrize('change', ['source_hold', 'group_mapping', 'renderer', 'permission'])
async def test_final_v2_barrier_reads_live_holds_mapping_and_renderer(db_session, tmp_path, monkeypatch, change):
    backend, _, _ = await active_content(db_session, tmp_path)
    pins, chunks = await selected(db_session, backend)
    await db_session.commit()
    async with AsyncSession(get_engine()) as writer:
        if change == 'source_hold':
            await writer.execute(sa.update(Paper).where(Paper.id == chunks[0].paper_id).values(status='corrected'))
        elif change == 'group_mapping':
            work = Work(canonical_title='Synthetic v2 mapping ' + uuid4().hex, publication_status='active')
            writer.add(work)
            await writer.flush()
            writer.add(PaperWorkMap(paper_id=chunks[0].paper_id, work_id=work.id,
                match_method='manual', review_status='accepted'))
        elif change == 'permission':
            from services.rag_evidence import register_chunk_evidence
            await register_chunk_evidence(writer, chunk_id=chunks[0].member['chunk_key'], dry_run=False,
                candidate={'version': 'rag-evidence/1.0.0', 'chunk_kind': 'original_passage',
                    'permission_status': 'restricted'})
            await writer.execute(sa.delete(Chunk).where(Chunk.id == chunks[0].member['chunk_key']))
        await writer.commit()
    if change == 'renderer':
        from services import rag_evidence
        monkeypatch.setattr(rag_evidence, 'CURRENT_FACT_RENDERER_VERSION', 'synthetic-changed-v2-renderer')
    checked = await check(pins, backend)
    assert checked.status == 'changed'
    assert checked.reason_code == {'source_hold': 'retrieval_source_no_longer_eligible',
        'group_mapping': 'retrieval_grouping_changed', 'renderer': 'retrieval_source_changed',
        'permission': 'retrieval_source_changed'}[change]


async def test_v2_activation_ABA_requires_new_event_even_with_same_content_and_build(db_session):
    backend, _, first = await active_content(db_session)
    pins, _ = await selected(db_session, backend)
    second = await prepared_build(db_session, content_id=backend.content_id, logical_index=backend.logical_index)
    second_event = await activation_service.activate_backend(db_session, **activation(second,
        await accepted(db_session, second), predecessor=backend.activation_event_id, old=False), dry_run=False)
    # Return to the identical retained first build through a NEW rollback event.
    args = activation(first, await accepted(db_session, first),
        predecessor=second_event['activation_event_id'], old=False) | {'action': 'rollback'}
    await activation_service.activate_backend(db_session, **args, dry_run=False)
    restored = await activation_service.load_active_backend(db_session, logical_index=backend.logical_index)
    assert restored.build_id == backend.build_id and restored.activation_event_id != backend.activation_event_id
    await db_session.commit()
    assert (await check(pins, backend)).reason_code == 'retrieval_generation_changed'
    # Replacing the pin alone cannot reauthorize inputs captured at the old event.
    assert (await check(pins, restored)).reason_code == 'retrieval_generation_changed'


async def test_forged_mixed_missing_or_caller_mapping_backend_is_not_current(db_session, tmp_path):
    backend, _, _ = await active_content(db_session, tmp_path)
    pins, _ = await selected(db_session, backend)
    await db_session.commit()
    for supplied in (backend.metadata(), {'build_id': backend.build_id}):
        assert (await check(pins, supplied)).status == 'unavailable'
    for field in ('build_id', 'content_id', 'activation_event_id'):
        assert (await check(pins, replace(backend, **{field: str(uuid4())}))).status == 'changed'
    mixed = [pins[0], replace(pins[1], generation_pin_sha256=None)]
    assert (await check(mixed, backend)).status == 'unavailable'
    assert (await check([replace(pin, generation_pin_sha256=None) for pin in pins], backend)).status == 'unavailable'


async def test_final_v2_details_are_only_resolved_after_all_sources_match(db_session):
    backend, _, _ = await active_content(db_session)
    pins, chunks = await selected(db_session, backend)
    await db_session.commit()
    calls = []
    async def details(db):
        calls.append(True)
        return {'synthetic': 'fresh final snapshot only'}
    checked = await check(pins, backend, snapshot_resolver=details)
    assert checked.status == 'unchanged' and checked.details == {'synthetic': 'fresh final snapshot only'}
    async with AsyncSession(get_engine()) as writer:
        await writer.execute(sa.update(Paper).where(Paper.id == chunks[0].paper_id).values(status='corrected'))
        await writer.commit()
    assert (await check(pins, backend, snapshot_resolver=details)).status == 'changed'
    assert calls == [True]
