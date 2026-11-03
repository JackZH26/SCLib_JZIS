"""Actual short CAS/role/rollback/pin proofs in fresh owned vector clusters."""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, get_engine
from models.retrieval_activation_v2 import GATES, TABLE_ORDER
from services import retrieval_activation as service
from services import retrieval_backend as backend
from services import retrieval_content as content_service
from services.index_generations import activate_generation, load_active_generation, record_validation
from tests.test_index_generations import db_session as db_session
from tests.test_index_generations import observation, staged
from tests.test_research_freeze import state

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST') != '1', reason='Requires fresh owned vector runner')]


async def prepared_build(db, *, content_id=None, logical_index=None,policy_version='v4'):
    old = None
    if content_id is None:
        logical = logical_index or 'synthetic-' + uuid4().hex
        generation, _ = await staged(db, logical_index=logical)
        validated = await record_validation(db, generation_id=generation['generation_id'],
            observation=await observation(db, generation), dry_run=False)
        old = await activate_generation(db, generation_id=generation['generation_id'], validation_id=validated['validation_id'],
            expected_event_id=None, idempotency_key='initial', dry_run=False)
        plan = await content_service.stage_legacy_content(db, generation_id=generation['generation_id'], dry_run=False)
        content_id = plan['content_id']
        refs = await content_service.source_reference_page(db, content_id=content_id)
        await content_service.append_content_partition(db, content_id=content_id, partition_id=0, references=refs, dry_run=False)
        await content_service.seal_content(db, content_id=content_id, dry_run=False)
    identifier = str(uuid4())
    await backend.stage_build(db, build_id=identifier, content_id=content_id,
        image_digest='sha256:' + 'a' * 64, implementation_revision='b' * 40, dry_run=False,policy_version=policy_version)
    await backend.create_projection(db, build_id=identifier, dry_run=False)
    await backend.copy_partition(db, build_id=identifier, partition_id=0, dry_run=False)
    await backend.build_small_projection_graph(db, build_id=identifier, dry_run=False)
    await backend.seal_projection(db, build_id=identifier, dry_run=False)
    validated = await backend.validate_projection(db, build_id=identifier, validation_id=str(uuid4()), dry_run=False)
    return {'build_id': identifier, 'content_id': content_id, 'validation_id': validated['validation_id'],
            'logical_index': logical_index or logical if old else logical_index, 'old': old}


async def accepted(db, prepared):
    identifier = str(uuid4())
    # Explicit synthetic references only. No real report/signature is claimed.
    await service.record_operator_acceptance(db, acceptance_id=identifier, build_id=prepared['build_id'],
        validation_id=prepared['validation_id'], evidence={gate: 'c' * 64 for gate in GATES}, dry_run=False)
    return identifier


def activation(prepared, acceptance_id, *, predecessor=None, old=True):
    return {'event_id': str(uuid4()), 'build_id': prepared['build_id'], 'validation_id': prepared['validation_id'],
        'acceptance_id': acceptance_id, 'expected_event_id': predecessor, 'idempotency_key': uuid4().hex,
        'expected_v1': {key: prepared['old'][key] for key in ('generation_id', 'activation_event_id', 'manifest_sha256')}
            if old else None}


async def test_preview_exact_initial_pin_replay_and_unchanged_v1_pointer(db_session):
    prepared = await prepared_build(db_session)
    assert await service.load_active_backend(db_session, logical_index=prepared['logical_index']) is None
    identifier = await accepted(db_session, prepared)
    args = activation(prepared, identifier)
    before = await state(db_session)
    await service.activate_backend(db_session, **args)
    assert await state(db_session) == before
    result = await service.activate_backend(db_session, **args, dry_run=False)
    pin = await service.load_active_backend(db_session, logical_index=prepared['logical_index'])
    assert pin.metadata()['version'] == 'sclib-retrieval-pin/2.0.0'
    assert pin.build_id == prepared['build_id'] and pin.activation_event_id == result['activation_event_id']
    assert pin.projection.table == 'retrieval_projection.b_' + UUID(prepared['build_id']).hex
    assert 'resource' not in pin.metadata() and 'generation_id' not in pin.metadata()
    await service.assert_current_backend(db_session, pin)
    after = await state(db_session)
    assert await service.activate_backend(db_session, **args, dry_run=False) == result
    assert await state(db_session) == after
    assert await load_active_generation(db_session, logical_index=prepared['logical_index']) == {
        key: value for key, value in prepared['old'].items() if key not in ('dry_run', 'committed')}


@pytest.mark.parametrize('wrong', ['generation', 'event', 'manifest', 'missing'])
async def test_initial_cas_requires_actual_exact_v1_predecessor(db_session, wrong):
    prepared = await prepared_build(db_session)
    args = activation(prepared, await accepted(db_session, prepared))
    if wrong == 'missing':
        args['expected_v1'] = None
    elif wrong == 'manifest':
        args['expected_v1']['manifest_sha256'] = 'd' * 64
    else:
        # Existing FK identities, but from a different logical index.
        other = await prepared_build(db_session)
        key = 'generation_id' if wrong == 'generation' else 'activation_event_id'
        args['expected_v1'][key] = other['old'][key]
    before = await state(db_session)
    with pytest.raises(DBAPIError, match='initial_exact_v1'):
        await service.activate_backend(db_session, **args, dry_run=False)
    assert await state(db_session) == before


async def test_complete_evidence_is_explicit_operator_attestation_not_automatic_validation(db_session):
    prepared = await prepared_build(db_session)
    args = dict(acceptance_id=str(uuid4()), build_id=prepared['build_id'], validation_id=prepared['validation_id'])
    with pytest.raises(service.RetrievalActivationError, match='Complete exact'):
        await service.record_operator_acceptance(db_session, **args, evidence={GATES[0]: 'c' * 64}, dry_run=False)
    before = await state(db_session)
    result = await service.record_operator_acceptance(db_session, **args, evidence={gate: 'c' * 64 for gate in GATES})
    assert not result['external_artifacts_verified_by_this_method'] and await state(db_session) == before
    with pytest.raises(DBAPIError, match='complete_operator_evidence'):
        async with db_session.begin_nested():
            await db_session.execute(Base.metadata.tables[TABLE_ORDER[0]].insert().values(
                id=uuid4(), build_id=UUID(prepared['build_id']), validation_id=UUID(prepared['validation_id']),
                evidence={GATES[0]: 'c' * 64}, attestation='operator-reviewed-artifact-references/1.0.0'))


@pytest.mark.parametrize('role', ['sclib_retrieval_reader', 'sclib_retrieval_builder'])
async def test_reader_or_builder_cannot_attest_even_with_accidental_insert_grant(db_session, role):
    prepared = await prepared_build(db_session)
    await db_session.execute(sa.text(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}'))
    await db_session.execute(sa.text(f'GRANT INSERT ON retrieval_acceptances_v2 TO {role}'))
    with pytest.raises(DBAPIError, match='separate_publisher_role'):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(f'SET LOCAL ROLE {role}'))
            await accepted(db_session, prepared)


async def test_native_forward_must_extend_current_content_and_rejects_stale_branch(db_session, tmp_path):
    from tests.test_retrieval_content import publication

    first = await prepared_build(db_session)
    event = await service.activate_backend(db_session, **activation(first, await accepted(db_session, first)), dry_run=False)
    async def new_content(base, publication_id):
        plan = await content_service.stage_native_content(db_session, base_content_id=base,
            publication_ids=[publication_id], dry_run=False)
        refs = await content_service.source_reference_page(db_session, content_id=plan['content_id'])
        await content_service.append_content_partition(db_session, content_id=plan['content_id'], partition_id=0,
            references=refs, dry_run=False)
        await content_service.seal_content(db_session, content_id=plan['content_id'], dry_run=False)
        return await prepared_build(db_session, content_id=plan['content_id'], logical_index=first['logical_index'])
    _, _, pub1 = await publication(db_session, tmp_path)
    second = await new_content(first['content_id'], pub1['publication_id'])
    event = await service.activate_backend(db_session, **activation(second, await accepted(db_session, second),
        predecessor=event['activation_event_id'], old=False), dry_run=False)
    _, _, pub2 = await publication(db_session, tmp_path)
    stale = await new_content(first['content_id'], pub2['publication_id'])
    with pytest.raises(DBAPIError, match='forward_content_must_extend_current'):
        await service.activate_backend(db_session, **activation(stale, await accepted(db_session, stale),
            predecessor=event['activation_event_id'], old=False), dry_run=False)
    third = await new_content(second['content_id'], pub2['publication_id'])
    await service.activate_backend(db_session, **activation(third, await accepted(db_session, third),
        predecessor=event['activation_event_id'], old=False), dry_run=False)
    pin = await service.load_active_backend(db_session, logical_index=first['logical_index'])
    assert pin.content_id == third['content_id']


async def test_rollback_uses_previously_active_local_build_fresh_validation_and_no_whole_db_restore(db_session):
    first = await prepared_build(db_session)
    acceptance1 = await accepted(db_session, first)
    event1 = await service.activate_backend(db_session, **activation(first, acceptance1), dry_run=False)
    pin1 = await service.load_active_backend(db_session, logical_index=first['logical_index'])
    second = await prepared_build(db_session, content_id=first['content_id'], logical_index=first['logical_index'])
    acceptance2 = await accepted(db_session, second)
    event2 = await service.activate_backend(db_session, **activation(second, acceptance2,
        predecessor=event1['activation_event_id'], old=False), dry_run=False)
    with pytest.raises(service.RetrievalActivationError, match='no longer current'):
        await service.assert_current_backend(db_session, pin1)
    invalid = await prepared_build(db_session, content_id=first['content_id'], logical_index=first['logical_index'])
    args = activation(invalid, await accepted(db_session, invalid), predecessor=event2['activation_event_id'], old=False)
    with pytest.raises(DBAPIError, match='previously_active_local_build'):
        await service.activate_backend(db_session, **args, action='rollback', dry_run=False)
    fresh = await backend.validate_projection(db_session, build_id=first['build_id'], validation_id=str(uuid4()), dry_run=False)
    args = activation({**first, 'validation_id': fresh['validation_id']}, acceptance1,
        predecessor=event2['activation_event_id'], old=False)
    await service.activate_backend(db_session, **args, action='rollback', dry_run=False)
    pin3 = await service.load_active_backend(db_session, logical_index=first['logical_index'])
    assert pin3.build_id == pin1.build_id and pin3.activation_event_id != pin1.activation_event_id
    assert await db_session.scalar(sa.text('SELECT count(*) FROM retrieval_activation_events_v2 WHERE logical_index=:logical'),
                                   {'logical': first['logical_index']}) == 3


async def test_stale_predecessor_cannot_overwrite_new_head(db_session):
    prepared = await prepared_build(db_session)
    acceptance = await accepted(db_session, prepared)
    first = await service.activate_backend(db_session, **activation(prepared, acceptance), dry_run=False)
    args = activation(prepared, acceptance, predecessor=first['activation_event_id'], old=False)
    await service.activate_backend(db_session, **args, dry_run=False)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match='cas_or_acceptance'):
        await service.activate_backend(db_session, **{**args, 'event_id': str(uuid4()), 'idempotency_key': 'stale'}, dry_run=False)
    assert await state(db_session) == before


async def test_v1_activation_is_fenced_after_v2_takes_authority(db_session):
    prepared = await prepared_build(db_session)
    await service.activate_backend(db_session, **activation(prepared, await accepted(db_session, prepared)), dry_run=False)
    validation = (await db_session.execute(sa.text('SELECT id FROM index_generation_validations WHERE generation_id=:id'),
                         {'id': UUID(prepared['old']['generation_id'])})).scalar_one()
    before = await state(db_session)
    with pytest.raises(DBAPIError, match='v2_authority_blocks_v1'):
        await activate_generation(db_session, generation_id=prepared['old']['generation_id'], validation_id=validation,
            expected_event_id=prepared['old']['activation_event_id'], idempotency_key='late-v1', dry_run=False)
    assert await state(db_session) == before


async def test_expired_readback_and_changed_physical_guards_cannot_activate(db_session):
    prepared = await prepared_build(db_session)
    accepted_id = await accepted(db_session, prepared)
    async with db_session.begin_nested() as savepoint:
        await db_session.execute(sa.text('ALTER TABLE retrieval_backend_validations_v2 DISABLE TRIGGER USER'))
        await db_session.execute(sa.text("UPDATE retrieval_backend_validations_v2 SET created_at=clock_timestamp()-interval '16 minutes' WHERE id=:id"),
                                 {'id': UUID(prepared['validation_id'])})
        await db_session.execute(sa.text('ALTER TABLE retrieval_backend_validations_v2 ENABLE TRIGGER USER'))
        with pytest.raises(DBAPIError, match='fresh_exact_build_validation'):
            await service.activate_backend(db_session, **activation(prepared, accepted_id), dry_run=False)
        await savepoint.rollback()
    table = 'retrieval_projection.b_' + UUID(prepared['build_id']).hex
    await db_session.execute(sa.text(f'ALTER TABLE {table} DISABLE TRIGGER retrieval_projection_write_v2'))
    with pytest.raises(DBAPIError, match='sealed_physical_build_unavailable'):
        await service.activate_backend(db_session, **activation(prepared, accepted_id), dry_run=False)


async def test_read_pin_works_with_select_only_role_and_rejects_broken_physical_objects(db_session):
    prepared = await prepared_build(db_session)
    await service.activate_backend(db_session, **activation(prepared, await accepted(db_session, prepared)), dry_run=False)
    await db_session.execute(sa.text('GRANT SELECT ON ALL TABLES IN SCHEMA public TO sclib_retrieval_reader'))
    await db_session.execute(sa.text('GRANT USAGE ON SCHEMA retrieval_projection TO sclib_retrieval_reader'))
    async with db_session.begin_nested():
        await db_session.execute(sa.text('SET LOCAL ROLE sclib_retrieval_reader'))
        pin = await service.load_active_backend(db_session, logical_index=prepared['logical_index'])
        assert pin.build_id == prepared['build_id']
        await db_session.execute(sa.text('RESET ROLE'))
    await db_session.execute(sa.text(f'DROP INDEX retrieval_projection.hnsw_b_{UUID(prepared["build_id"]).hex}'))
    with pytest.raises(service.RetrievalActivationError, match='physical projection unavailable'):
        await service.load_active_backend(db_session, logical_index=prepared['logical_index'])


@pytest.mark.parametrize('table', TABLE_ORDER)
async def test_authority_cannot_be_deleted_or_directly_repointed(db_session, table):
    prepared = await prepared_build(db_session)
    await service.activate_backend(db_session, **activation(prepared, await accepted(db_session, prepared)), dry_run=False)
    before = await state(db_session)
    with pytest.raises(DBAPIError, match='append-only|requires_activation_event'):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(f'DELETE FROM {table}'))
    assert await state(db_session) == before


async def test_stale_repeatable_read_v1_writer_cannot_miss_committed_v2_authority(db_session):
    prepared = await prepared_build(db_session)
    args = activation(prepared, await accepted(db_session, prepared))
    await db_session.commit()
    engine = get_engine()
    try:
        async with engine.connect() as writer:
            await writer.execution_options(isolation_level='REPEATABLE READ')
            await writer.begin()
            await writer.scalar(sa.text('SELECT epoch FROM index_generation_epoch WHERE id=1'))
            await service.activate_backend(db_session, **args, dry_run=False)
            await db_session.commit()
            with pytest.raises(DBAPIError) as error:
                await writer.execute(sa.text("INSERT INTO index_activation_events(id,logical_index,generation_id,validation_id,"
                    "predecessor_id,event_number,action,idempotency_key) SELECT :id,e.logical_index,e.generation_id,e.validation_id,"
                    "e.id,e.event_number+1,'promote','stale-writer' FROM index_activation_events e WHERE e.id=:prior"),
                    {'id': uuid4(), 'prior': UUID(prepared['old']['activation_event_id'])})
            assert getattr(error.value.orig, 'sqlstate', None) == '40001'
            await writer.rollback()
    finally:
        await engine.dispose()
        # Cluster destruction owns this synthetic committed history. No ledger
        # is emptied to make a historical comparison pass.
        await db_session.execute(sa.text(f'DROP TABLE retrieval_projection.b_{UUID(prepared["build_id"]).hex}'))
        await db_session.commit()
