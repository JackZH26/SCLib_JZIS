"""Transfer a pinned admitted snapshot with the existing canonical importers.

No model calls, schema migrations, permission changes, or corpus-ledger writes.
The caller supplies the exact destination identity and a retained release plan.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ingestion.materials_ner import reviewed_reader as rr
from materials_ner_amendment_bridge import apply as store_amendment
from materials_ner_canonical_bridge import _put, _apply_plan, require
from materials_ner_production90 import canonical_plan, read_pin
from materials_ner_tc_admit import anchor, identities
from materials_ner_tc_intake import AdmissionValidation, checked_projection, prepare, apply
from materials_ner_tc_release_plan import exclusion_evidence
from materials_ner_tc_sampling import retained
from models.db import Base
from services.source_registry import _json


def typed(table, row):
    result = dict(row)
    for key, value in result.items():
        if value is None:
            continue
        try:
            kind = Base.metadata.tables[table].c[key].type.python_type
        except NotImplementedError:
            continue
        if isinstance(value, str) and kind in (datetime, date):
            result[key] = kind.fromisoformat(value)
    return result


def scientific_metadata(value):
    """Destination catalogue bindings may change; scientific provenance may not."""
    value = deepcopy(value)
    for name in ('native_origin', 'editorial_origin'):
        value.get(name, {}).pop('identity_binding_sha256', None)
    return value


def verify_planned_claims(plan, expected):
    rows = plan['rows']['material_claims']
    require({r['id'] for r in rows} == set(expected), 'transfer_claim_scope_changed')
    for row in rows:
        original = expected[row['id']]
        for key, value in row.items():
            if key == 'validity_status':
                require(value == 'pending', 'unexpected_initial_claim_state')
            elif key == 'extraction_metadata':
                require(scientific_metadata(value) == scientific_metadata(original[key]),
                    'transfer_scientific_provenance_changed:' + row['id'])
            else:
                require(_json(value) == original[key], 'transfer_claim_value_changed:' + key + ':' + row['id'])


async def verify_existing(db, expected):
    rows = (await db.execute(text('SELECT to_jsonb(c) FROM material_claims c WHERE id::text=ANY(:ids)'),
        dict(ids=list(expected)))).scalars().all()
    for row in rows:
        original = expected[row['id']]
        for key in ('paper_id', 'material_id', 'work_id', 'result_key', 'source_locator', 'raw_record',
                    'value_kelvin', 'value_lower_kelvin', 'value_upper_kelvin', 'value_relation',
                    'tc_definition', 'measurement_method', 'pressure_gpa', 'pressure_state', 'validity_status'):
            require(row[key] == original[key], 'existing_transfer_record_changed:' + key)
        require(scientific_metadata(row['extraction_metadata']) == scientific_metadata(original['extraction_metadata']),
            'existing_transfer_provenance_changed')
    return {r['id'] for r in rows}


async def preserve_exclusions(db, expected, corrections):
    for row in expected.values():
        if row['validity_status'] == 'pending':
            continue
        require(row['id'] in corrections and row['validity_status'] == 'excluded',
            'transfer_correction_authority_missing')
        changed = (await db.execute(text("UPDATE material_claims SET validity_status='excluded' "
            "WHERE id=CAST(:id AS uuid) AND validity_status='pending' RETURNING id"), dict(id=row['id']))).scalar_one_or_none()
        require(changed is not None, 'transfer_correction_not_applied')


async def transfer(manifest_pin, fixture_pin, verification_pin, database_url, output, *,
                   expected_database, expected_user, campaign, progress=None):
    manifest = read_pin(manifest_pin)
    fixture = read_pin(fixture_pin)
    verified = read_pin(verification_pin)
    require(verified['manifest'] == manifest_pin, 'release_verification_manifest_mismatch')
    require(verified['all_admission_groups_checked'] == len(manifest['admission_groups']),
        'release_admission_validation_missing')
    corrections = {r['claim_id']: r for r in exclusion_evidence(campaign, manifest['records'])}
    require(list(corrections.values()) == manifest['correction_updates'], 'release_correction_evidence_changed')
    original = {r['id']: r for r in fixture['material_claims']}
    require(set(original) == {r['id'] for r in manifest['records']}, 'transfer_fixture_scope_changed')
    for row in manifest['records']:
        source = original[row['id']]
        require(source['source_locator'] == row['source_locator'] and source['validity_status'] == row['validity_status']
            and source['extraction_metadata']['production_admission'] == row['admission'], 'transfer_fixture_admission_changed')
    snapshots = {r['id']: r for r in fixture['source_snapshots']}
    times = {}
    for row in fixture['capture_times']:
        times.setdefault(row['claim_id'], set()).add(datetime.fromisoformat(row['captured_at']).isoformat())
    legacy_requests = {r['paper_id']: r['request'] for r in verified['legacy_amendment_requests']}
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(database_url, connect_args={'server_settings': {'timezone': 'UTC'}})
    reports = []
    try:
        async with engine.connect() as db:
            identity = (await db.execute(text('SELECT current_database(),current_user'))).one()
            require(tuple(identity) == (expected_database, expected_user), 'transfer_destination_identity_mismatch')
            require((await db.execute(text('SELECT version_num FROM alembic_version'))).scalar_one() ==
                '0104_materials_device_context', 'transfer_destination_schema_mismatch')
        for number, group in enumerate(manifest['admission_groups']):
            selection, audit = read_pin(group['selection']), read_pin(group['audit'])
            route = group['admission_route']
            members = {key: original[key] for key in group['claim_ids']}
            work_reports = []
            if group['contract'] == 'native_tc':
                validation = AdmissionValidation.build(selection, audit, route)
                for entry in selection['source_entries']:
                    packet, projection = checked_projection(entry)
                    wanted = {key: row for key, row in members.items() if row['paper_id'] == packet['work_id']
                        and row['source_locator']['run_id'] == packet['run_id']
                        and row['source_locator']['projection_sha256'] == projection['projection_sha256']}
                    if not wanted:
                        continue
                    wanted_results = {row['source_locator']['source_result_id'] for row in wanted.values()}
                    omitted = {r['result_id'] for r in retained(projection, selection, audit, admission_route=route)} - wanted_results
                    snapshot_ids = {r['source_snapshot_id'] for r in wanted.values()}
                    require(len(snapshot_ids) == 1, 'transfer_work_snapshot_ambiguous')
                    snapshot_row = typed('source_snapshots', snapshots[next(iter(snapshot_ids))])
                    capture_times = set().union(*(times[key] for key in wanted))
                    require(len(capture_times) == 1, 'transfer_capture_time_ambiguous')
                    async with AsyncSession(engine, expire_on_commit=False) as db:
                        await db.execute(text('SELECT pg_advisory_xact_lock(1002401)'))
                        already = await verify_existing(db, wanted)
                        require(not already or already == set(wanted), 'partial_work_transfer_requires_reconciliation')
                        if already:
                            work_reports.append(dict(paper_id=packet['work_id'], inserted_claims=0, existing_claims=len(already)))
                            continue
                        bindings = await identities(db, packet, projection, selection, audit, snapshot_row,
                            omitted, admission_route=route)
                        arguments = dict(bindings=bindings, captured_at=next(iter(capture_times)), selection=selection,
                            audit=audit, excluded_result_ids=omitted, admission_route=route, validation=validation)
                        plan = prepare(entry, **arguments)
                        verify_planned_claims(plan, wanted)
                        result = await apply(db, entry, dry_run=False, **arguments)
                        require(len(result['results']) == len(wanted), 'transfer_insert_scope_mismatch')
                        await preserve_exclusions(db, wanted, corrections)
                        require(await verify_existing(db, wanted) == set(wanted), 'transfer_work_readback_incomplete')
                        await db.commit()
                    work_reports.append(dict(paper_id=packet['work_id'], inserted_claims=len(wanted), existing_claims=0))
            elif group['contract'] == 'editorial_amendment':
                for paper in sorted({r['paper_id'] for r in members.values()}):
                    wanted = {key: row for key, row in members.items() if row['paper_id'] == paper}
                    request = read_pin(legacy_requests[paper])
                    async with AsyncSession(engine, expire_on_commit=False) as db:
                        await db.execute(text('SELECT pg_advisory_xact_lock(1002401)'))
                        already = await verify_existing(db, wanted)
                        require(not already or already == set(wanted), 'partial_work_transfer_requires_reconciliation')
                        if already:
                            work_reports.append(dict(paper_id=paper, inserted_claims=0, existing_claims=len(already)))
                            continue
                        for table, key in [('works', 'work'), ('source_snapshots', 'snapshot')]:
                            row = next(r for r in fixture[table] if r['id'] == request['bindings'][key]['id'])
                            await _put(db, table, typed(table, row))
                        mapping = Base.metadata.tables['paper_work_map']
                        await db.execute(insert(mapping).values(paper_id=paper,
                            work_id=UUID(request['bindings']['work']['id']), relation_type='preprint',
                            match_method='exact_arxiv', match_score=1, review_status='accepted').on_conflict_do_nothing())
                        for table, key in [('papers', 'paper'), ('works', 'work'), ('source_snapshots', 'snapshot')]:
                            request['bindings'][key] = await anchor(db, table, request['bindings'][key]['id'])
                        for sample_id, bound in request['bindings']['samples'].items():
                            target = (await db.execute(select(Base.metadata.tables['materials']).where(
                                Base.metadata.tables['materials'].c.id == bound['id']))).mappings().one()
                            source = next(r for r in fixture['materials'] if r['id'] == bound['id'])
                            require(target['formula'] == source['formula'], 'legacy_target_formula_changed')
                            request['bindings']['samples'][sample_id] = await anchor(db, 'materials', bound['id'])
                        parent, amendment = read_pin(request['parent']), read_pin(request['amendment'])
                        await store_amendment(db, parent, amendment)
                        plan = canonical_plan(request, selection=selection, audit=audit)
                        verify_planned_claims(plan, wanted)
                        await _apply_plan(db, plan, amendment, dry_run=False)
                        require(await verify_existing(db, wanted) == set(wanted), 'transfer_legacy_readback_incomplete')
                        await db.commit()
                    work_reports.append(dict(paper_id=paper, inserted_claims=len(wanted), existing_claims=0))
            else:
                raise ValueError('unsupported_release_contract')
            report = dict(group=number, selection=group['selection'], audit=group['audit'],
                admission_route=route, work_reports=work_reports)
            rr.put(output / f'GROUP_{number:03}.json', report)
            reports.append(report)
            if progress:
                progress(number + 1, len(manifest['admission_groups']))
        async with engine.connect() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            ids = set((await db.execute(text("SELECT id::text FROM material_claims WHERE "
                "extraction_metadata->'production_admission'->>'policy'='production90/1'"))).scalars())
            require(ids == set(original), 'final_transfer_scope_mismatch')
            require(await verify_existing(db, original) == set(original), 'final_transfer_readback_incomplete')
        result = dict(schema='materials-production90-scoped-transfer/1', manifest=manifest_pin,
            inserted_claims=sum(r['inserted_claims'] for g in reports for r in g['work_reports']),
            existing_claims=sum(r['existing_claims'] for g in reports for r in g['work_reports']),
            historical_claims=len(original), excluded_claims=len(corrections), provider_calls=0,
            destination_database=expected_database, destination_user=expected_user,
            catalogue_binding_metadata='Destination row hashes rebound; original source snapshot retained in input artifacts.')
        rr.put(output / 'RESULT.json', result)
        return result
    finally:
        await engine.dispose()
