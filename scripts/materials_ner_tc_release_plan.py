"""Resolve a canonical Production-90 snapshot to its original admission evidence.

This is a read-only release preparation command. It neither re-evaluates the
science nor writes to a destination database. Later transfer must preserve the
exact result scope and the post-admission exclusions recorded in this manifest.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from pathlib import Path
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ingestion.materials_ner import reviewed_reader as rr
from materials_ner_production90 import digest, qualify, read_pin
from materials_ner_tc_intake import admission_quality
from materials_ner_tc_sampling import BATCH_ROUTE, RECORD_ROUTE, retained
from services.materials_admission_scope import ADMISSION_POLICY_WHERE, EXCLUSION_REASON_SQL


async def snapshot(database_url):
    engine = create_async_engine(database_url, isolation_level='REPEATABLE READ')
    try:
        async with engine.connect() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            at = (await db.execute(text('SELECT CURRENT_TIMESTAMP'))).scalar_one().isoformat()
            rows = (await db.execute(text('''SELECT c.id::text,c.paper_id,c.result_key,
                c.source_locator,c.validity_status,c.created_at,
                c.extraction_metadata->'production_admission' AS admission,
                p.status AS paper_status,w.publication_status,
                ''' + EXCLUSION_REASON_SQL + ''' AS exclusion_reason
                FROM material_claims c JOIN papers p ON p.id=c.paper_id
                JOIN works w ON w.id=c.work_id WHERE ''' + ADMISSION_POLICY_WHERE +
                ' ORDER BY c.created_at,c.id'))).mappings().all()
            count = (await db.execute(text('SELECT count(*) FROM material_claims c WHERE ' +
                ADMISSION_POLICY_WHERE))).scalar_one()
            if count != len(rows):
                raise ValueError('release_snapshot_lifecycle_join_loss')
            result = [dict(r, created_at=r['created_at'].isoformat()) for r in rows]
            return dict(snapshot_at=at, records=result)
    finally:
        await engine.dispose()


def source_index(campaign):
    """Match immutable content identities, including early versioned filenames."""
    selections, audits = {}, {}
    for pattern, target, key in (
        ('*SAMPLE*.json', selections, lambda d: d.get('selection_sha256')),
        ('SOURCE_AUDIT*.json', audits, digest),
    ):
        for path in sorted(Path(campaign).rglob(pattern)):
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict) or not value.get('selection_sha256'):
                continue
            identity = key(value)
            target.setdefault(identity, rr.reference(path))
    return selections, audits


def native_key(row):
    locator = row['source_locator']
    return (row['paper_id'], locator['source_result_id'], locator['run_id'], locator['projection_sha256'])


def check_membership(rows, selection, audit, route):
    native = selection.get('schema') == 'materials-native-tc-sample/1'
    if native:
        report = admission_quality(selection, audit, route)
        allowed = set()
        for entry in selection['source_entries']:
            projection = read_pin(entry['projection'])
            for r in retained(projection, selection, audit, admission_route=route):
                allowed.add((r['work_id'], r['result_id'], r['run_id'], projection['projection_sha256']))
        actual = [native_key(r) for r in rows]
    else:
        if route != BATCH_ROUTE:
            raise ValueError('unsupported_editorial_admission_route')
        report = qualify(selection, audit)
        if not report['qualified']:
            raise ValueError('editorial_batch_not_qualified')
        allowed = {(r['work_id'], r['result_id'], r['amendment_id'])
                   for r in audit['records'] if r['verdict'] == 'correct'}
        actual = [(r['paper_id'], r['result_key'], r['source_locator']['amendment_id']) for r in rows]
    if len(set(actual)) != len(actual):
        raise ValueError('duplicate_release_source_result')
    if not set(actual) <= allowed:
        raise ValueError('canonical_record_outside_original_admission')
    return dict(contract='native_tc' if native else 'editorial_amendment',
        original_quality_report=report, other_admittable_records=len(allowed - set(actual)))


def exclusion_evidence(campaign, records):
    """Keep known local corrections from silently reverting during re-import."""
    commits = {}
    for path in sorted((Path(campaign) / 'record-reviews').glob('*/COMMITTED.json')):
        value = json.loads(path.read_bytes())
        ids = value.get('claim_ids', [value['claim_id']] if value.get('claim_id') else [])
        for claim_id in ids:
            if claim_id in commits:
                raise ValueError('multiple_correction_commits_require_explicit_revision_order')
            commits[claim_id] = (path, value)
    updates = []
    for row in records:
        if row['exclusion_reason'] != 'claim_not_currently_usable':
            continue
        found = commits.get(row['id'])
        if found is None:
            raise ValueError('excluded_claim_without_correction_receipt:' + row['id'])
        path, commit = found
        if commit.get('validity_status') != row['validity_status']:
            raise ValueError('correction_receipt_state_mismatch')
        before, after = read_pin(commit['before']), read_pin(commit['after'])
        def claim_rows(value):
            rows = value if isinstance(value, list) else value.get('claims', [value])
            return [r.get('claim', r) for r in rows]
        before_rows, after_rows = claim_rows(before), claim_rows(after)
        previous = next((r for r in before_rows if str(r.get('id')) == row['id']), None)
        current = next((r for r in after_rows if str(r.get('id')) == row['id']), None)
        if previous is None or current is None or current.get('validity_status') != row['validity_status']:
            raise ValueError('correction_receipt_claim_binding_mismatch')
        protected = ('paper_id', 'raw_record', 'extraction_metadata', 'source_locator')
        if any(k not in previous or k not in current for k in protected):
            raise ValueError('correction_receipt_scientific_fields_missing')
        if any(previous.get(k) != current.get(k) for k in protected):
            raise ValueError('correction_rewrites_scientific_record')
        if current.get('paper_id') != row['paper_id'] or current.get('source_locator') != row['source_locator']:
            raise ValueError('correction_receipt_source_binding_mismatch')
        if current['extraction_metadata'].get('production_admission') != row['admission']:
            raise ValueError('correction_receipt_admission_binding_mismatch')
        updates.append(dict(claim_id=row['id'], paper_id=row['paper_id'],
            target_validity_status=row['validity_status'], source_locator=row['source_locator'],
            original_admission=row['admission'], commit=rr.reference(path),
            before=commit['before'], after=commit['after']))
    return updates


def assemble(campaign, captured, *, progress=None):
    records = captured['records']
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('duplicate_canonical_claim')
    selections, audits = source_index(campaign)
    groups = defaultdict(list)
    for row in records:
        a = row['admission']
        groups[(a['selection_sha256'], a['audit_sha256'], a.get('admission_route', BATCH_ROUTE))].append(row)
    releases = []
    for index, ((selection_id, audit_id, route), members) in enumerate(groups.items()):
        if selection_id not in selections or audit_id not in audits:
            raise ValueError('release_admission_evidence_missing')
        selection_pin, audit_pin = selections[selection_id], audits[audit_id]
        selection, audit = read_pin(selection_pin), read_pin(audit_pin)
        checked = check_membership(members, selection, audit, route)
        if checked['original_quality_report']['audit_sha256'] != audit_id:
            raise ValueError('release_audit_identity_changed')
        releases.append(dict(selection=selection_pin, audit=audit_pin, admission_route=route,
            claim_ids=[r['id'] for r in members], **checked))
        if progress:
            progress(index + 1, len(groups))
    updates = exclusion_evidence(campaign, records)
    current = [r['id'] for r in records if r['exclusion_reason'] is None]
    return dict(schema='materials-production90-release-inputs/1', snapshot_at=captured['snapshot_at'],
        records=records, admission_groups=releases, correction_updates=updates,
        counts=dict(historical=len(records), current=len(current), groups=len(releases),
            exclusion_updates=len(updates), exclusions=dict(Counter(r['exclusion_reason'] for r in records
                if r['exclusion_reason'] is not None)),
            contracts=dict(Counter(g['contract'] for g in releases))),
        current_claim_ids=current, current_claim_ids_sha256=digest(sorted(current)),
        provider_calls=0, database_writes=False, destination_import_executed=False,
        whole_corpus_complete=False,
        transfer_requirements=[
            'Use original admission evidence and this exact claim scope; do not import additional eligible records.',
            'Replay the correction updates before exposing the destination dataset.',
            'Preserve destination paper metadata and any stricter current lifecycle exclusions.',
            'Recheck source hashes, destination identities, API/export equality and idempotence at transfer time.',
            'Refresh this snapshot after the processable frozen arXiv first pass before formal release.',
        ])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / 'RELEASE_INPUTS.json').exists():
        raise ValueError('release_snapshot_already_prepared')
    captured = asyncio.run(snapshot(args.database_url))
    def progress(done, total):
        if done == total or done % 20 == 0:
            print(json.dumps(dict(admission_groups_checked=done, total=total)), flush=True)
    result = assemble(args.campaign, captured, progress=progress)
    rr.put(args.output / 'RELEASE_INPUTS.json', result)
    print(json.dumps(dict(counts=result['counts'], manifest=rr.reference(args.output / 'RELEASE_INPUTS.json'),
        provider_calls=0, database_writes=False, destination_import_executed=False)), flush=True)


if __name__ == '__main__':
    main()
