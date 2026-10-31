"""Finite evidence-only audit of a frozen native draft, never a repair loop.

Complete model decisions and verified source addresses are operational results.
They are not independent scientific acceptance or permission to import a graph.
"""
from collections import Counter
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import tiktoken

from . import evidence_policy as policy, finite_stage, paper_coverage, projection_binding as binding
from . import reviewed_proposals, reviewed_reader as reader, source_projector as projector
from .contract import canonical, digest, parse_extraction
from .quantities_v2 import ADDITIONS
from .sources import sha
from .validation import resolve_quote

WORKFLOW = 'assertion_audit_v1'
INPUT_SCHEMA = 'materials-assertion-audit-input/1'
ATTEMPT_SCHEMA = 'materials-assertion-audit-attempt/1'
ATTEMPTS_DIRECTORY = 'audit-attempts'
ERROR_PREFIX = 'assertion_audit'
INVALID_OUTCOME = 'assertions_not_audited'
PROVENANCE = dict(audit_authorship='gpt-6-luna', scientific_payload_changed=False,
                  verdicts_are_model_opinions=True)
RESULT_PINS = ['model_audit', 'audit_validation', 'source_catalog']
INSTRUCTION = Path(__file__).with_name('audit_protocol') / 'instruction.txt'
RELATIONSHIP_SEMANTICS = dict(context_uses=(
    'General source-supported applicability of a procedure to a state condition. '
    'This link alone does not assert that the procedure measured or determined the condition. '
    'Do not promote it into canonical measurement ownership without additional explicit source support.'))
SCOPE_NOTE = 'Existing native field obligations and supplied witnesses only; this is not a complete independent scientific claim inventory.'


def value(body, pointer):
    for key in pointer.lstrip('/').split('/'):
        body = body[int(key)] if isinstance(body, list) else body[key.replace('~1','/').replace('~0','~')]
    return body


def enumerate_targets(graph, validation):
    """Expand the shared obligations without inventing or editing candidate facts."""
    targets = []
    for group in binding.GROUPS:
        for index, entity in enumerate(graph[group]):
            stages = {'samples':['sample'], 'states':['state','pressure'], 'protocols':['protocol'],
                'results':['result','definition','qualifiers'], 'sample_relations':['sample_relation'],
                'condition_supports':['condition_support']}[group].copy()
            if group == 'results':
                if entity['quantity_kind'] in ADDITIONS: stages += ['adopted']
                if entity['cited_source_raw']: stages += ['citation']
                if entity['quantity_kind'] in policy.COMPONENT_KINDS and entity['component_raw']: stages += ['component']
                if entity['quantity_kind'] == 'unmapped': stages += ['unmapped']
                if entity['quantity_kind'] == 'non_detection': stages += ['non_detection_window','non_detection_sensitivity']
            fields = {}
            for stage in stages:
                for field in policy.required(stage, entity):
                    fields.setdefault(field, dict(coverage='exact_pointer', reasons=[]))['reasons'].append(stage)
            for field, _ in policy.raw_fields(entity):
                fields.setdefault(field, dict(coverage='self_or_ancestor', reasons=[]))['reasons'].append('verbatim_raw_string')
            for evidence in entity['evidence']:
                fields.setdefault(evidence['field'], dict(coverage='exact_pointer', reasons=[]))['reasons'].append('model_supplied_witness')
            for field, rule in sorted(fields.items()):
                full = f'/{group}/{index}' + field
                targets.append(dict(id=f'A{len(targets)+1:04}', entity_group=group, entity_id=entity['id'],
                    field=field, graph_pointer=full, candidate_value=value(entity, field), **rule,
                    current_witnesses=[e for e in entity['evidence'] if e['field']==field or
                        rule['coverage']=='self_or_ancestor' and field.startswith(e['field'].rstrip('/')+'/')],
                    current_issues=[i for i in validation['issues'] if i['path']==full]))
    return targets


def build_input(model_graph, compiled_graph, request):
    """Build from immutable source/graph pins; preparation rechecks all claims."""
    p = projector.prepare(reader.checked(request))
    compiled = json.loads(reader.checked(compiled_graph).read_bytes())
    graph = compiled['graph']
    capture = json.loads(reader.checked(p['scope']['image_capture']).read_bytes()) if p['scope']['image_capture'] else None
    _, validation = reviewed_proposals.validate_graph(graph, p['bundle'], p['scope'], p['coverage'], image_capture=capture)
    return dict(schema=INPUT_SCHEMA, model_graph=model_graph, compiled_graph=compiled_graph, request=request,
        policy_version=policy.VERSION, source_bundle_sha256=p['bundle_sha256'], targets=enumerate_targets(graph, validation),
        graph_sha256=digest(graph), scientific_payload_sha256=digest(binding.scientific_payload(graph)),
        candidates_are_not_reference_answers=True, scope=SCOPE_NOTE, relationship_semantics=RELATIONSHIP_SEMANTICS,
        new_model_calls=0, scientific_acceptance=False)


def output_schema(targets, scope):
    witness = dict(type='object', additionalProperties=False, required=['block_id','quote','context_quote'], properties=dict(
        block_id=dict(type='string', enum=sorted({p['block_id'] for p in scope['passages']})),
        quote=dict(type='string', minLength=1), context_quote=dict(type='string', minLength=1)))
    def decision(statuses, minimum):
        return dict(type='object', additionalProperties=False, required=['status','reason','witnesses'], properties=dict(
            status=dict(type='string', enum=statuses), reason=dict(type='string', minLength=1),
            witnesses=dict(type='array', minItems=minimum, items={'$ref':'#/$defs/Witness'})))
    return dict(type='object', additionalProperties=False, required=[t['id'] for t in targets],
        properties={t['id']:{'$ref':'#/$defs/Decision'} for t in targets}, **{'$defs':dict(Witness=witness,
            Decision=dict(anyOf=[decision(['supported','contradicted'], 1), decision(['insufficient_source'], 0)]))})


def prepare(path):
    from . import semantic_audit
    inp = projector.decode_output(Path(path).read_text())
    if inp.get('schema') == semantic_audit.INPUT_SCHEMA:
        return semantic_audit.prepare(path)
    return _prepare_v1(path)


def _prepare_v1(path):
    path = Path(path).resolve()
    inp = projector.decode_output(path.read_text())
    required = {'schema','model_graph','compiled_graph','request','policy_version','source_bundle_sha256','targets',
        'graph_sha256','scientific_payload_sha256','candidates_are_not_reference_answers','scope','relationship_semantics',
        'new_model_calls','scientific_acceptance'}
    if (set(inp) not in (required, required | {'semantic_correction'}) or inp['schema'] != INPUT_SCHEMA
            or inp['policy_version'] != policy.VERSION or inp['candidates_are_not_reference_answers'] is not True
            or inp['scientific_acceptance'] is not False or inp['new_model_calls'] != 0
            or inp['scope'] != SCOPE_NOTE or inp['relationship_semantics'] != RELATIONSHIP_SEMANTICS):
        raise ValueError('assertion_audit_input_shape_or_semantics')
    p = projector.prepare(reader.checked(inp['request']))
    model = projector.decode_output(reader.checked(inp['model_graph']).read_text())
    compiled = projector.decode_output(reader.checked(inp['compiled_graph']).read_text())
    graph = compiled['graph']; parse_extraction(graph)
    if (graph['schema_version'] != 'materials-ner/13' or graph['work_id'] != p['work_id']
            or inp['source_bundle_sha256'] != p['bundle_sha256'] or inp['graph_sha256'] != digest(graph)
            or compiled['source_bundle_sha256'] != p['bundle_sha256'] or compiled['scope_sha256'] != digest(p['scope'])
            or compiled['input_graph_sha256'] != digest(model) or compiled['output_graph_sha256'] != digest(graph)
            or inp['scientific_payload_sha256'] != digest(binding.scientific_payload(graph))
            or binding.scientific_payload(graph) != binding.scientific_payload(model)):
        raise ValueError('assertion_audit_source_or_candidate_identity')
    expected = build_input(inp['model_graph'], inp['compiled_graph'], inp['request'])
    if inp['targets'] != expected['targets'] or not inp['targets'] or len(inp['targets']) > 500:
        raise ValueError('assertion_audit_target_inventory_changed')
    extras = []
    if 'semantic_correction' in inp:
        c = inp['semantic_correction']
        if set(c) != {'supersedes','supporting_contract_references','targets_and_candidate_values_unchanged'} or c['targets_and_candidate_values_unchanged'] is not True:
            raise ValueError('assertion_audit_correction_shape')
        extras = [c['supersedes'], *c['supporting_contract_references']]
        for pin in extras: reader.checked(pin)
    # Previous witnesses, validator diagnoses and reference annotations are NOT
    # answers. Omit them from the auditor's prompt to reduce anchoring.
    claims = [{k:t[k] for k in ('id','entity_group','entity_id','field','graph_pointer','candidate_value')} for t in inp['targets']]
    science = binding.scientific_payload(graph)
    # Keep only entity context and work identity; extraction limitations are not source facts.
    context = {k:science[k] for k in ('work_id', *binding.GROUPS)}
    original = reader.prepare_scope(reader.checked(p['request']['scope']))['prompt'][len(reader.protocol()[0]):]
    prompt = (INSTRUCTION.read_text() + '\nRELATIONSHIP SEMANTICS\n' + canonical(RELATIONSHIP_SEMANTICS)
        + '\nUNTRUSTED CANDIDATE CONTEXT\n' + canonical(context)
        + '\nFROZEN ASSERTIONS TO AUDIT\n' + canonical(claims) + '\nORIGINAL SOURCE\n' + original)
    schema = output_schema(inp['targets'], p['scope']); Draft202012Validator.check_schema(schema)
    tokens = len(tiktoken.get_encoding('cl100k_base').encode(prompt + canonical(schema), disallowed_special=()))
    if tokens > 60000: raise ValueError('assertion_audit_input_budget_exceeded')
    pins = [reader.reference(path), inp['model_graph'], inp['compiled_graph'], *p['input_pins'], *extras]
    return dict(work_id=p['work_id'], bundle_sha256=p['bundle_sha256'], request=inp, targets=inp['targets'], graph=graph,
        bundle=p['bundle'], coverage=p['coverage'], scope=p['scope'], prompt=prompt, schema=schema,
        input_tokens_estimate=tokens, input_pins=list({pin['path']:pin for pin in pins}.values()))


def configuration(p):
    identity = digest(dict(work_id=p['work_id'], source=p['bundle_sha256'], scope=digest(p['scope']),
        scientific_payload=p['request']['scientific_payload_sha256']))
    config = dict(workflow=WORKFLOW, provider='codex', model='gpt-6-luna', reasoning='medium', timeout_seconds=900,
        max_input_tokens=60000, automatic_attempts=1, single_pass_identity=identity, request=p['input_pins'][0],
        input_pins=p['input_pins'], prompt_sha256=sha(p['prompt'].encode()), schema_sha256=digest(p['schema']),
        implementation=[*projector.implementation(), reader.reference(INSTRUCTION)], output_kind='unaudited_assertion_decisions',
        target_count=len(p['targets']), graph_schema='materials-ner/13', evidence_policy_version=policy.VERSION,
        scientific_acceptance=False)
    if 'semantic_policy_version' in p:
        config.update(semantic_policy_version=p['semantic_policy_version'], audit_mode=p['request']['mode'],
            target_manifest_sha256=p['request']['target_manifest_sha256'], output_kind='unaudited_typed_assertion_decisions')
        if p['request']['mode']=='synthetic_controls':
            config['single_pass_identity'] = digest(dict(base=identity, synthetic_controls=p['request']['controls']))
        if p.get('source_catalog'):
            config.update(evidence_transport='source_catalog',source_catalog_sha256=digest(p['source_catalog']))
    return config


def resolve_witness(witness, target, p):
    """Resolve original locations only; quoted words do not establish entailment."""
    block = next((b for b in p['bundle'].blocks if b.id == witness['block_id']), None)
    if block is None: raise ValueError('audit_witness_block_missing')
    quantity = target['entity_group']=='results' and target['field'] in {
        '/quantity','/quantity/raw','/quantity/value','/quantity/lower','/quantity/upper'}
    spans = [s for s in p['scope']['passages'] if s['block_id']==block.id and (not quantity or s['role']=='target')]
    positions = set(); ambiguous = False
    for span in spans:
        start, end = span['start_char'], span['end_char']
        try:
            left, right = resolve_quote(block.text[start:end], witness['context_quote'])
            positions.update(binding.contextual_positions(block.text, witness['quote'], start+left, start+right, target['field']))
        except ValueError as exc:
            if str(exc) == 'ambiguous_quote_locator': ambiguous = True
    if ambiguous or len(positions) != 1:
        raise ValueError('audit_witness_ambiguous' if ambiguous or len(positions)>1 else 'audit_witness_unresolved_in_scope')
    start, end = next(iter(positions))
    anchor = dict(block_id=block.id, start_char=start, end_char=end, quote=block.text[start:end])
    if not paper_coverage.published(anchor, p['coverage'], p['bundle']):
        raise ValueError('audit_witness_not_published')
    return anchor


def evaluate(p, text, directory, result):
    if 'semantic_policy_version' in p:
        from . import semantic_audit
        return semantic_audit.evaluate(p, text, directory, result)
    returned = projector.decode_output(text)
    reader.put(directory / 'model-audit.json', returned)
    result['model_audit'] = reader.reference(directory / 'model-audit.json')
    issues = [dict(location=list(e.absolute_path), code='audit_response_schema', validator=e.validator)
        for e in Draft202012Validator(p['schema']).iter_errors(returned)]
    rows = []
    if not issues:
        for target in p['targets']:
            decision = returned[target['id']]; resolved = []; holds = []
            for n, witness in enumerate(decision['witnesses']):
                try: resolved.append(resolve_witness(witness, target, p))
                except ValueError as exc: holds.append(dict(witness_index=n, code=str(exc)))
            rows.append(dict(assertion_id=target['id'], graph_pointer=target['graph_pointer'],
                model_status=decision['status'], reason=decision['reason'], resolved_witnesses=resolved, holds=holds,
                evidence_addresses_valid=not holds, semantic_verified=False))
    missing = sorted({t['id'] for t in p['targets']} - set(returned)) if isinstance(returned, dict) else [t['id'] for t in p['targets']]
    counts = dict(Counter(r['model_status'] for r in rows))
    holds = sum(len(r['holds']) for r in rows)
    valid = not issues and not holds
    report = dict(schema='materials-assertion-audit-validation/1', target_count=len(p['targets']), decisions=len(rows),
        model_status_counts=counts, missing_assertion_ids=missing, schema_issues=issues, unresolved_witnesses=holds,
        complete_decision_inventory=not issues, deterministic_validation_valid=valid, rows=rows,
        input_graph_sha256=p['request']['graph_sha256'], scientific_payload_sha256=p['request']['scientific_payload_sha256'],
        scientific_payload_changed=False, semantic_validation_qualified=False, scientific_acceptance=False,
        automatic_repairs=0, proposal_generated=False, paper_completed=False, independent_scientific_claim_inventory=False)
    reader.put(directory / 'audit-validation.json', report)
    result.update(audit_validation=reader.reference(directory / 'audit-validation.json'),
        state='succeeded' if valid else 'quarantined', outcome='audit_recorded_pending_semantic_review',
        target_count=len(p['targets']), decision_count=len(rows), model_status_counts=counts,
        complete_decision_inventory=not issues, unresolved_witnesses=holds, deterministic_validation_valid=valid,
        audit_mechanically_completed=valid, automatic_repairs=0)


def enqueue(store, path):
    store._require_dispatch_enabled()
    p = prepare(path)
    return store.enqueue(work_id=p['work_id'], bundle_hash=p['bundle_sha256'], config=configuration(p), max_attempts=1)


def row(store, identifier):
    return finite_stage.row(store, identifier, sys.modules[__name__])


def terminal(job, directory, **kwargs):
    return finite_stage.terminal(job, directory, sys.modules[__name__], **kwargs)


def recover(store, identifier):
    return finite_stage.recover(store, identifier, sys.modules[__name__])


def run(store, identifier, *, provider_override=None):
    return finite_stage.run(store, identifier, sys.modules[__name__], provider_override=provider_override)
