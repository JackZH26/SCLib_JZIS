"""Read-only full-corpus readiness snapshot; never enqueue, call a model or write SQL.

The frozen paper plan is the denominator. Local source representations and
historical jobs are evidence, not completion of a new re-extraction campaign.
Multiple original bundles are retained without selecting one by file mtime.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ingestion'))
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.planning import load_plan
from ingestion.materials_ner.sources import load_bundle

VERSION = 'materials-corpus-readiness/1'


def file_hash(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular_source_file_required')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_action(paper, bundles, advisory, receipt):
    if paper['source'] == 'aps':
        return 'aps_authorization_pending'
    if paper['source'] != 'arxiv':
        return 'unsupported_source'
    if advisory and advisory.get('exclude_from_new_ner'):
        return 'source_advisory_hold'
    usable = [b for b in bundles if b['original_bytes_verified'] and b['processing_allowed']
              and b['has_original_main_document'] and not b['pdf_wrapper_only']]
    if len(usable) > 1:
        return 'source_selection_required'
    if usable:
        # This is a preparation queue, not an extraction- or scientific-admission decision.
        return 'source_scope_and_version_preflight_required'
    if bundles:
        return 'source_representation_or_bytes_repair_required'
    if paper['acquisition_status'] == 'available_in_gcs':
        return 'gcs_acquisition_required'
    if receipt:
        return 'source_recovery_followup_required'
    return 'original_source_missing'


def capture(root, plan_path, *, plan_sha256, output):
    root, plan_path, output = root.resolve(), plan_path.resolve(), output.resolve()
    plan, identifier = load_plan(plan_path)
    if identifier != plan_sha256:
        raise ValueError('source_plan_pin_mismatch')
    papers = plan['papers']
    ids = {p['id'] for p in papers}
    if len(ids) != len(papers) or len(papers) != plan['summary']['papers']:
        raise ValueError('paper_denominator_mismatch')
    output.mkdir(parents=True, exist_ok=False)
    input_files, errors, original_bytes = [], [], {}

    def record(path):
        checksum = file_hash(path)
        input_files.append({'path': str(path), 'sha256': checksum, 'bytes': path.stat().st_size})
        return checksum

    record(plan_path)
    by_work = defaultdict(list)
    excluded_windows = 0
    for path in sorted((root / 'bundles').glob('*.json')):
        checksum = record(path)
        try:
            bundle = load_bundle(path)
            if digest(bundle.model_dump()) != path.stem:
                raise ValueError('bundle_identity_mismatch')
            if any(note.startswith('SOURCE_WINDOW ') for note in bundle.acquisition_notes):
                excluded_windows += 1
                continue
            if bundle.work_id not in ids:
                raise ValueError('bundle_work_outside_frozen_plan')
            for doc in bundle.documents:
                if doc.source_sha256 not in original_bytes:
                    source = root / 'sources' / doc.source_sha256
                    observed = file_hash(source) if source.is_file() and not source.is_symlink() else None
                    original_bytes[doc.source_sha256] = {
                        'path': str(source), 'expected_sha256': doc.source_sha256,
                        'observed_sha256': observed, 'verified': observed == doc.source_sha256,
                        'bytes': source.stat().st_size if observed else 0}
            text = '\n'.join(block.text for block in bundle.blocks)
            item = {'work_id': bundle.work_id, 'bundle_sha256': path.stem, 'file_sha256': checksum,
                    'original_bytes_verified': all(original_bytes[d.source_sha256]['verified'] for d in bundle.documents),
                    'processing_allowed': all(d.processing_permission == 'allowed' for d in bundle.documents),
                    'has_original_main_document': any(d.role == 'main' and d.source_kind in
                        {'original_text', 'original_tex', 'original_pdf'} for d in bundle.documents),
                    'pdf_wrapper_only': '\\includepdf' in text and len(text) < 2500,
                    'source_status': bundle.source_status, 'supplement_status': bundle.supplement_status,
                    'documents': [d.model_dump() for d in bundle.documents],
                    'blocks': len(bundle.blocks), 'text_characters': len(text)}
            by_work[bundle.work_id].append(item)
        except (ValueError, OSError) as error:
            errors.append({'path': str(path), 'sha256': checksum, 'error_class': type(error).__name__})

    advisories = {}
    for path in sorted((root / 'source-advisories').glob('*.json')):
        record(path)
        value = json.loads(path.read_bytes())
        if value.get('schema') != 'materials-source-advisory/1' or value['work_id'] in advisories:
            raise ValueError('ambiguous_source_advisory')
        advisories[value['work_id']] = value
    receipts = defaultdict(list)
    for lane in ('acquisitions', 'recovery'):
        # Direct receipts only: append-only attempt history must not double the denominator.
        for path in sorted((root / lane / identifier).glob('*.json')):
            checksum = record(path)
            value = json.loads(path.read_bytes())
            if value['plan_sha256'] != identifier or value['work_id'] not in ids:
                raise ValueError('acquisition_plan_binding_mismatch')
            receipts[value['work_id']].append({'path': str(path), 'sha256': checksum,
                                              'state': value['state'], 'lane': lane})

    legacy = defaultdict(Counter)
    jobs = []
    queue = root / 'queue.sqlite3'
    if queue.exists():
        with sqlite3.connect(queue.as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            jobs = db.execute('SELECT id,work_id,bundle_hash,state,attempts,config_json,result_hash '
                              'FROM jobs ORDER BY id').fetchall()
        for _, work, _, state, *_ in jobs:
            legacy[work][state] += 1

    rows, counts = [], Counter()
    for paper in sorted(papers, key=lambda p: p['id']):
        work = paper['id']
        bundles = by_work[work]
        action = source_action(paper, bundles, advisories.get(work), receipts[work])
        counts[action] += 1
        row = {'work_id': work, 'source': paper['source'],
               'frozen_archive_status': paper['acquisition_status'], 'next_source_action': action,
               'new_campaign_state': 'not_enqueued', 'scientific_acceptance': False,
               'ml_training_eligible': False}
        if bundles:
            row['candidate_bundle_sha256s'] = sorted(b['bundle_sha256'] for b in bundles)
        if receipts[work]:
            row['acquisition_receipts'] = receipts[work]
        if legacy[work]:
            row['legacy_job_states'] = dict(sorted(legacy[work].items()))
        if work in advisories:
            row['source_advisory'] = advisories[work]
        if paper.get('alternate_work_ids'):
            row['alternate_work_ids_for_version_reconciliation_only'] = paper['alternate_work_ids']
        rows.append(row)
    assert sum(counts.values()) == len(papers)
    bundle_rows = [b for work in sorted(by_work) for b in by_work[work]]
    for name, values in [('papers.jsonl', rows), ('bundles.jsonl', bundle_rows)]:
        with (output / name).open('x') as stream:
            for value in values:
                stream.write(canonical(value) + '\n')
    summary = {'schema': VERSION, 'captured_at': datetime.now(timezone.utc).isoformat(),
               'source_plan_sha256': identifier, 'frozen_inventory_captured_at': plan.get('inventory_captured_at'),
               'papers': len(papers), 'sources': dict(Counter(p['source'] for p in papers)),
               'frozen_archive_states': dict(Counter(p['acquisition_status'] for p in papers)),
               'next_source_actions': dict(sorted(counts.items())), 'original_bundle_works': len([w for w in by_work if by_work[w]]),
               'original_bundles': len(bundle_rows), 'excluded_window_bundles': excluded_windows,
               'original_source_objects_checked': len(original_bytes),
               'verified_original_bytes': sum(x['bytes'] for x in original_bytes.values() if x['verified']),
               'unverified_original_objects': sum(not x['verified'] for x in original_bytes.values()),
               'bundle_errors': len(errors), 'legacy_jobs': len(jobs),
               'legacy_job_states': dict(Counter(j[3] for j in jobs)), 'legacy_queue_snapshot_sha256': digest(jobs),
               'new_campaign_enqueued': 0, 'new_campaign_completed': 0, 'scientifically_accepted': 0,
               'ml_qualified': 0, 'deployment': 'deferred_until_full_corpus_and_database_acceptance',
               'independent_review': 'deferred_by_user_not_waived', 'model_calls': 0, 'production_writes': False,
               'limitations': ['This is the frozen plan, not a fresh catalogue or GCS listing.',
                   'Original byte checks do not verify publication version, currentness or complete-paper coverage.',
                   'Historical window jobs do not complete the new campaign.',
                   'APS and arXiv representations are not interchangeable.',
                   'Development evidence outside this runtime root is not counted as a corpus-wide readiness certificate.']}
    evidence = {'files': input_files, 'original_objects': list(original_bytes.values()), 'errors': errors,
                'legacy_queue_snapshot': {'columns': ['id','work_id','bundle_hash','state','attempts','config_json','result_hash'],
                                          'rows': jobs, 'sha256': digest(jobs)}}
    (output / 'EVIDENCE.json').write_text(canonical(evidence) + '\n')
    (output / 'READINESS.json').write_text(json.dumps(summary, indent=2) + '\n')
    artifacts = [{'path': p.name, 'bytes': p.stat().st_size, 'sha256': file_hash(p)}
                 for p in sorted(output.iterdir()) if p.is_file()]
    (output / 'FILES.json').write_text(json.dumps({'files': artifacts}, indent=2) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(capture(args.root, args.plan, plan_sha256=args.plan_sha256, output=args.output)))


if __name__ == '__main__':
    main()
