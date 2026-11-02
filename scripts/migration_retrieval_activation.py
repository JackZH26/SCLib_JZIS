"""Owned activation boundary and local rollback proof, never real acceptance."""
from __future__ import annotations

from uuid import uuid4

from migration_retrieval_native import _sha, _snapshot
from test_safety import validate_test_environment, verify_postgres_identity

REVISION = '0110_retrieval_activation_v2'


def empty_roundtrip(capability, engine, config):
    from alembic import command
    from migration_revision_scope import assert_revision, at_revision
    from migration_source_expressions import public_objects
    from models.retrieval_activation_v2 import FUNCTION_SIGNATURES, TABLE_ORDER
    from sqlalchemy import inspect, text

    validate_test_environment()
    with at_revision(capability, engine, config, REVISION):
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert_revision(connection, REVISION)
            before = _snapshot(connection)
            assert all(not before[0][name] for name in TABLE_ORDER)
            signatures = {connection.execute(text('SELECT to_regprocedure(:signature)::text'),
                {'signature': f'public.{name}({arguments})'}).scalar_one() for name, arguments in FUNCTION_SIGNATURES}
            assert None not in signatures
            legacy = {name: rows for name, rows in before[0].items() if name not in TABLE_ORDER}
            old_objects = ({key: value for key, value in before[1][0].items() if key not in signatures},
                tuple(row for row in before[1][1] if row[0] not in TABLE_ORDER
                    and (row[0], row[1]) != ('index_activation_events', 'aa_retrieval_v2_blocks_v1')))
        command.downgrade(config, '0109_retrieval_backend_v2')
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert not set(TABLE_ORDER) & set(inspect(connection).get_table_names(schema='public'))
            assert _snapshot(connection)[0] == legacy and public_objects(connection) == old_objects
        command.upgrade(config, REVISION)
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert _snapshot(connection) == before
    return {'empty_roundtrip_preserved_every_prior_row_function_trigger': True, 'revision': REVISION,
            'only_new_named_v1_fence_added_and_removed': True}


async def populated_activation(capability):
    from sqlalchemy import text

    from models.db import get_engine, get_session_factory
    from services import retrieval_activation as activation
    from services import retrieval_backend as backend
    from tests.test_retrieval_activation import accepted, activation as event_args, prepared_build

    validate_test_environment()
    engine = get_engine()
    try:
        async with get_session_factory()() as db:
            connection = await db.connection()
            await connection.run_sync(verify_postgres_identity, capability)
            if not await db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector' AND extversion='0.8.7')")):
                return {'actual_pgvector_runtime': False, 'activation_checks': 'not_run_without_owned_pgvector_runtime'}
            first = await prepared_build(db)
            async def original_rows():
                return {name: (await db.execute(text(f'SELECT to_jsonb(t)::text FROM public.{name} t ORDER BY to_jsonb(t)::text'))).scalars().all()
                    for name in ('papers', 'users', 'index_generations', 'index_generation_members', 'index_activation_events', 'index_active_pointer')}
            before = await original_rows()
            a1 = await accepted(db, first)
            e1 = await activation.activate_backend(db, **event_args(first, a1), dry_run=False)
            p1 = await activation.load_active_backend(db, logical_index=first['logical_index'])
            assert await original_rows() == before
            second = await prepared_build(db, content_id=first['content_id'], logical_index=first['logical_index'])
            # The second local graph is a distinct physical candidate, not a
            # relabelled provider generation or whole-database replacement.
            # Compare unchanged user/source/v1 history after both were staged.
            assert await original_rows() == before
            e2 = await activation.activate_backend(db, **event_args(second, await accepted(db, second),
                predecessor=e1['activation_event_id'], old=False), dry_run=False)
            fresh = await backend.validate_projection(db, build_id=first['build_id'], validation_id=str(uuid4()), dry_run=False)
            e3 = await activation.activate_backend(db, **event_args({**first, 'validation_id': fresh['validation_id']}, a1,
                predecessor=e2['activation_event_id'], old=False), action='rollback', dry_run=False)
            p3 = await activation.load_active_backend(db, logical_index=first['logical_index'])
            assert p3.build_id == p1.build_id and p3.activation_event_id == e3['activation_event_id']
            assert await original_rows() == before
            await db.commit()
            return {'actual_pgvector_runtime': True, 'synthetic': True,
                'initial_exact_v1_transition_and_distinct_local_rollback': True,
                'source_user_and_v1_history_unchanged': True, 'events_appended': 3,
                'build_ids': [first['build_id'], second['build_id']], 'logical_index': first['logical_index'],
                'restored_pin': p3.metadata(), 'operator_evidence_references': 'synthetic_only_not_real_reports',
                'external_artifacts_verified': False, 'provider_calls_performed': False}
    finally:
        await engine.dispose()


def retained_history(capability, engine, config, capture):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import text

    validate_test_environment()
    if not capture['actual_pgvector_runtime']:
        return {'nonempty_downgrade_check': 'not_run_without_owned_pgvector_runtime'}
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = _snapshot(connection)
        physical = {identifier: connection.execute(text('SELECT to_regclass(:name)::oid'),
            {'name': 'retrieval_projection.b_' + identifier.replace('-', '')}).scalar_one() for identifier in capture['build_ids']}
    try:
        command.downgrade(config, '0109_retrieval_backend_v2')
    except RuntimeError as error:
        assert 'retained retrieval acceptance/activation authority' in str(error)
    else:
        raise AssertionError('Retained activation authority must refuse downgrade')
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)['status'] == 'compatible'
        after = _snapshot(connection)
        assert before == after
        for identifier, oid in physical.items():
            assert connection.execute(text('SELECT to_regclass(:name)::oid'),
                {'name': 'retrieval_projection.b_' + identifier.replace('-', '')}).scalar_one() == oid
    return {'nonempty_downgrade_refused': True, 'all_rows_functions_triggers_and_physical_OIDs_preserved': True,
        'before_sha256': _sha(before), 'after_sha256': _sha(after)}
