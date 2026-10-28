"""Freeze explicit original representations; this manifest never authorizes NER.

Byte identity and representation selection are separate from publication-version,
supplement and whole-paper coverage review. Old bundles and queues are read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from materials_ner_corpus_readiness import file_hash, source_action
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.planning import load_plan
from ingestion.materials_ner.sources import load_bundle, private_write

SCHEMA = 'materials-source-selection-manifest/1'
DECISIONS = 'materials-source-selection-decisions/1'
OUTPUTS = {'papers.jsonl', 'selections.jsonl', 'SELECTION_PROOF.json', 'INPUT_PINS.json'}


def reference(path):
    return {'path': str(path), 'sha256': file_hash(path), 'bytes': path.stat().st_size}


def check_reference(item, path=None):
    path = Path(path or item['path'])
    if file_hash(path) != item['sha256'] or path.stat().st_size != item['bytes']:
        raise ValueError('input_pin_mismatch: ' + str(path))


def indexed(values, key):
    result = {}
    for value in values:
        if value[key] in result:
            raise ValueError('duplicate_' + key)
        result[value[key]] = value
    return result


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def scientific_representation(bundle):
    """Only incidental metadata may differ in an equivalent-representation choice.

    Source bytes, URIs, document roles, version/rights/coverage labels, every block
    and its location must agree. Selecting different original bytes needs a
    separate version-resolution workflow, never this equivalence shortcut.
    """
    value = deepcopy(bundle.model_dump())
    for key in ('title', 'family', 'acquisition_notes'):
        value.pop(key)
    for document in value['documents']:
        document.pop('parser')
    return value


def usable(item):
    return (item['original_bytes_verified'] and item['processing_allowed']
            and item['has_original_main_document'] and not item['pdf_wrapper_only'])


def freeze(root, plan_path, readiness, *, readiness_files_sha256, decisions_path, output):
    root, plan_path, readiness, decisions_path, output = map(
        Path, (root, plan_path, readiness, decisions_path, output))
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if output.is_relative_to(root) or output.is_relative_to(readiness.resolve()):
        raise ValueError('output_must_be_separate_from_source_and_readiness_roots')
    listing_path = readiness / 'FILES.json'
    if file_hash(listing_path) != readiness_files_sha256:
        raise ValueError('readiness_files_pin_mismatch')
    listing = json.loads(listing_path.read_bytes())['files']
    indexed(listing, 'path')
    if {item['path'] for item in listing} != {
            'READINESS.json', 'papers.jsonl', 'bundles.jsonl', 'EVIDENCE.json'}:
        raise ValueError('readiness_file_inventory_mismatch')
    for item in listing:
        check_reference(item, readiness / item['path'])
    summary = json.loads((readiness / 'READINESS.json').read_bytes())
    evidence = json.loads((readiness / 'EVIDENCE.json').read_bytes())
    plan, plan_hash = load_plan(plan_path)
    papers = indexed(plan['papers'], 'id')
    inventory = indexed(read_rows(readiness / 'papers.jsonl'), 'work_id')
    if (set(papers) != set(inventory) or len(papers) != plan['summary']['papers']
            or len(papers) != summary['papers'] or plan_hash != summary['source_plan_sha256']):
        raise ValueError('paper_denominator_or_plan_pin_mismatch')
    if summary['bundle_errors'] or summary['unverified_original_objects']:
        raise ValueError('repair_source_inventory_before_selection')
    # Verify the frozen inputs, including acquisition/advisory receipts. Historical
    # queue status is retained in the snapshot, never reused as new-run completion.
    pins = {item['path']: item for item in evidence['files']}
    for item in evidence['original_objects']:
        if not item['verified']:
            raise ValueError('unverified_original_source')
        pins[item['path']] = {'path': item['path'], 'bytes': item['bytes'],
                              'sha256': item['expected_sha256']}
    for path in (plan_path, listing_path, decisions_path):
        item = reference(path.resolve())
        if item['path'] in pins and pins[item['path']] != item:
            raise ValueError('conflicting_input_pin')
        pins[item['path']] = item
    for item in listing:
        pin = dict(item, path=str((readiness / item['path']).resolve()))
        pins[pin['path']] = pin
    for item in pins.values():
        check_reference(item)

    raw_decisions = json.loads(decisions_path.read_bytes())
    if raw_decisions.get('schema') != DECISIONS or raw_decisions.get('source_plan_sha256') != plan_hash:
        raise ValueError('decision_schema_or_plan_mismatch')
    decisions = indexed(raw_decisions['selections'], 'work_id')
    bundles = indexed(read_rows(readiness / 'bundles.jsonl'), 'bundle_sha256')
    by_work = defaultdict(list)
    for item in bundles.values():
        if item['work_id'] not in papers:
            raise ValueError('bundle_outside_denominator')
        path = root / 'bundles' / (item['bundle_sha256'] + '.json')
        if file_hash(path) != item['file_sha256']:
            raise ValueError('bundle_file_pin_mismatch')
        by_work[item['work_id']].append(item)

    rows, selected, proofs, used_decisions = [], [], [], set()
    for work, paper in sorted(papers.items()):
        prior, candidates = inventory[work], by_work[work]
        if prior['source'] != paper['source']:
            raise ValueError('paper_source_changed')
        if sorted(prior.get('candidate_bundle_sha256s', [])) != sorted(
                item['bundle_sha256'] for item in candidates):
            raise ValueError('candidate_inventory_changed')
        action = source_action(paper, candidates, prior.get('source_advisory'),
                               prior.get('acquisition_receipts'))
        if action != prior['next_source_action']:
            raise ValueError('source_action_changed')
        possible = {item['bundle_sha256']: item for item in candidates if usable(item)}
        chosen, basis = None, None
        if action == 'source_scope_and_version_preflight_required':
            chosen, basis = next(iter(possible)), 'unique_usable_original_representation'
        elif action == 'source_selection_required' and work in decisions:
            decision = decisions[work]
            if (set(decision) != {'work_id', 'candidate_bundle_sha256s', 'selected_bundle_sha256', 'reason'}
                    or sorted(decision['candidate_bundle_sha256s']) != sorted(possible)
                    or decision['selected_bundle_sha256'] not in possible
                    or not isinstance(decision['reason'], str) or not decision['reason'].strip()):
                raise ValueError('invalid_explicit_source_selection')
            representations = {}
            for identifier in sorted(possible):
                bundle = load_bundle(root / 'bundles' / (identifier + '.json'))
                if digest(bundle.model_dump()) != identifier or bundle.work_id != work:
                    raise ValueError('bundle_identity_mismatch')
                representations[identifier] = digest(scientific_representation(bundle))
            if len(set(representations.values())) != 1:
                raise ValueError('representations_not_equivalent: ' + work)
            chosen, basis = decision['selected_bundle_sha256'], 'explicit_equivalent_representation_choice'
            used_decisions.add(work)
            proofs.append({**decision, 'scientific_representation_sha256s': representations,
                           'publication_version_resolved': False,
                           'original_bundles_modified': False})
            action = 'source_scope_and_version_preflight_required'
        row = {'work_id': work, 'source': paper['source'], 'disposition': action,
               'new_campaign_state': 'not_enqueued'}
        if chosen:
            item = possible[chosen]
            bundle = load_bundle(root / 'bundles' / (chosen + '.json'))
            if digest(bundle.model_dump()) != chosen or bundle.work_id != work:
                raise ValueError('bundle_identity_mismatch')
            # Check against this source root rather than trusting absolute paths in
            # a snapshot built in a different runtime directory.
            for document in bundle.documents:
                path = root / 'sources' / document.source_sha256
                if str(path) not in pins or pins[str(path)]['sha256'] != document.source_sha256:
                    raise ValueError('original_object_not_in_verified_source_root')
            holds = ['paper_coverage_audit_required']
            if any(d.version_status != 'verified' or not d.publication_version for d in bundle.documents):
                holds.append('publication_version_unresolved')
            if bundle.source_status != 'current':
                holds.append('source_currentness_unresolved')
            if bundle.supplement_status == 'not_checked':
                holds.append('supplement_inventory_unchecked')
            selected.append({'work_id': work, 'bundle_sha256': chosen,
                             'file_sha256': item['file_sha256'], 'selection_basis': basis,
                             'original_sha256s': sorted({d.source_sha256 for d in bundle.documents}),
                             'preflight_holds': holds, 'permits_model_dispatch': False})
            row['selected_bundle_sha256'] = chosen
        rows.append(row)
    if used_decisions != set(decisions):
        raise ValueError('unused_or_out_of_scope_source_selection')

    manifest = {'schema': SCHEMA, 'created_at': datetime.now(timezone.utc).isoformat(),
                'source_root': str(root), 'source_plan_sha256': plan_hash,
                'readiness_files_sha256': readiness_files_sha256,
                'source_selection_decisions_sha256': file_hash(decisions_path),
                'papers': len(rows), 'sources': dict(Counter(row['source'] for row in rows)),
                'dispositions': dict(Counter(row['disposition'] for row in rows)),
                'selected_works': len(selected), 'explicit_equivalence_choices': len(proofs),
                'preflight_holds': dict(Counter(h for s in selected for h in s['preflight_holds'])),
                'new_campaign_enqueued': 0, 'new_campaign_completed': 0,
                'permits_model_dispatch': False, 'scientific_acceptance': False,
                'ml_training_eligible': False, 'production_writes': False,
                'limitations': ['This manifest selects representations; it does not resolve publication versions.',
                    'Parser complete_document labels are not paper-coverage certificates.',
                    'APS and withdrawn works retain their holds; no arXiv substitution is allowed.',
                    'Use a later versioned preflight artifact before scheduling reviewed drafts.']}
    output.mkdir(parents=True, exist_ok=False)
    for name, data in [('papers.jsonl', rows), ('selections.jsonl', selected)]:
        private_write(output / name, ''.join(canonical(row) + '\n' for row in data).encode())
    private_write(output / 'SELECTION_PROOF.json', (canonical({'decisions': proofs}) + '\n').encode())
    private_write(output / 'INPUT_PINS.json', (canonical({'files': sorted(pins.values(), key=lambda p: p['path'])}) + '\n').encode())
    manifest['files'] = [dict(reference(output / name), path=name) for name in sorted(OUTPUTS)]
    # Written last: interrupted output without this header is not a manifest.
    private_write(output / 'MANIFEST.json', (json.dumps(manifest, indent=2) + '\n').encode())
    return manifest


def verify(path, *, sha256):
    path = Path(path)
    if file_hash(path) != sha256:
        raise ValueError('source_manifest_pin_mismatch')
    manifest = json.loads(path.read_bytes())
    if manifest.get('schema') != SCHEMA or manifest.get('permits_model_dispatch') is not False:
        raise ValueError('unsupported_source_manifest')
    files = indexed(manifest['files'], 'path')
    if set(files) != OUTPUTS:
        raise ValueError('source_manifest_file_inventory_mismatch')
    for name, item in files.items():
        check_reference(item, path.parent / name)
    pins = json.loads((path.parent / 'INPUT_PINS.json').read_bytes())['files']
    indexed(pins, 'path')
    for item in pins:
        check_reference(item)
    rows = indexed(read_rows(path.parent / 'papers.jsonl'), 'work_id')
    selections = indexed(read_rows(path.parent / 'selections.jsonl'), 'work_id')
    if (len(rows) != manifest['papers'] or len(selections) != manifest['selected_works']
            or dict(Counter(r['disposition'] for r in rows.values())) != manifest['dispositions']):
        raise ValueError('manifest_accounting_mismatch')
    for work, selection in selections.items():
        if (work not in rows or rows[work].get('selected_bundle_sha256') != selection['bundle_sha256']
                or selection['permits_model_dispatch'] is not False):
            raise ValueError('manifest_selection_binding_mismatch')
    return {'verified': True, 'manifest_sha256': sha256, 'papers': len(rows),
            'selected_works': len(selections), 'input_files_verified': len(pins),
            'permits_model_dispatch': False, 'scientific_acceptance': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('freeze')
    for name in ('root', 'plan', 'readiness', 'decisions', 'output'):
        prepare.add_argument('--' + name, type=Path, required=True)
    prepare.add_argument('--readiness-files-sha256', required=True)
    check = commands.add_parser('verify')
    check.add_argument('--manifest', type=Path, required=True)
    check.add_argument('--sha256', required=True)
    args = parser.parse_args()
    result = (freeze(args.root, args.plan, args.readiness, decisions_path=args.decisions,
                     readiness_files_sha256=args.readiness_files_sha256, output=args.output)
              if args.command == 'freeze' else verify(args.manifest, sha256=args.sha256))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
