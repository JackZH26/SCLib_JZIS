"""Operational source coverage, separate from scientific entities and acceptance.

Roles are explicit, exhaustive character partitions of immutable source blocks.
PDF pages and archive graphics remain obligations even when text extraction is
empty. A reading receipt alone cannot discharge any review obligation. Labels
seen only in pixels need typed region evidence, never inserted original text.
"""
from datetime import datetime
from copy import deepcopy
import json
from pathlib import PurePosixPath
import re

from .contract import canonical, digest
from .source_audit import _mask_comments, GRAPHICS_SUFFIXES
from .sources import sha, verify_bundle

VERSION = 'materials-paper-coverage/1'
ROLES = {'main', 'supplement', 'bibliography', 'excluded', 'unreviewed'}


def authorship(author, created_at):
    if (set(author) != {'kind', 'identity', 'thread_id'} or author['kind'] != 'assistant'
            or any(not isinstance(v, str) or not v.strip() for v in author.values())
            or datetime.fromisoformat(created_at).tzinfo is None):
        raise ValueError('coverage_explicit_assistant_authorship_required')


def anchor(value, bundle):
    if set(value) != {'block_id', 'start_char', 'end_char', 'quote'}:
        raise ValueError('coverage_anchor_shape')
    blocks = {b.id: b for b in bundle.blocks}
    b = blocks.get(value['block_id']); a, z = value['start_char'], value['end_char']
    if (b is None or type(a) is not int or type(z) is not int or not 0 <= a < z <= len(b.text)
            or b.text[a:z] != value['quote']):
        raise ValueError('coverage_anchor_mismatch')
    return b


def inventory(bundle, structure):
    verify_bundle(bundle)
    if structure.get('source_sha256') not in {d.source_sha256 for d in bundle.documents}:
        raise ValueError('coverage_structure_source_mismatch')
    visual = []
    if structure['container'] == 'pdf':
        for p in structure['pages']:
            visual.append(dict(id=f"page:{p['page']}", kind='pdf_page', page=p['page'],
                block_ids=[b.id for b in bundle.blocks if b.locator == f"pdf_page:{p['page']}"]))
    else:
        for m in structure['members']:
            if m['regular_file'] and PurePosixPath(m['normalized_name']).suffix.lower() in GRAPHICS_SUFFIXES:
                visual.append(dict(id=f"member:{m['index']}", kind='archive_graphic', member=m['normalized_name']))
    unresolved = [e for e in structure.get('dependency_candidates', []) if e['resolution'] != 'one_literal_candidate']
    unresolved += structure.get('unsupported_dependency_tokens', [])
    dependencies = [dict(id='dependency:' + digest(e), source=e) for e in unresolved]
    return dict(text_blocks=[dict(block_id=b.id, locator=b.locator, characters=len(b.text), sha256=b.sha256)
                             for b in bundle.blocks], visual_units=visual, dependencies=dependencies)


def build(*, source, bundle, roles, visuals, dependencies, supplement, assertions, author, created_at):
    """Pure replay; filesystem pins are checked at capture/projection boundaries."""
    authorship(author, created_at); verify_bundle(bundle)
    if set(source) != {'preflight', 'original', 'publication_version', 'structure_ref', 'structure_json'}:
        raise ValueError('coverage_source_shape')
    raw = source['structure_json'].encode()
    if (sha(raw) != source['structure_ref']['sha256'] or len(raw) != source['structure_ref']['bytes']
            or not re.fullmatch(r'v[1-9]\d*', source['publication_version'])
            or any(d.source_sha256 != source['original']['sha256'] for d in bundle.documents)):
        raise ValueError('coverage_source_binding')
    required = inventory(bundle, json.loads(raw)); blocks = {b.id: b for b in bundle.blocks}
    by_block = {identifier: [] for identifier in blocks}
    for r in roles:
        if (set(r) != {'block_id', 'start_char', 'end_char', 'role', 'note', 'anchors'}
                or r['role'] not in ROLES or not isinstance(r['note'], str) or not r['note'].strip()
                or r['block_id'] not in blocks):
            raise ValueError('coverage_role_shape')
        a, z = r['start_char'], r['end_char']
        if type(a) is not int or type(z) is not int or not 0 <= a < z <= len(blocks[r['block_id']].text):
            raise ValueError('coverage_role_bounds')
        if r['role'] != 'unreviewed' and not r['anchors']:
            raise ValueError('coverage_role_requires_source')
        for e in r['anchors']: anchor(e, bundle)
        by_block[r['block_id']].append((a, z))
    for identifier, spans in by_block.items():
        end = 0
        for a, z in sorted(spans):
            if a != end: raise ValueError('coverage_role_gap_or_overlap')
            end = z
        if end != len(blocks[identifier].text): raise ValueError('coverage_role_gap_or_overlap')
    for rows, units, label in [(visuals, required['visual_units'], 'visual'),
                               (dependencies, required['dependencies'], 'dependency')]:
        if sorted(r['id'] for r in rows) != sorted(u['id'] for u in units):
            raise ValueError('coverage_' + label + '_inventory_mismatch')
        for r in rows:
            if (set(r) != {'id', 'status', 'note', 'evidence'} or r['status'] not in {'pending', 'reviewed'}
                    or not isinstance(r['note'], str) or not r['note'].strip()
                    or not isinstance(r['evidence'], list) or (r['status'] == 'reviewed' and not r['evidence'])):
                raise ValueError('coverage_' + label + '_review_shape')
            for pin in r['evidence']:
                if set(pin) != {'path', 'bytes', 'sha256'}: raise ValueError('coverage_review_evidence_pin')
    if (set(supplement) != {'status', 'note', 'anchors'} or not supplement['note'].strip()
            or supplement['status'] not in {'not_checked', 'embedded_identified', 'external_missing',
                                            'reviewed_complete', 'reviewed_none_reported'}):
        raise ValueError('coverage_supplement_shape')
    if supplement['status'] != 'not_checked' and not supplement['anchors']:
        raise ValueError('coverage_supplement_requires_source')
    for e in supplement['anchors']: anchor(e, bundle)
    seen = set(); visual_ids = {v['id'] for v in required['visual_units']}
    for a in assertions:
        if (set(a) != {'id', 'kind', 'anchor', 'visual', 'note'} or not a['id'] or a['id'] in seen
                or a['kind'] not in {'text_result', 'figure_label'} or not a['note'].strip()):
            raise ValueError('coverage_assertion_shape')
        seen.add(a['id']); anchor(a['anchor'], bundle)
        if a['kind'] == 'text_result':
            if a['visual'] is not None: raise ValueError('coverage_text_assertion_visual')
        else:
            v = a['visual']
            if (not isinstance(v, dict) or set(v) != {'unit_id', 'image', 'region', 'label'}
                    or v['unit_id'] not in visual_ids or not v['label'].strip()
                    or set(v['image']) != {'path', 'sha256', 'bytes'}):
                raise ValueError('coverage_visual_assertion_shape')
            box = v['region']
            if (not isinstance(box, list) or len(box) != 4 or any(type(n) not in {int, float} for n in box)
                    or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
                raise ValueError('coverage_visual_region')
    body = dict(schema=VERSION, work_id=bundle.work_id, bundle_sha256=digest(bundle.model_dump()),
                source=source, inventory=required, roles=roles, visuals=visuals, dependencies=dependencies,
                supplement=supplement, assertions=assertions, author=author, created_at=created_at,
                independent_review=False, scientific_acceptance=False, ml_training_eligible=False)
    return deepcopy({**body, 'coverage_hash': digest(body)})


def verify(manifest, bundle):
    rebuilt = build(bundle=bundle, **{k: manifest[k] for k in (
        'source', 'roles', 'visuals', 'dependencies', 'supplement', 'assertions', 'author', 'created_at')})
    if canonical(rebuilt) != canonical(manifest): raise ValueError('coverage_replay_mismatch')
    return rebuilt


def seed(preflight_pin, *, author, created_at):
    from .reviewed_reader import source_input, checked
    p, b, _ = source_input(preflight_pin)
    structure_json = checked(p['structure']).read_text()
    required = inventory(b, json.loads(structure_json))
    return build(source=dict(preflight=preflight_pin, original=p['original'],
        publication_version=p['exact_version_binding']['publication_version'], structure_ref=p['structure'],
        structure_json=structure_json), bundle=b,
        roles=[dict(block_id=x.id, start_char=0, end_char=len(x.text), role='unreviewed',
                    note='Source role not yet reviewed.', anchors=[]) for x in b.blocks],
        visuals=[dict(id=x['id'], status='pending', note='Original visual content has not been reviewed.', evidence=[])
                 for x in required['visual_units']],
        dependencies=[dict(id=x['id'], status='pending', note='Literal dependency lookup requires review.', evidence=[])
                      for x in required['dependencies']],
        supplement=dict(status='not_checked', note='Supplement availability and completeness not established.', anchors=[]),
        assertions=[], author=author, created_at=created_at)


def inside(evidence, ranges):
    """Require a single declared span; crossing a role/scope boundary is not enough."""
    return any(evidence['block_id'] == r['block_id'] and r['start_char'] <= evidence['start_char']
               and evidence['end_char'] <= r['end_char'] for r in ranges)


def published(evidence, manifest, bundle, *, bibliography=False):
    roles = {'main', 'supplement', *({'bibliography'} if bibliography else set())}
    if not inside(evidence, [r for r in manifest['roles'] if r['role'] in roles]):
        return False
    block = next(b for b in bundle.blocks if b.id == evidence['block_id'])
    doc = next(d for d in bundle.documents if d.id == block.document_id)
    if doc.source_kind == 'original_tex':
        a, z = evidence['start_char'], evidence['end_char']
        # Reject quotes crossing unpublished percent-comment text. Complex TeX
        # conditional environments still require explicit role/dependency review.
        return _mask_comments(block.text)[a:z] == block.text[a:z]
    return True


def literal_value_in_quote(raw, quote):
    """A whole raw expression, not a substring such as 5 K inside 15 K."""
    raw, quote = ' '.join((raw or '').split()), ' '.join(quote.split())
    return bool(raw) and re.search(r'(?<![\w.+−-])' + re.escape(raw) + r'(?!\w|\.\d)', quote) is not None


def scope_issues(extraction, bundle, validation, scope, manifest):
    verify(manifest, bundle)
    if scope['preflight'] != manifest['source']['preflight']:
        raise ValueError('coverage_reader_source_mismatch')
    issues = []
    def issue(code, path): issues.append(dict(code=code, path=path))
    resolved = validation['resolved_evidence']
    for e in resolved:
        context = e['caption'] if e.get('kind') == 'visual_region' else e
        if not inside(context, scope['passages']): issue('evidence_outside_reader_scope', e['path'])
        if not published(context, manifest, bundle, bibliography=e['path'].endswith('/cited_source_raw')):
            issue('evidence_source_role_unreviewed_or_unpublished', e['path'])
    target = [r for r in scope['passages'] if r['role'] == 'target']
    for i, r in enumerate(extraction.results):
        prefix = f'/results/{i}'
        if r.quantity_kind == 'non_detection':
            bearing = {prefix + '/quantity_kind', *(prefix + f'/qualifiers/{n}' for n in range(len(r.qualifiers)))}
            raw = next(q.raw for q in r.qualifiers if q.kind == 'non_detection')
        else:
            bearing = {prefix + '/quantity', *(prefix + '/quantity/' + f for f in ['raw', 'value', 'lower', 'upper'])}
            raw = r.quantity.raw
        anchors = [e for e in resolved if e['path'] in bearing]
        blocks = {b.id: b for b in bundle.blocks}
        def witness(e):
            context = e['caption'] if e.get('kind') == 'visual_region' else e
            quote = e['transcription'] if e.get('kind') == 'visual_region' else blocks[e['block_id']].text[e['start_char']:e['end_char']]
            return (inside(context, target) and published(context, manifest, bundle)
                   and (r.quantity.status != 'reported' and r.quantity_kind != 'non_detection'
                        or literal_value_in_quote(raw, quote)))
        if not any(witness(e) for e in anchors):
            issue('result_without_target_original_evidence', prefix)
    return issues


def union_length(spans):
    end = -1; total = 0
    for a, z in sorted(spans):
        total += max(0, z - max(a, end)); end = max(end, z)
    return total


def progress(manifest, bundle, reviews):
    """reviews are verified structured-scope reviews, never raw reading strings.

    A complete scope review is an attributed assistant assertion, not an
    independently measured recall denominator. Bound visual labels discharge
    their specific assertion only, never all figures or the entire page.
    """
    verify(manifest, bundle); holds = []
    if any(r['role'] == 'unreviewed' for r in manifest['roles']): holds.append('source_roles_unreviewed')
    if manifest['supplement']['status'] not in {'reviewed_complete', 'reviewed_none_reported'}:
        holds.append('supplement_coverage_unresolved')
    if any(r['status'] != 'reviewed' for r in manifest['visuals']): holds.append('visual_units_unreviewed')
    if any(r['status'] != 'reviewed' for r in manifest['dependencies']): holds.append('source_dependencies_unresolved')
    targets = []; resolved = []; visual_bound = set()
    for r in reviews:
        if (r['work_id'] != bundle.work_id or r['coverage_hash'] != manifest['coverage_hash']
                or r['bundle_sha256'] != manifest['bundle_sha256']):
            raise ValueError('coverage_progress_review_identity')
        visual_bound.update(e['assertion_id'] for e in r['validation']['resolved_evidence']
                            if e.get('kind') == 'visual_region')
        if not r['scope_review_complete'] or not r['validation']['valid']:
            holds.append('structured_scope_review_incomplete'); continue
        targets.extend(p for p in r['scope']['passages'] if p['role'] == 'target')
        resolved.extend(r['validation']['resolved_evidence'])
    required = covered = 0
    for r in manifest['roles']:
        if r['role'] not in {'main', 'supplement'}: continue
        required += r['end_char'] - r['start_char']
        clipped = [(max(r['start_char'], p['start_char']), min(r['end_char'], p['end_char']))
                   for p in targets if p['block_id'] == r['block_id']
                   and p['start_char'] < r['end_char'] and r['start_char'] < p['end_char']]
        covered += union_length(clipped)
    if not required or covered != required: holds.append('required_text_not_reviewed')
    unresolved_assertions = []
    for a in manifest['assertions']:
        # A caption cannot discharge a label printed only inside a figure.
        if a['kind'] == 'figure_label':
            if a['id'] not in visual_bound:
                unresolved_assertions.append(a['id']); holds.append('visual_result_evidence_adapter_required')
        elif not any(e['path'].startswith('/results/') and '/quantity' in e['path']
                     and inside(a['anchor'], [e]) for e in resolved):
            unresolved_assertions.append(a['id']); holds.append('inventoried_result_not_bound')
    return dict(work_id=bundle.work_id, coverage_hash=manifest['coverage_hash'], required_text_characters=required,
        reviewed_target_characters=covered, visual_units=len(manifest['visuals']),
        visual_units_reviewed=sum(r['status'] == 'reviewed' for r in manifest['visuals']),
        unresolved_assertion_ids=unresolved_assertions, holds=sorted(set(holds)),
        paper_ready_for_independent_review=not holds, scientific_acceptance=False, ml_training_eligible=False)


RECONCILIATION_VERSION = 'materials-paper-reconciliation/1'
EXCLUSION_REASONS = {'measurement_condition', 'preparation_condition', 'model_input',
                     'reference_label', 'not_superconducting_result', 'unpublished_source'}


def review_units(manifest, bundle):
    """Deterministic original-coordinate obligations; no rewritten window bundle."""
    from .evidence import source_spans
    verify(manifest, bundle); blocks = {b.id: b for b in bundle.blocks}; units = []
    for role in manifest['roles']:
        if role['role'] not in {'main', 'supplement'}: continue
        block = blocks[role['block_id']]; begin, end = role['start_char'], role['end_char']
        for a, z in source_spans(block.text[begin:end]):
            a += begin; z += begin
            units.append(dict(id=f'text:{block.id}:{a}:{z}', kind='text', block_id=block.id,
                start_char=a, end_char=z, locator=block.locator, source_role=role['role']))
    for visual in manifest['inventory']['visual_units']:
        units.append(dict(id='visual:' + visual['id'], kind='visual', visual_id=visual['id']))
    return units


def reconciliation(*, manifest, bundle, units, dispositions, exclusions, author, created_at):
    """Attributed coverage decisions, separate from graph and model output schemas.

    Existing manifest assertions are the result inventory. This artifact adds
    explicit dispositions and reviews of all deterministic source units. It
    cannot certify that the author's scientific inventory is exhaustive.
    """
    authorship(author, created_at); expected = review_units(manifest, bundle)
    if (not isinstance(units, list) or sorted(u['id'] for u in units) != sorted(u['id'] for u in expected)):
        raise ValueError('reconciliation_unit_inventory')
    for u in units:
        if (set(u) != {'id', 'status', 'note'} or u['status'] not in {'pending', 'reviewed'}
                or not isinstance(u['note'], str) or not u['note'].strip()):
            raise ValueError('reconciliation_unit_review')
    assertions = {a['id']: a for a in manifest['assertions']}
    if (not isinstance(dispositions, list)
            or sorted(d['assertion_id'] for d in dispositions) != sorted(assertions)):
        raise ValueError('reconciliation_assertion_inventory')
    for d in dispositions:
        if (set(d) != {'assertion_id', 'action', 'targets', 'repeat_of', 'note'}
                or d['action'] not in {'bound', 'repeat', 'held'} or not isinstance(d['targets'], list)
                or not isinstance(d['note'], str) or not d['note'].strip()):
            raise ValueError('reconciliation_disposition_shape')
        if d['action'] == 'bound':
            if not d['targets'] or d['repeat_of'] is not None: raise ValueError('reconciliation_bound_shape')
        elif d['targets'] or (d['action'] == 'held' and d['repeat_of'] is not None):
            raise ValueError('reconciliation_held_or_repeat_shape')
        if d['action'] == 'repeat' and (d['repeat_of'] not in assertions or d['repeat_of'] == d['assertion_id']):
            raise ValueError('reconciliation_repeat_target')
        seen = set()
        for target in d['targets']:
            if (set(target) != {'packet_hash', 'result_id'}
                    or not isinstance(target['packet_hash'], str) or not re.fullmatch('[a-f0-9]{64}', target['packet_hash'])
                    or not isinstance(target['result_id'], str) or not target['result_id'].strip()
                    or (target['packet_hash'], target['result_id']) in seen):
                raise ValueError('reconciliation_result_reference')
            seen.add((target['packet_hash'], target['result_id']))
    if not isinstance(exclusions, list): raise ValueError('reconciliation_exclusions_shape')
    seen = set(assertions)
    for e in exclusions:
        if (set(e) != {'id', 'anchor', 'reason', 'note'} or not isinstance(e['id'], str)
                or not e['id'].strip() or e['id'] in seen or e['reason'] not in EXCLUSION_REASONS
                or not isinstance(e['note'], str) or not e['note'].strip()):
            raise ValueError('reconciliation_exclusion_shape')
        seen.add(e['id']); anchor(e['anchor'], bundle)
        if (e['reason'] != 'unpublished_source' and not published(e['anchor'], manifest, bundle)):
            raise ValueError('reconciliation_exclusion_source_role')
        if e['reason'] == 'unpublished_source' and published(e['anchor'], manifest, bundle):
            raise ValueError('reconciliation_published_source_excluded_as_unpublished')
        if e['reason'] == 'unpublished_source':
            source = anchor(e['anchor'], bundle)
            doc = next(d for d in bundle.documents if d.id == source.document_id)
            a, z = e['anchor']['start_char'], e['anchor']['end_char']
            excluded = inside(e['anchor'], [r for r in manifest['roles'] if r['role'] == 'excluded'])
            comment_only = doc.source_kind == 'original_tex' and not _mask_comments(source.text)[a:z].strip()
            if not (excluded or comment_only): raise ValueError('reconciliation_unpublished_source_not_proven')
    body = dict(schema=RECONCILIATION_VERSION, work_id=bundle.work_id, bundle_sha256=digest(bundle.model_dump()),
        coverage_hash=manifest['coverage_hash'], units=units, dispositions=dispositions, exclusions=exclusions,
        author=author, created_at=created_at, independent_review=False, scientific_acceptance=False, ml_training_eligible=False)
    return deepcopy(dict(body, reconciliation_hash=digest(body)))


def seed_reconciliation(manifest, bundle, *, author, created_at):
    return reconciliation(manifest=manifest, bundle=bundle, author=author, created_at=created_at,
        units=[dict(id=u['id'], status='pending', note='Original source unit has not been fully reviewed.')
               for u in review_units(manifest, bundle)],
        dispositions=[dict(assertion_id=a['id'], action='held', targets=[], repeat_of=None,
            note='Inventoried source assertion has no reviewed result disposition.') for a in manifest['assertions']], exclusions=[])


def reconciliation_status(manifest, bundle, reviews, ledger):
    """Reconcile verified current packets; matching a number alone never suffices.

    Multiple source occurrences may explicitly repeat one result only if each
    has its own matching source evidence in that result. This is bookkeeping
    and source identity validation, not scientific equivalence adjudication.
    """
    if ledger is None:
        return dict(reconciliation_hash=None, holds=['source_reconciliation_missing'], mechanically_reconciled=False,
                    scientific_acceptance=False, ml_training_eligible=False)
    rebuilt = reconciliation(manifest=manifest, bundle=bundle, **{k: ledger[k] for k in
        ('units', 'dispositions', 'exclusions', 'author', 'created_at')})
    if canonical(rebuilt) != canonical(ledger): raise ValueError('reconciliation_replay_mismatch')
    holds = set(); blocks = {b.id: b for b in bundle.blocks}; result_map = {}; packets = set()
    for review in reviews:
        if (review['work_id'] != bundle.work_id or review['bundle_sha256'] != manifest['bundle_sha256']
                or review['coverage_hash'] != manifest['coverage_hash'] or review['packet_hash'] in packets):
            raise ValueError('reconciliation_current_packet_identity')
        packets.add(review['packet_hash'])
        if not review['validation']['valid']: holds.add('candidate_validation_holds')
        for index, result in enumerate(review['results']):
            result_map[(review['packet_hash'], result['id'])] = (index, result, review)
    unit_index = {u['id']: u for u in review_units(manifest, bundle)}
    visual_index = {v['id']: v for v in manifest['visuals']}
    pending = [u['id'] for u in ledger['units'] if u['status'] != 'reviewed']
    if pending: holds.add('source_units_unreviewed')
    for u in ledger['units']:
        source = unit_index[u['id']]
        if (u['status'] == 'reviewed' and source['kind'] == 'visual'
                and visual_index[source['visual_id']]['status'] != 'reviewed'):
            holds.add('visual_unit_review_not_established')
    assertions = {a['id']: a for a in manifest['assertions']}
    dispositions = {d['assertion_id']: d for d in ledger['dispositions']}
    def resolve(identifier):
        trail = set()
        while identifier not in trail:
            trail.add(identifier); d = dispositions[identifier]
            if d['action'] == 'held': return [], 'explicit_hold'
            if d['action'] == 'bound': return d['targets'], None
            identifier = d['repeat_of']
        return [], 'repeat_cycle'
    def witness(assertion, index, result, review):
        prefix = f'/results/{index}/'
        fields = {prefix + 'quantity', prefix + 'quantity/raw', prefix + 'quantity/value', prefix + 'quantity/lower', prefix + 'quantity/upper'}
        if result['quantity_kind'] == 'non_detection':
            fields = {prefix + 'quantity_kind', *(prefix + f'qualifiers/{i}' for i in range(len(result['qualifiers'])))}
            raw = next(q['raw'] for q in result['qualifiers'] if q['kind'] == 'non_detection')
        else: raw = result['quantity']['raw'] if result['quantity']['status'] == 'reported' else None
        for e in review['validation']['resolved_evidence']:
            if e['path'] not in fields: continue
            if assertion['kind'] == 'figure_label':
                if e.get('kind') == 'visual_region' and e['assertion_id'] == assertion['id']: return True
                continue
            a = assertion['anchor']
            if e.get('kind') == 'visual_region' or e['block_id'] != a['block_id']: continue
            start, end = max(e['start_char'], a['start_char']), min(e['end_char'], a['end_char'])
            if start < end and published(a, manifest, bundle) and (raw is None
                    or literal_value_in_quote(raw, blocks[a['block_id']].text[start:end])): return True
        return False
    matched = set(); primary = {}; rows = []
    for identifier, assertion in assertions.items():
        targets, issue = resolve(identifier); checked_targets = []
        for target in targets:
            key = (target['packet_hash'], target['result_id']); found = result_map.get(key)
            if found is None: issue = 'result_not_in_current_packets'
            elif not witness(assertion, *found): issue = 'result_source_disconnected'
            else:
                matched.add(key); checked_targets.append(target)
                if dispositions[identifier]['action'] == 'bound': primary.setdefault(key, []).append(identifier)
        if issue: holds.add('source_assertions_unresolved')
        rows.append(dict(assertion_id=identifier, action=dispositions[identifier]['action'], issue=issue,
            source_bound_targets=checked_targets, repeat_of=dispositions[identifier]['repeat_of']))
    repeated = [dict(packet_hash=k[0], result_id=k[1], assertion_ids=v) for k, v in primary.items() if len(v) > 1]
    if repeated: holds.add('repeated_result_requires_explicit_disposition')
    unlisted = [dict(packet_hash=k[0], result_id=k[1]) for k in sorted(set(result_map) - matched)]
    if unlisted: holds.add('candidate_results_missing_from_inventory')
    contradictions = [e['id'] for e in ledger['exclusions'] if any(
        a['kind'] == 'text_result' and inside(a['anchor'], [e['anchor']]) for a in assertions.values())]
    if contradictions: holds.add('source_assertion_also_excluded')
    return dict(reconciliation_hash=ledger['reconciliation_hash'], source_units=len(ledger['units']),
        reviewed_source_units=len(ledger['units']) - len(pending), pending_source_unit_ids=pending,
        source_assertions=len(assertions), source_assertions_with_binding=sum(bool(r['source_bound_targets']) and not r['issue'] for r in rows),
        assertion_dispositions=rows, exclusions=len(ledger['exclusions']), contradictory_exclusion_ids=contradictions,
        unlisted_results=unlisted, repeated_result_bindings=repeated, unique_candidate_results=len(result_map),
        holds=sorted(holds), mechanically_reconciled=not holds, source_semantic_coverage_verified=False,
        independent_gold=False, scientific_acceptance=False, ml_training_eligible=False)
