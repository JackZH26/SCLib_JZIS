"""Authentic automatic drafts into the existing, non-canonical proposal store.

Build reads a terminal queue without dispatch or recovery. Portable verification
replays source binding and validation, never executes captured implementation.
Hashes provide integrity relative to a retained receipt/packet, not signatures
or independent scientific approval. Unsupported producer versions fail closed.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from . import paper_coverage, projection_binding, projector_schema, reader_scope, scoped_evidence, source_focus
from . import reviewed_reader as reader, reviewed_proposals, source_projector
from .contract import canonical, digest, parse_extraction
from .sources import Bundle, sha

WORKFLOW = 'source_projector_proposal_v1'
FORMAT = 'materials-source-projector-proposal/1'
FINDINGS = 'materials-projector-review-findings/1'


def _text(path):
    # Path.read_text performs universal newline conversion. Original TeX prompts
    # can contain CRLF; a receipt must preserve those bytes exactly.
    return Path(path).read_bytes().decode('utf-8')


def unpack(pin, text):
    if (not isinstance(text, str) or sha(text.encode()) != pin['sha256']
            or len(text.encode()) != pin['bytes']):
        raise ValueError('projector_proposal_embedded_pin')
    return source_projector.decode_output(text)


def _scope(scope, bundle, capture):
    reader_scope.shape(scope)
    blocks = {b.id: b for b in bundle.blocks}
    seen = set()
    for p in scope['passages']:
        if set(p) != {'block_id', 'start_char', 'end_char', 'role'}:
            raise ValueError('projector_proposal_scope_shape')
        b = blocks.get(p['block_id']); a, z = p['start_char'], p['end_char']
        if (b is None or type(a) is not int or type(z) is not int
                or not 0 <= a < z <= len(b.text) or p['role'] not in {'target', 'context'}
                or digest(p) in seen):
            raise ValueError('projector_proposal_scope_bounds')
        seen.add(digest(p))
    if not any(p['role'] == 'target' for p in scope['passages']):
        raise ValueError('projector_proposal_target_required')
    reader_scope.visual_units(scope, capture, bundle)


def _findings(attachment, bundle, attempt_pin, graph, scope, manifest):
    """Assistant observations can add holds; they cannot approve or edit facts."""
    if attachment is None:
        return [], []
    if set(attachment) != {'pin', 'text'}:
        raise ValueError('projector_proposal_findings_attachment')
    value = unpack(attachment['pin'], attachment['text'])
    if (set(value) != {'schema', 'work_id', 'bundle_sha256', 'attempt_sha256', 'author',
                      'created_at', 'independent_review', 'findings'}
            or value['schema'] != FINDINGS or value['work_id'] != bundle.work_id
            or value['bundle_sha256'] != digest(bundle.model_dump())
            or value['attempt_sha256'] != attempt_pin['sha256']
            or value['independent_review'] is not False):
        raise ValueError('projector_proposal_findings_identity')
    paper_coverage.authorship(value['author'], value['created_at'])
    issues, omissions, seen = [], [], set()
    for item in value['findings']:
        if (set(item) != {'id', 'kind', 'path', 'code', 'note', 'anchors'}
                or not isinstance(item['id'], str) or not item['id'] or item['id'] in seen
                or item['kind'] not in {'entity', 'source_completeness'}
                or not isinstance(item['code'], str) or not re.fullmatch('[a-z][a-z0-9_]*', item['code'])
                or not isinstance(item['note'], str) or not item['note'].strip()
                or not isinstance(item['anchors'], list) or not item['anchors']):
            raise ValueError('projector_proposal_finding_shape')
        seen.add(item['id'])
        for anchor in item['anchors']:
            paper_coverage.anchor(anchor, bundle)
            if not paper_coverage.inside(anchor, scope['passages']) or not paper_coverage.published(anchor, manifest, bundle):
                raise ValueError('projector_proposal_finding_outside_source')
        if item['kind'] == 'source_completeness':
            if item['path'] != '/paper':
                raise ValueError('projector_proposal_completeness_path')
            omissions.append(item)
        else:
            match = re.fullmatch(r'/(samples|states|protocols|results|sample_relations|condition_supports)/(0|[1-9]\d*)', item['path'])
            if graph is None or match is None or int(match[2]) >= len(graph[match[1]]):
                raise ValueError('projector_proposal_finding_owner')
            issues.append(dict(path=item['path'], code='source_review_' + item['code']))
    return issues, omissions


def make_receipt(bundle, provenance, review_findings=None):
    """Pure portable replay of a captured terminal attempt and its evidence."""
    required = {'terminal_pin', 'terminal_json', 'config', 'request_json', 'scope_json',
                'coverage_json', 'preflight_json', 'provider_json', 'captured', 'artifacts'}
    if not required <= set(provenance) or set(provenance) - required - {'image_capture_json', 'source_focus_json', 'projector_request_json'}:
        raise ValueError('projector_proposal_provenance_shape')
    p = provenance; c = p['config']; a = unpack(p['terminal_pin'], p['terminal_json'])
    from . import production_tc
    tc_profile = c.get('workflow') == production_tc.WORKFLOW
    producer = production_tc if tc_profile else source_projector
    if (c.get('workflow') != producer.WORKFLOW or c.get('provider') != 'codex'
            or c.get('model') not in ['gpt-6-luna', 'gpt-6.1-sol'] or c.get('automatic_attempts') != 1
            or c.get('graph_schema') not in {'materials-ner/13','materials-ner/14','materials-ner/15'}
            or c.get('interface_version') != projector_schema.interface_version(c['graph_schema'], c.get('interface_version'))
            or c.get('binding_version') != projection_binding.VERSION
            or a.get('schema') != producer.ATTEMPT_SCHEMA
            or a['config_sha256'] != digest(c) or a['work_id'] != bundle.work_id
            or a['bundle_sha256'] != digest(bundle.model_dump())
            or a['state'] not in {'succeeded', 'quarantined'}
            or a.get('graph_authorship') != c['model']
            or any(a.get(k) is not False for k in ['automatic_retry', 'semantic_validation_qualified',
                'paper_completed', 'proposal_generated', 'scientific_acceptance', 'ml_training_eligible', 'production_writes'])
            or c.get('scientific_acceptance') is not False):
        raise ValueError('projector_proposal_terminal_identity_or_version')
    request = unpack(c['request'], p['request_json'])
    additional_pins = []
    if tc_profile:
        if (set(request) != {'schema', 'projector_input'} or request['schema'] != production_tc.INPUT_SCHEMA
                or 'projector_request_json' not in p or c.get('extraction_scope') != 'explicit_tc'
                or c.get('admission_policy') != 'production90/1'):
            raise ValueError('projector_proposal_tc_profile')
        additional_pins.append(request['projector_input'])
        request = unpack(request['projector_input'], p['projector_request_json'])
    elif 'projector_request_json' in p:
        raise ValueError('projector_proposal_unexpected_tc_request')
    scope = unpack(request['scope'], p['scope_json'])
    manifest = unpack(request['coverage'], p['coverage_json'])
    preflight = unpack(scope['preflight'], p['preflight_json'])
    for pin in [c['request'], *additional_pins, request['scope'], request['coverage'], scope['preflight'], preflight['bundle']]:
        if pin not in c['input_pins']:
            raise ValueError('projector_proposal_input_not_frozen')
    graph_schema = source_projector.request_contract(request)
    profile = request.get('execution_profile')
    if (c['model'] != (profile['model'] if profile else 'gpt-6-luna')
            or c['reasoning'] != ('high' if tc_profile else profile['reasoning'] if profile else 'medium')
            or c.get('execution_profile') != profile):
        raise ValueError('projector_proposal_execution_identity')
    expected_identity = source_projector.provenance(c).get('provider_model_identity')
    if (a.get('provider_model_identity') != expected_identity
            or ('provider_model_identity' in a) != (expected_identity is not None)):
        raise ValueError('projector_proposal_model_attestation')
    if (graph_schema != c['graph_schema']
            or c.get('consistency_version') != request.get('consistency_version')
            or ('consistency_version' in c) != ('consistency_version' in request)
            or c['interface_version'] != projector_schema.interface_version(graph_schema, request.get('interface_version'))
            or preflight['bundle_sha256'] != digest(bundle.model_dump())
            or preflight['bundle']['sha256'] != digest(bundle.model_dump())
            or preflight['work_id'] != bundle.work_id
            or preflight['permits_bounded_passage_reading'] is not True
            or preflight['official_identity_verified'] is not True
            or preflight['scientific_acceptance'] is not False
            or manifest['source']['preflight'] != scope['preflight']
            or manifest['source']['original'] != preflight['original']
            or manifest['source']['publication_version'] != preflight['exact_version_binding']['publication_version']):
        raise ValueError('projector_proposal_original_binding')
    paper_coverage.verify(manifest, bundle)
    capture = unpack(scope['image_capture'], p['image_capture_json']) if scope['image_capture'] else None
    _scope(scope, bundle, capture)
    focus = None
    if request['schema'] == source_projector.FOCUSED_INPUT_SCHEMA:
        if 'source_focus_json' not in p or request['source_focus'] not in c['input_pins']:
            raise ValueError('projector_proposal_focus_not_frozen')
        focus = unpack(request['source_focus'], p['source_focus_json'])
        source_focus.verify(focus, bundle, scope, manifest, scoped_evidence.build(bundle, scope))
        if (c.get('source_focus_version') != source_focus.VERSION
                or c.get('source_focus_sha256') != digest(focus)
                or c.get('execution_profile') != request['execution_profile']
                or c['reasoning'] != request['execution_profile']['reasoning']):
            raise ValueError('projector_proposal_focus_configuration')
    elif 'source_focus_json' in p:
        raise ValueError('projector_proposal_unexpected_focus')
    returned = unpack(a['provider_return'], p['provider_json'])
    response = returned['result']; raw_output = response['text']
    if (returned['job_id'] != a['job_id'] or returned['attempt_id'] != a['attempt_id']
            or returned['config_sha256'] != digest(c) or response['provider'] != c['provider']
            or response['model'] != c['model'] or response['usage'] != a['usage']
            or response['elapsed_seconds'] != a['model_elapsed_seconds']):
        raise ValueError('projector_proposal_provider_binding')
    # Captured prompt, wire schema and request are bound to the actual return,
    # not rebuilt using today's prompt. No arbitrary archived code is executed.
    raw_pins = {pin['path']: pin for pin in returned['raw_artifacts']}
    directory = Path(a['provider_return']['path']).parent
    if set(p['captured']) != {'input.txt', 'output-schema.json', 'request.json'}:
        raise ValueError('projector_proposal_capture_shape')
    for name, text in p['captured'].items():
        pin = raw_pins.get(str(directory / name))
        if pin is None or sha(text.encode()) != pin['sha256'] or len(text.encode()) != pin['bytes']:
            raise ValueError('projector_proposal_capture_pin')
    schema = json.loads(p['captured']['output-schema.json'])
    submitted = json.loads(p['captured']['request.json'])
    if (sha(p['captured']['input.txt'].encode()) != c['prompt_sha256'] or digest(schema) != c['schema_sha256']
            or submitted['config'] != c or submitted['job_id'] != a['job_id']
            or submitted['attempt_id'] != a['attempt_id']):
        raise ValueError('projector_proposal_capture_identity')
    keys = {k for k in source_projector.RESULT_PINS + ['diagnostic'] if k in a}
    if set(p['artifacts']) != keys:
        raise ValueError('projector_proposal_terminal_artifacts')
    artifacts = {k: unpack(a[k], p['artifacts'][k]) for k in keys}
    if focus is not None and artifacts.get('source_focus_inventory') != source_focus.inventory(focus):
        raise ValueError('projector_proposal_focus_inventory_changed')
    model = source_projector.decode_output(raw_output)
    if artifacts.get('model_graph') != model or artifacts.get('native_input_graph') != projection_binding.native_graph(model):
        raise ValueError('projector_proposal_raw_graph_changed')
    native = artifacts['native_input_graph']
    extraction = None
    if a['outcome'] == producer.INVALID_OUTCOME and a.get('error_code') == producer.ERROR_PREFIX + '_schema_invalid':
        if a['state'] != 'quarantined':
            raise ValueError('projector_proposal_failure_state')
        try:
            source_projector.parse_output(canonical(native), graph_schema=graph_schema)
        except ValidationError as exc:
            details = [dict(location=list(e['loc']), type=e['type']) for e in exc.errors(include_input=False)]
            expected = dict(error_code=producer.ERROR_PREFIX + '_schema_invalid', details=details, exception_class='ValidationError')
            if artifacts['diagnostic'] != expected or 'graph' in artifacts:
                raise ValueError('projector_proposal_failure_replay')
        else:
            raise ValueError('projector_proposal_failure_not_reproduced')
        validation = dict(valid=False, issues=[dict(path='/run', code='projector_schema_invalid')],
                          normalized={}, resolved_evidence=[])
    elif a['outcome'] == 'graph_drafted_pending_semantic_review':
        source_projector.parse_output(canonical(native), graph_schema=graph_schema)
        interface = dict(valid=True, issues=[dict(location=list(e.absolute_path), validator=e.validator)
            for e in Draft202012Validator(schema).iter_errors(model)])
        interface['valid'] = not interface['issues']
        if interface != artifacts['interface_validation']:
            raise ValueError('projector_proposal_interface_replay')
        _, mv = reviewed_proposals.validate_graph(native, bundle, scope, manifest, image_capture=capture,
            allowed_contracts=(graph_schema,), consistency_version=c.get('consistency_version'))
        if c.get('evidence_transport') == 'source_catalog':
            mv['validation_scope'] = 'native_scientific_payload_before_source_id_compilation'
            catalog = artifacts['source_catalog']
            if digest(catalog) != c['source_catalog_sha256']:
                raise ValueError('projector_proposal_catalog_pin')
            if (('source_catalog_version' in request or catalog.get('schema')==scoped_evidence.LINE_VERSION)
                    and request.get('source_catalog_version')!=catalog.get('schema')):
                raise ValueError('projector_proposal_catalog_version')
            binding = projection_binding.compile_catalog_bindings(model, bundle, scope, manifest, catalog)
        else:
            binding = projection_binding.compile_bindings(model, bundle, scope, manifest)
        extraction = parse_extraction(binding['graph'])
        _, validation = reviewed_proposals.validate_graph(extraction.model_dump(), bundle, scope, manifest, image_capture=capture,
            allowed_contracts=(graph_schema,), consistency_version=c.get('consistency_version'))
        if (mv != artifacts['model_validation'] or binding != artifacts['binding']
                or extraction.model_dump() != artifacts['graph'] or validation != artifacts['validation']
                or not binding['scientific_payload_unchanged']
                or projection_binding.scientific_payload(native) != projection_binding.scientific_payload(binding['graph'])):
            raise ValueError('projector_proposal_compiler_replay')
        valid = validation['valid'] and not binding['holds'] and interface['valid']
        if (a['deterministic_validation_valid'] != valid or a['state'] != ('succeeded' if valid else 'quarantined')
                or a['result_count'] != len(extraction.results) or a['unresolved_binding_holds'] != len(binding['holds'])):
            raise ValueError('projector_proposal_terminal_outcome')
        if focus is not None and artifacts.get('source_focus_mapping') != source_focus.mapping(focus, extraction.model_dump()):
            raise ValueError('projector_proposal_focus_mapping_changed')
        validation = deepcopy(validation)
        validation['issues'] += [dict(path=i['path'], code='source_binding_' + i['code']) for i in binding['holds']]
        validation['issues'] += [dict(path='/' + '/'.join(map(str, i['location'])),
            code='provider_interface_' + i['validator']) for i in interface['issues']]
    else:
        # Unknown dispatch/completion and partial local failures remain original
        # queue attempts. This adapter never fabricates a completed graph.
        raise ValueError('projector_proposal_unsupported_terminal_outcome')
    extra, omissions = _findings(review_findings, bundle, p['terminal_pin'],
        extraction.model_dump() if extraction else None, scope, manifest)
    validation['issues'] += extra
    validation['valid'] = not validation['issues']
    result = dict(schema=FORMAT, job_id=a['job_id'], work_id=bundle.work_id,
        bundle_sha256=digest(bundle.model_dump()), state='succeeded' if validation['valid'] else 'quarantined',
        config=dict(workflow=WORKFLOW, output_format=FORMAT, provider=c['provider'], model=c['model']),
        raw_output_sha256=sha(raw_output.encode()), projector_provenance=deepcopy(provenance),
        graph_authorship=c['model'], graph_transformation='deterministic_evidence_metadata_only',
        validation=validation, review_findings=deepcopy(review_findings),
        paper_review=dict(scope_review_complete=False, source_completeness_findings=omissions,
            coverage_hash=manifest['coverage_hash'], independent_review=False),
        paper_completed=False, scientific_acceptance=False, ml_training_eligible=False, production_writes=False)
    if expected_identity is not None:
        result['provider_model_identity'] = deepcopy(expected_identity)
    if extraction is not None:
        result['extraction'] = extraction.model_dump()
    if focus is not None:
        result['paper_review']['source_focus'] = dict(inventory=deepcopy(artifacts['source_focus_inventory']),
            mapping=deepcopy(artifacts.get('source_focus_mapping')), scientific_mapping_reviewed=False)
    return result


def build(queue_root, job_id, *, review_findings=None):
    """Read-only capture; it does not instantiate a worker or initialize a queue."""
    root = Path(queue_root).resolve()
    with sqlite3.connect((root / 'queue.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        value = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        attempts = db.execute('SELECT * FROM attempts WHERE job_id=? ORDER BY ordinal', (job_id,)).fetchall()
    if value is None:
        raise ValueError('projector_proposal_unknown_job')
    job = dict(value); job['config'] = json.loads(job['config_json'])
    if (job['state'] not in {'succeeded', 'quarantined'} or job['max_attempts'] != 1
            or job['attempts'] != 1 or len(attempts) != 1 or attempts[0]['finished_at'] is None
            or attempts[0]['status'] != job['state'] or attempts[0]['receipt_hash'] != job['result_hash']):
        raise ValueError('projector_proposal_terminal_attempt_required')
    from . import production_tc, finite_stage
    c = job['config']
    producer = production_tc if c.get('workflow') == production_tc.WORKFLOW else source_projector
    a = finite_stage.existing(job, producer)
    if 'provider_return' not in a:
        raise ValueError('projector_proposal_verified_provider_return_required')
    if a['attempt_id'] != attempts[0]['id'] or a['work_id'] != job['work_id'] or a['bundle_sha256'] != job['bundle_hash']:
        raise ValueError('projector_proposal_queue_identity')
    request = json.loads(reader.checked(c['request']).read_bytes())
    projector_request = request['projector_input'] if producer is production_tc else None
    if projector_request:
        request = json.loads(reader.checked(projector_request).read_bytes())
    scope = json.loads(reader.checked(request['scope']).read_bytes())
    preflight, bundle, _ = reader.source_input(scope['preflight'])
    manifest = json.loads(reader.checked(request['coverage']).read_bytes())
    for row in manifest['visuals'] + manifest['dependencies']:
        for pin in row['evidence']: reader.checked(pin)
    for row in manifest['assertions']:
        if row['visual']: reader.checked(row['visual']['image'])
    directory = Path(a['provider_return']['path']).parent
    p = dict(terminal_pin=reader.reference(job['result_path']), terminal_json=_text(job['result_path']),
        config=c, request_json=_text(reader.checked(c['request'])), scope_json=_text(reader.checked(request['scope'])),
        coverage_json=_text(reader.checked(request['coverage'])), preflight_json=_text(reader.checked(scope['preflight'])),
        provider_json=_text(reader.checked(a['provider_return'])),
        captured={n:_text(directory / n) for n in ['input.txt','output-schema.json','request.json']},
        artifacts={k:_text(reader.checked(a[k])) for k in source_projector.RESULT_PINS + ['diagnostic'] if k in a})
    if projector_request:
        p['projector_request_json'] = _text(reader.checked(projector_request))
    if scope['image_capture']:
        p['image_capture_json'] = _text(reader.checked(scope['image_capture']))
    if request['schema'] == source_projector.FOCUSED_INPUT_SCHEMA:
        p['source_focus_json'] = _text(reader.checked(request['source_focus']))
    findings = None if review_findings is None else dict(pin=reader.reference(review_findings), text=_text(review_findings))
    receipt = make_receipt(bundle, p, findings)
    from .proposals import RELATION_SCHEMA_VERSION, review_rows, verify_packet
    rows = {name:[] for name in projection_binding.GROUPS}
    if 'extraction' in receipt:
        rows = review_rows(parse_extraction(receipt['extraction']), receipt['validation'])
    packet = dict(schema=RELATION_SCHEMA_VERSION, run_id=digest(receipt), job_id=job_id,
        work_id=bundle.work_id, bundle_hash=digest(bundle.model_dump()), bundle=bundle.model_dump(),
        receipt=receipt, raw_output=json.loads(p['provider_json'])['result']['text'], rows=rows,
        evidence=receipt['validation']['resolved_evidence'], scientific_acceptance=False, ml_training_eligible=False)
    packet['packet_hash'] = digest(packet); verify_packet(packet)
    return packet


def verify_receipt(receipt, bundle, raw_output):
    c = receipt.get('config', {})
    if (c.get('workflow') != WORKFLOW and c.get('output_format') != FORMAT
            and receipt.get('schema') != FORMAT and 'projector_provenance' not in receipt):
        return
    rebuilt = make_receipt(bundle, receipt['projector_provenance'], receipt['review_findings'])
    if canonical(rebuilt) != canonical(receipt) or sha(raw_output.encode()) != rebuilt['raw_output_sha256']:
        raise ValueError('projector_proposal_receipt_replay')


def ingest_local(packet, root):
    from .proposals import ProposalDatabase, require_ingest_enabled, verify_packet
    require_ingest_enabled(Path(root) / 'proposals.sqlite3')
    verify_packet(packet)
    if packet['receipt'].get('config', {}).get('workflow') != WORKFLOW:
        raise ValueError('projector_proposal_wrong_workflow')
    return ProposalDatabase(Path(root)).ingest(packet)
