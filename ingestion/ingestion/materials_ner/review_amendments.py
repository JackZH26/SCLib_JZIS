"""Source-backed assistant amendments beside immutable provider attempts.

This is an editorial review record, never a provider receipt, independent
scientific review, canonical identity assignment, or training qualification.
The adapter preserves every parent entity ID. /14 and /15 are explicit opt-in
schema-version change in the source-backed amendment ledger, never an implicit
upgrade of historical /13 amendments or provider returns.
"""
from copy import deepcopy
from datetime import datetime
import json

from .contract import canonical, digest, parse_extraction
from .proposals import verify_packet
from .sources import Bundle, verify_bundle
from .validation import validate_extraction

VERSION = 'materials-proposal-amendment/1'
GROUPS = ('samples', 'states', 'protocols', 'results', 'sample_relations', 'condition_supports')
AUTHOR_KEYS = {'kind', 'identity', 'thread_id'}
FIELDS = {'quantity', 'sample', 'composition', 'method', 'criterion', 'conditions',
          'source_role', 'physical_identity'}
DISPOSITIONS = {'supported', 'corrected', 'not_reported_in_reviewed_scope',
                'source_conflicted', 'not_reviewed', 'source_unavailable'}


def baseline(raw):
    """Mechanical /4..13 adaptation; retain opt-in /14..15 without reinterpretation.

    The immutable source graph plus this deterministic conversion are retained.
    Criteria previously owned by protocols become per-result definitions with
    their evidence; stable condition IDs are local IDs, not physical identities.
    """
    graph = parse_extraction(raw).model_dump()
    version = int(graph['schema_version'].split('/')[-1])
    if version < 4 or version > 15:
        raise ValueError('unsupported_amendment_parent_contract')
    if version < 5:
        protocols = {p['id']: p for p in graph['protocols']}
        for result in graph['results']:
            p = protocols[result['protocol_id']]
            if any(q['kind'] == 'resistance_fraction' for q in p['parameters']):
                raise ValueError('legacy_parameter_migration_needs_explicit_adapter')
            result['definition'] = dict(criterion=p['criterion'], criterion_raw=p['criterion_raw'], parameters=[])
            for e in p['evidence']:
                if e['field'] in {'/criterion', '/criterion_raw'}:
                    result['evidence'].append({**e, 'field': '/definition' + e['field']})
        for p in graph['protocols']:
            del p['criterion'], p['criterion_raw']
            p['evidence'] = [e for e in p['evidence'] if e['field'] not in {'/criterion', '/criterion_raw'}]
            p['context_uses'] = []
    if version < 6:
        states = {s['id']: s for s in graph['states']}
        for s in graph['states']:
            for i, c in enumerate(s['conditions']):
                c['id'] = f'legacy-condition-{i}'
        for p in graph['protocols']:
            for u in p['context_uses']:
                u['condition_id'] = states[u['state_id']]['conditions'][u.pop('condition_index')]['id']
        graph['sample_relations'] = []
        graph['condition_supports'] = []
    if version < 9:
        for sample in graph['samples']:
            sample['formula_unavailability'] = None
    if version < 13:
        for state in graph['states']:
            state['pressure'] = dict(availability='not_extracted', regime='unknown', condition_id=None, basis_raw=None)
    graph['schema_version'] = f'materials-ner/{version}' if version >= 14 else 'materials-ner/13'
    return parse_extraction(graph).model_dump()


def at(value, path):
    if not path.startswith('/') or path == '/':
        raise ValueError('invalid_amendment_pointer')
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def replace(value, path, after):
    parent, _, token = path.rpartition('/')
    target = at(value, parent) if parent else value
    token = token.replace('~1', '/').replace('~0', '~')
    # Replacement only; typos cannot silently create scientific fields.
    at(value, path)
    target[int(token) if isinstance(target, list) else token] = deepcopy(after)


def check_anchor(anchor, blocks):
    if set(anchor) != {'block_id', 'start_char', 'end_char', 'quote'}:
        raise ValueError('amendment_anchor_shape')
    block = blocks[anchor['block_id']]
    a, b = anchor['start_char'], anchor['end_char']
    if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(block.text):
        raise ValueError('amendment_anchor_bounds')
    if block.text[a:b] != anchor['quote']:
        raise ValueError('amendment_anchor_mismatch')


def affected_results(before, after):
    changed = {g: {x['id'] for x, y in zip(before[g], after[g]) if x != y} for g in GROUPS}
    ids = set(changed['results'])
    if before['schema_version'] != after['schema_version']:
        ids.update(r['id'] for r in after['results'])
    for r in after['results']:
        if any(r[k + '_id'] in changed[k + 's'] for k in ('sample', 'state', 'protocol')):
            ids.add(r['id'])
    # Dependency propagation matters even when an unselected result is retained.
    while True:
        old = set(ids)
        ids.update(r['id'] for r in after['results'] if any(e['result_id'] in ids for e in r['dependencies']))
        if old == ids:
            return sorted(ids)


def build(parent, *, bundle, changes, reviews, author, created_at):
    verify_packet(parent)
    if 'extraction' not in parent['receipt']:
        raise ValueError('amendment_parent_graph_unavailable')
    if set(author) != AUTHOR_KEYS or author['kind'] != 'assistant' or not all(author.values()):
        raise ValueError('assistant_authorship_required')
    if datetime.fromisoformat(created_at).tzinfo is None:
        raise ValueError('amendment_timestamp_timezone_required')
    source = Bundle.model_validate(bundle); verify_bundle(source)
    if source.work_id != parent['work_id']:
        raise ValueError('amendment_work_mismatch')
    parent_docs = {d['id']: d for d in parent['bundle']['documents']}
    for d in source.documents:
        if d.id not in parent_docs or d.source_sha256 != parent_docs[d.id]['source_sha256']:
            raise ValueError('amendment_source_artifact_changed')
    blocks = {b.id: b for b in source.blocks}
    # Original source windows remain addressable; expansion is additive.
    for b in parent['bundle']['blocks']:
        if b['id'] not in blocks or blocks[b['id']].model_dump() != b:
            raise ValueError('amendment_parent_block_changed')
    original = baseline(parent['receipt']['extraction']); graph = deepcopy(original)
    for change in changes:
        if set(change) != {'path', 'before', 'after', 'reason', 'anchors'} or not change['reason'].strip():
            raise ValueError('amendment_change_shape')
        path = change['path']
        if path == '/schema_version':
            if (change['before'], change['after']) not in {
                    ('materials-ner/13', 'materials-ner/14'),
                    ('materials-ner/13', 'materials-ner/15'),
                    ('materials-ner/14', 'materials-ner/15')}:
                raise ValueError('amendment_contract_upgrade_not_supported')
        elif path.split('/')[1] not in {*GROUPS, 'processed_block_ids', 'unread_block_ids', 'limitations', 'outcome'}:
            raise ValueError('amendment_path_not_allowed')
        if canonical(at(graph, path)) != canonical(change['before']):
            raise ValueError('amendment_preimage_mismatch')
        if canonical(change['before']) == canonical(change['after']):
            raise ValueError('amendment_noop')
        if not change['anchors']:
            raise ValueError('amendment_source_required')
        for anchor in change['anchors']:
            check_anchor(anchor, blocks)
        replace(graph, path, change['after'])
    graph = parse_extraction(graph).model_dump()
    for group in GROUPS:
        if [x['id'] for x in original[group]] != [x['id'] for x in graph[group]]:
            raise ValueError('amendment_cannot_allocate_or_remove_entities')
    results = {r['id']: r for r in graph['results']}
    seen = set()
    for review in reviews:
        if set(review) != {'result_id', 'fields', 'holds'} or review['result_id'] not in results or review['result_id'] in seen:
            raise ValueError('amendment_review_target')
        seen.add(review['result_id'])
        if set(review['fields']) != FIELDS or not isinstance(review['holds'], list):
            raise ValueError('amendment_review_fields')
        for field in review['fields'].values():
            if set(field) != {'disposition', 'note', 'anchors'} or field['disposition'] not in DISPOSITIONS or not field['note']:
                raise ValueError('amendment_disposition_shape')
            if not field['anchors'] and field['disposition'] not in {'not_reviewed', 'source_unavailable'}:
                raise ValueError('reviewed_field_requires_source_scope')
            for anchor in field['anchors']:
                check_anchor(anchor, blocks)
    if not reviews or not changes:
        raise ValueError('empty_amendment')
    from .validation import CONTEXT_CONSISTENCY_VERSION
    consistency = CONTEXT_CONSISTENCY_VERSION if graph['schema_version'] == 'materials-ner/15' else None
    validation = validate_extraction(parse_extraction(graph), source, consistency_version=consistency)
    contracts = (graph['schema_version'],)
    from .reviewed_proposals import WORKFLOW, validate_graph, source_scope, captured_images
    if parent['receipt'].get('config', {}).get('workflow') == WORKFLOW:
        scope = source_scope(parent['receipt']['reader_provenance'], source)
        _, validation = validate_graph(graph, source,
            scope, parent['receipt']['coverage'], parent['receipt'].get('visual_support'),
            captured_images(parent['receipt']['reader_provenance'], scope), allowed_contracts=contracts,
            consistency_version=consistency)
    source_review = None
    from .projector_proposals import WORKFLOW as PROJECTOR_WORKFLOW
    if parent['receipt'].get('config', {}).get('workflow') == PROJECTOR_WORKFLOW:
        provenance = parent['receipt']['projector_provenance']
        scope = json.loads(provenance['scope_json'])
        manifest = json.loads(provenance['coverage_json'])
        capture = json.loads(provenance['image_capture_json']) if scope['image_capture'] else None
        _, validation = validate_graph(graph, source, scope, manifest, image_capture=capture,
            allowed_contracts=contracts, consistency_version=consistency)
        attachment = parent['receipt']['review_findings']
        findings = json.loads(attachment['text']) if attachment else None
        # Changing one field does not discharge all source observations. Keep
        # their authorship and exact anchors for a subsequent explicit review.
        # Paper omissions remain separate from per-entity technical holds.
        pending = findings['findings'] if findings else []
        validation['issues'] += [dict(path=f['path'], code='source_review_pending_reassessment')
                                 for f in pending if f['kind'] == 'entity']
        validation['valid'] = not validation['issues']
        source_review = dict(status='pending_reassessment', parent_terminal_sha256=provenance['terminal_pin']['sha256'],
            findings_sha256=attachment['pin']['sha256'] if attachment else None,
            findings_author=findings['author'] if findings else None,
            findings_created_at=findings['created_at'] if findings else None,
            findings=deepcopy(pending), paper_completed=False, independent_review=False)
    body = dict(schema=VERSION, parent_run_id=parent['run_id'], parent_packet_hash=parent['packet_hash'],
        parent_graph_hash=digest(parent['receipt']['extraction']), baseline_hash=digest(original),
        work_id=parent['work_id'], author=author, created_at=created_at, bundle=source.model_dump(),
        changes=changes, reviews=reviews, graph=graph, validation=validation,
        affected_result_ids=affected_results(original, graph), selected_result_ids=sorted(seen),
        unreviewed_result_ids=sorted(set(results)-seen), independent_review=False,
        scientific_acceptance=False, ml_training_eligible=False, canonical_writes=False,
        source_scope='Selected source assertions in retained development attempts; no whole-paper completeness claim.')
    if source_review is not None:
        body['source_review'] = source_review
    return {**body, 'amendment_id': digest(body)}


def verify(amendment, parent):
    rebuilt = build(parent, **{k: amendment[k] for k in ('bundle', 'changes', 'reviews', 'author', 'created_at')})
    if canonical(rebuilt) != canonical(amendment):
        raise ValueError('amendment_replay_mismatch')
    return rebuilt


def tc_mapping(amendment):
    """Exact field routing to existing canonical objects, with unallocated IDs.

    There is intentionally no insert function: sample/event/source-occurrence
    identities and independent review must precede canonical writes.
    """
    graph = amendment['graph']
    if graph['schema_version'] != 'materials-ner/13':
        raise ValueError('canonical_tc_mapping_contract_not_qualified')
    indexes = {k: {x['id']: x for x in graph[k]} for k in ('samples', 'states', 'protocols', 'results')}
    mappings = []
    for review_index, review in enumerate(amendment['reviews']):
        r = indexes['results'][review['result_id']]
        if r['quantity_kind'] != 'tc' or r['quantity']['status'] != 'reported':
            raise ValueError('tc_mapping_requires_reported_tc')
        from .quantities import normalize
        normalized = normalize('tc', parse_extraction(graph).results[graph['results'].index(r)].quantity)['normalized']
        s, st, p = [indexes[k][r[f]] for k, f in (('samples', 'sample_id'), ('states', 'state_id'), ('protocols', 'protocol_id'))]
        qualifiers = [q for q in r['qualifiers'] if q['kind'] == 'transition_stage']
        unsupported = [q for q in r['qualifiers'] if q['kind'] != 'transition_stage']
        holds = ['canonical_material_sample_state_event_identity_required', 'registered_source_occurrences_required',
                 'independent_scientific_review_required', 'canonical_context_adoption_required', *review['holds']]
        if unsupported:
            holds.append('non_stage_qualifiers_require_canonical_mapping')
        # Fidelity and experimental qualification are distinct downstream profiles.
        if p['method_class'] == 'unspecified':
            holds.append('experimental_method_unreported')
        if s['identity_resolution'] != 'source_scoped':
            holds.append('source_composition_identity_unresolved')
        mappings.append(dict(source_result_id=r['id'], parent_run_id=amendment['parent_run_id'],
            amendment_id=amendment['amendment_id'], source_sample_id=s['id'], source_state_id=st['id'],
            source_protocol_id=p['id'], target_table='material_claims', target_id=None,
            candidate_fields=dict(property_type='tc', result_status='observed',
                evidence_role='primary_experimental' if r['origin']=='observed' and r['source_role']=='primary' else 'unknown',
                value_relation=normalized['relation'], value_kelvin=normalized.get('value'),
                value_lower_kelvin=normalized.get('lower'), value_upper_kelvin=normalized.get('upper'),
                tc_definition=r['definition']['criterion'], measurement_method=p['method'], validity_status='pending'),
            result_semantics=dict(version='materials-result-semantics/1', definition=r['definition'], qualifiers=qualifiers),
            source_quantity=r['quantity'],
            sample_pointer='/graph/samples/'+str(graph['samples'].index(s)),
            state_pointer='/graph/states/'+str(graph['states'].index(st)),
            protocol_pointer='/graph/protocols/'+str(graph['protocols'].index(p)),
            source_evidence_pointer='/graph/results/'+str(graph['results'].index(r))+'/evidence',
            review_pointer='/reviews/'+str(review_index), unmapped_qualifiers=unsupported,
            holds=sorted(set(holds)), ready_for_canonical_insert=False,
            scientific_acceptance=False, ml_training_eligible=False))
    return dict(schema='materials-reviewed-tc-mapping/1', amendment_id=amendment['amendment_id'], records=mappings,
        note='Field routing only. All identities are unallocated; raw qualifiers, uncertainty and conditions remain in the amendment.')


def review_mapping(amendment):
    """Private result routing, independent of canonical quantity admission.

    Preserve the existing Tc representation byte-for-byte for historical
    amendment IDs. Other kinds/statuses retain native quantities and validation
    without selecting a canonical table, unit or material identity.
    Call only after verify(amendment, parent) at the import boundary.
    """
    from .proposals import review_rows
    graph = amendment['graph']
    indexed = {key:{item['id']:item for item in graph[key]} for key in ('samples','states','protocols','results')}
    selected = [indexed['results'][r['result_id']] for r in amendment['reviews']]
    if graph['schema_version'] == 'materials-ner/13' and all(r['quantity_kind'] == 'tc' and r['quantity']['status'] == 'reported' for r in selected):
        return tc_mapping(amendment)
    rows = {r['local_id']:r for r in review_rows(parse_extraction(graph),amendment['validation'])['results']}
    records = []
    for review_index, review in enumerate(amendment['reviews']):
        result = indexed['results'][review['result_id']]; row = rows[result['id']]
        sample, state, protocol = [indexed[key][result[field]] for key,field in
            (('samples','sample_id'),('states','state_id'),('protocols','protocol_id'))]
        result_index = graph['results'].index(result)
        records.append(dict(source_result_id=result['id'],parent_run_id=amendment['parent_run_id'],
            amendment_id=amendment['amendment_id'],source_sample_id=sample['id'],source_state_id=state['id'],
            source_protocol_id=protocol['id'],target_table=None,target_id=None,
            quantity_kind=result['quantity_kind'],source_quantity=deepcopy(result['quantity']),
            result_semantics=dict(version='materials-result-semantics/2' if graph['schema_version']=='materials-ner/15' else 'materials-result-semantics/1',definition=deepcopy(result['definition']),
                                  qualifiers=deepcopy(result['qualifiers'])),
            dependencies=deepcopy(result['dependencies']),normalized=deepcopy(row['normalized']),
            review_status=row['review_status'],validation_issues=row['issues'],
            result_pointer=f'/graph/results/{result_index}',
            sample_pointer='/graph/samples/'+str(graph['samples'].index(sample)),
            state_pointer='/graph/states/'+str(graph['states'].index(state)),
            protocol_pointer='/graph/protocols/'+str(graph['protocols'].index(protocol)),
            source_evidence_pointer=f'/graph/results/{result_index}/evidence',review_pointer=f'/reviews/{review_index}',
            holds=sorted(set(['canonical_result_mapping_required','independent_scientific_review_required',
                'task_specific_training_qualification_required',*review['holds'],*row['issues']])),
            ready_for_canonical_insert=False,scientific_acceptance=False,ml_training_eligible=False))
    return dict(schema='materials-reviewed-result-mapping/1',amendment_id=amendment['amendment_id'],records=records,
        note='Private result review only. Native quantities, missingness and dependencies are retained. Canonical quantity mapping and independent scientific review remain pending.')
