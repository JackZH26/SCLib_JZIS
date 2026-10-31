"""Assistant-authored /13 graphs beside immutable Luna passage readings.

No automatic conversion of prose to facts, provider impersonation, new SQL
schema, canonical writes or independent scientific acceptance is involved.
"""
import json
from copy import deepcopy

from . import paper_coverage as coverage, reader_scope
from .contract import canonical, digest, parse_extraction
from .sources import Bundle, sha
from .validation import validate_extraction

WORKFLOW = 'reviewed_reader_projection_v1'
FORMAT = 'materials-reviewed-reader-projection/1'
VISUAL_FORMAT = 'materials-reviewed-reader-projection/2'


def source_scope(provenance, bundle):
    c, a = provenance['config'], provenance['attempt']
    raw = provenance['scope_json'].encode(); scope = json.loads(raw)
    reader_scope.shape(scope)
    if (sha(raw) != c['scope']['sha256'] or len(raw) != c['scope']['bytes']
            or a['state'] != 'succeeded' or a['config_sha256'] != digest(c)
            or a['work_id'] != bundle.work_id or c['workflow'] != 'reviewed_reader_v1'
            or c['provider'] != 'codex' or c['model'] != 'gpt-6-luna' or c['reasoning'] != 'medium'
            or not any(p['sha256'] == digest(bundle.model_dump()) for p in c['input_pins'])
            or a['paper_completed'] or a['proposal_generated'] or a['scientific_acceptance']
            or a['ml_training_eligible']):
        raise ValueError('reviewed_proposal_reader_binding')
    blocks = {b.id: b for b in bundle.blocks}; seen = set()
    for p in scope['passages']:
        if set(p) != {'block_id', 'start_char', 'end_char', 'role'}:
            raise ValueError('reviewed_proposal_scope_shape')
        b = blocks.get(p['block_id']); start, end = p['start_char'], p['end_char']
        if (b is None or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(b.text)
                or p['role'] not in {'target', 'context'} or digest(p) in seen):
            raise ValueError('reviewed_proposal_scope_bounds')
        seen.add(digest(p))
    if not any(p['role'] == 'target' for p in scope['passages']):
        raise ValueError('reviewed_proposal_target_required')
    if scope['schema'] == reader_scope.VERSION:
        reader_scope.visual_units(scope, captured_images(provenance, scope), bundle)
    return scope


def captured_images(provenance, scope):
    if scope['schema'] != reader_scope.VERSION or scope['image_capture'] is None: return None
    raw = provenance.get('image_capture_json')
    if (not isinstance(raw, str) or sha(raw.encode()) != scope['image_capture']['sha256']
            or len(raw.encode()) != scope['image_capture']['bytes']):
        raise ValueError('reviewed_proposal_image_capture_pin')
    return json.loads(raw)


def validate_graph(graph, bundle, scope, manifest, visual_support=None, image_capture=None, *, allowed_contracts=('materials-ner/13',), consistency_version=None):
    extraction = parse_extraction(graph)
    if extraction.schema_version not in allowed_contracts or extraction.schema_version not in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}:
        raise ValueError('reviewed_proposal_existing_contract_required')
    visual_quantities = []
    if visual_support is not None:
        from .visual_regions import resolve
        visual_quantities = resolve(visual_support, bundle, manifest, scope, extraction)
        for binding in visual_quantities: reader_scope.require_target(binding, scope, image_capture, bundle)
    result = validate_extraction(extraction, bundle, visual_quantities=visual_quantities, consistency_version=consistency_version)
    result['issues'].extend(coverage.scope_issues(extraction, bundle, result, scope, manifest))
    result['valid'] = not result['issues']; result['reviewed_scope_gate'] = VISUAL_FORMAT if visual_support is not None else FORMAT
    return extraction, result


def make_receipt(*, bundle, graph, manifest, provenance, raw_output, author, created_at, scope_review_complete, note, visual_support=None):
    coverage.authorship(author, created_at)
    if type(scope_review_complete) is not bool or not isinstance(note, str) or not note.strip():
        raise ValueError('reviewed_proposal_review_declaration')
    scope = source_scope(provenance, bundle); attempt = provenance['attempt']
    provenance_fields = {'attempt', 'attempt_pin', 'config', 'scope_json', 'provider_return_json'}
    if scope['schema'] == reader_scope.VERSION and scope['image_capture'] is not None:
        provenance_fields.add('image_capture_json')
    if (set(provenance) != provenance_fields
            or sha(canonical(attempt).encode()) != provenance['attempt_pin']['sha256']
            or len(canonical(attempt).encode()) != provenance['attempt_pin']['bytes']):
        raise ValueError('reviewed_proposal_attempt_pin')
    provider_raw = provenance['provider_return_json'].encode()
    if (sha(provider_raw) != attempt['provider_return']['sha256']
            or len(provider_raw) != attempt['provider_return']['bytes']):
        raise ValueError('reviewed_proposal_provider_pin')
    returned = json.loads(provider_raw)
    if (returned['job_id'] != attempt['job_id'] or returned['attempt_id'] != attempt['attempt_id']
            or returned['config_sha256'] != attempt['config_sha256']
            or returned['result']['text'] != raw_output
            or returned['result']['provider'] != 'codex' or returned['result']['model'] != 'gpt-6-luna'):
        raise ValueError('reviewed_proposal_provider_binding')
    # Portable packet verification must not load a provider, queue or local
    # source paths. The original reader has already checked this container.
    def pairs(items):
        if len(dict(items)) != len(items): raise ValueError('reviewed_proposal_duplicate_reading_key')
        return dict(items)
    parsed = json.loads(raw_output, object_pairs_hook=pairs)
    if (not isinstance(parsed, dict) or set(parsed) != {'reading'}
            or not isinstance(parsed['reading'], str) or not parsed['reading'].strip()):
        raise ValueError('reviewed_proposal_reading_shape')
    if sha(canonical(parsed).encode()) != attempt['reading']['sha256']:
        raise ValueError('reviewed_proposal_raw_reading_changed')
    extraction, validation = validate_graph(graph, bundle, scope, manifest, visual_support, captured_images(provenance, scope))
    output_format = VISUAL_FORMAT if visual_support is not None else FORMAT
    return deepcopy(dict(schema=output_format, job_id=attempt['job_id'], work_id=bundle.work_id,
        bundle_sha256=digest(bundle.model_dump()), state='succeeded' if validation['valid'] else 'quarantined',
        config=dict(workflow=WORKFLOW, output_format=output_format, model='assistant', reader_model=provenance['config']['model']),
        raw_output_sha256=sha(raw_output.encode()), reader_provenance=provenance,
        projection_author=author, created_at=created_at, scope_review_complete=scope_review_complete, note=note,
        extraction=extraction.model_dump(), validation=validation, coverage=manifest,
        **({'visual_support': visual_support} if visual_support is not None else {}),
        structured_graph_authored_by_reader=False, paper_completed=False,
        scientific_acceptance=False, ml_training_eligible=False, production_writes=False))


def build(store, job_id, *, graph, manifest, author, created_at, scope_review_complete=False, note, visual_support=None):
    """Consume a successful terminal attempt only; never dispatch or recover."""
    from . import reviewed_reader as reader
    from .proposals import RELATION_SCHEMA_VERSION, review_rows, verify_packet
    job = reader.row(store, job_id)
    if job['state'] != 'succeeded': raise ValueError('reviewed_proposal_requires_completed_reading')
    attempt = reader._existing(job)
    prepared = reader.prepare_scope(reader.checked(job['config']['scope']))
    if (sha(prepared['prompt'].encode()) != job['config']['prompt_sha256']
            or prepared['bundle_sha256'] != job['bundle_hash']):
        raise ValueError('reviewed_proposal_source_drift')
    preflight = json.loads(reader.checked(prepared['source_scope']['preflight']).read_bytes())
    bundle = Bundle.model_validate(json.loads(reader.checked(preflight['bundle']).read_bytes()))
    coverage.verify(manifest, bundle)
    for r in manifest['visuals'] + manifest['dependencies']:
        for pin in r['evidence']: reader.checked(pin)
    for a in manifest['assertions']:
        if a['visual'] is not None: reader.checked(a['visual']['image'])
    provider_json = reader.checked(attempt['provider_return']).read_text()
    provenance = dict(attempt=attempt, attempt_pin=reader.reference(job['result_path']), config=job['config'],
        scope_json=reader.checked(job['config']['scope']).read_text(), provider_return_json=provider_json)
    scope = prepared['source_scope']
    if scope['schema'] == reader_scope.VERSION and scope['image_capture'] is not None:
        provenance['image_capture_json'] = reader.checked(scope['image_capture']).read_text()
    raw_output = json.loads(provider_json)['result']['text']
    receipt = make_receipt(bundle=bundle, graph=graph, manifest=manifest, provenance=provenance,
        raw_output=raw_output, author=author, created_at=created_at, scope_review_complete=scope_review_complete,
        note=note, visual_support=visual_support)
    if visual_support is not None:
        from .visual_regions import verify_local_assets
        verify_local_assets(visual_support, bundle)
    extraction = parse_extraction(receipt['extraction'])
    packet = dict(schema=RELATION_SCHEMA_VERSION, run_id=digest(receipt), job_id=job_id,
        work_id=bundle.work_id, bundle_hash=digest(bundle.model_dump()), bundle=bundle.model_dump(),
        receipt=receipt, raw_output=raw_output, rows=review_rows(extraction, receipt['validation']),
        evidence=receipt['validation']['resolved_evidence'], scientific_acceptance=False, ml_training_eligible=False)
    packet['packet_hash'] = digest(packet); verify_packet(packet)
    return packet


def verify_receipt(receipt, bundle, raw_output):
    active = receipt.get('config', {}).get('workflow') == WORKFLOW
    if not active and receipt.get('config', {}).get('output_format') not in {FORMAT, VISUAL_FORMAT}: return
    rebuilt = make_receipt(bundle=bundle, graph=receipt['extraction'], manifest=receipt['coverage'],
        provenance=receipt['reader_provenance'], raw_output=raw_output, author=receipt['projection_author'],
        created_at=receipt['created_at'], scope_review_complete=receipt['scope_review_complete'], note=receipt['note'],
        visual_support=receipt.get('visual_support'))
    if canonical(rebuilt) != canonical(receipt): raise ValueError('reviewed_proposal_replay_mismatch')


def paper_status(manifest, bundle, packets, reconciliation=None):
    from .proposals import verify_packet
    reviews = []
    for packet in packets:
        verify_packet(packet); r = packet['receipt']
        if r.get('config', {}).get('workflow') != WORKFLOW:
            raise ValueError('coverage_requires_structured_review')
        reviews.append(dict(work_id=packet['work_id'], bundle_sha256=packet['bundle_hash'],
            coverage_hash=r['coverage']['coverage_hash'], scope_review_complete=r['scope_review_complete'],
            validation=r['validation'], scope=json.loads(r['reader_provenance']['scope_json']),
            packet_hash=packet['packet_hash'], results=r['extraction']['results']))
    result = coverage.progress(manifest, bundle, reviews)
    reconciled = coverage.reconciliation_status(manifest, bundle, reviews, reconciliation)
    result['source_reconciliation'] = reconciled
    result['holds'] = sorted(set(result['holds']) | set(reconciled['holds']))
    result['paper_ready_for_independent_review'] = not result['holds']
    return result


def ingest_local(packet, root):
    """Explicit isolated proposal storage only; preparation namespaces stay empty."""
    from pathlib import Path
    from .proposals import ProposalDatabase, verify_packet
    root = Path(root)
    if (root / 'STAGING_PREPARATION.json').exists():
        raise ValueError('staging_preparation_only')
    verify_packet(packet)
    if packet['receipt'].get('config', {}).get('workflow') != WORKFLOW:
        raise ValueError('reviewed_proposal_wrong_workflow')
    return ProposalDatabase(root).ingest(packet)
