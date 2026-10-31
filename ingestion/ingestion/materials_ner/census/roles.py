"""Source-only role decisions, isolated from census labels and graph assembly."""
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import tiktoken

from . import stage as census
from .literals import resolve_literal
from .. import finite_stage, paper_coverage, reviewed_reader as reader, source_projector
from ..contract import canonical, digest
from ..evidence import selected_quotes
from ..sources import sha
from ..validation import resolve_quote

WORKFLOW = 'source_roles_v1'
INPUT_SCHEMA = 'materials-source-roles-input/1'
OUTPUT_SCHEMA = 'materials-source-roles/1'
COMPACT_INPUT_SCHEMA = 'materials-source-roles-input/2'
COMPACT_OUTPUT_SCHEMA = 'materials-source-roles/2'
PROFILED_INPUT_SCHEMA = 'materials-source-roles-input/3'
EXECUTION_PROFILE_SCHEMA = 'materials-source-roles-execution/1'
ATTEMPT_SCHEMA = 'materials-source-roles-attempt/1'
ATTEMPTS_DIRECTORY = 'role-attempts'
ERROR_PREFIX = 'source_roles'
INVALID_OUTCOME = 'source_roles_not_validated'
PROVENANCE = dict(role_authorship='gpt-6-luna', scientific_relationships_resolved=False)
RESULT_PINS = ['model_roles', 'role_validation', 'source_catalog']
INSTRUCTION = Path(__file__).with_name('roles.txt')
COMPACT_INSTRUCTION = Path(__file__).with_name('roles_v2.txt')
MAX_OCCURRENCES = 64
MAX_COMPACT_OCCURRENCES = 8
MAX_INPUT_TOKENS = 40000
ROLES = ['property_result', 'sample_descriptor', 'measurement_condition', 'preparation_condition',
    'extrapolation_target', 'behavior_window', 'model_parameter', 'qualitative_statement',
    'symbolic_relationship', 'non_detection', 'unresolved']


def implementation():
    return census.implementation() + [reader.reference(path) for path in
        [Path(__file__), INSTRUCTION, COMPACT_INSTRUCTION]]


def output_schema(catalog, occurrences, *, interface_version=1):
    if interface_version == 2:
        return compact_schema(catalog, occurrences)
    string = dict(type='string', minLength=1)
    nullable = dict(anyOf=[string, dict(type='null')])
    decision = dict(type='object', additionalProperties=False,
        required=['role', 'origin', 'basis', 'quantity_raw', 'subject_raw', 'evidence', 'note'],
        properties=dict(role=dict(type='string', enum=ROLES),
            origin=dict(type='string', enum=['current_work', 'cited_work', 'unspecified']),
            basis=dict(type='string', enum=['measured', 'fitted', 'extrapolated', 'computed', 'derived', 'assumed', 'unspecified']),
            quantity_raw=nullable, subject_raw=nullable,
            evidence=dict(type='array', minItems=1, maxItems=4, items=dict(type='object',
                additionalProperties=False, required=['witness_ids', 'quote'], properties=dict(
                    witness_ids=dict(type='array', minItems=1, maxItems=4,
                        items=dict(type='string', enum=list(catalog['spans']))),
                    quote=dict(type='string', minLength=1, maxLength=2200)))),
            note=dict(type='string', minLength=1, maxLength=500)))
    return dict(type='object', additionalProperties=False, required=['schema_version', 'decisions', 'limitations'],
        properties=dict(schema_version=dict(type='string', const=OUTPUT_SCHEMA),
            decisions=dict(type='object', additionalProperties=False, required=list(occurrences),
                properties={key: {'$ref': '#/$defs/Decision'} for key in occurrences}),
            limitations=dict(type='array', maxItems=20, items=string)), **{'$defs': dict(Decision=decision)})


def compact_schema(catalog, occurrences):
    """No source retyping; basis is null when its role makes it inapplicable."""
    basis_roles = {'property_result', 'sample_descriptor', 'model_parameter', 'non_detection'}
    def decision(allowed_roles, with_basis):
        return dict(type='object', additionalProperties=False,
            required=['role', 'origin', 'basis', 'witness_ids', 'note'], properties=dict(
                role=dict(type='string', enum=allowed_roles),
                origin=dict(type='string', enum=['current_work', 'cited_work', 'unspecified']),
                basis=dict(type='string', enum=['measured', 'fitted', 'extrapolated', 'computed',
                    'derived', 'assumed', 'unspecified']) if with_basis else dict(type='null'),
                witness_ids=dict(type='array', minItems=1, maxItems=8,
                    items=dict(type='string', enum=list(catalog['spans']))),
                note=dict(type='string', minLength=1, maxLength=280)))
    return dict(type='object', additionalProperties=False, required=['schema_version', 'decisions', 'limitations'],
        properties=dict(schema_version=dict(type='string', const=COMPACT_OUTPUT_SCHEMA),
            decisions=dict(type='object', additionalProperties=False, required=list(occurrences),
                properties={key: {'$ref': '#/$defs/Decision'} for key in occurrences}),
            limitations=dict(type='array', maxItems=20, items=dict(type='string', minLength=1))),
        **{'$defs': dict(Decision=dict(anyOf=[
            decision([x for x in ROLES if x in basis_roles], True),
            decision([x for x in ROLES if x not in basis_roles], False)]))})


def prepare(path):
    path = Path(path).resolve()
    request = json.loads(path.read_bytes())
    if not isinstance(request, dict) or request.get('schema') not in [INPUT_SCHEMA, COMPACT_INPUT_SCHEMA, PROFILED_INPUT_SCHEMA]:
        raise ValueError('roles_input_shape')
    version = 1 if request['schema'] == INPUT_SCHEMA else 2
    profiled = request['schema'] == PROFILED_INPUT_SCHEMA
    keys = {'schema', 'census_request', 'census_receipt'} | ({'occurrence_ids'} if version == 2 else set())
    if profiled:
        keys.add('execution_profile')
    if set(request) != keys:
        raise ValueError('roles_input_shape')
    profile = request.get('execution_profile')
    if profiled and (not isinstance(profile, dict) or set(profile) != {'schema', 'model', 'reasoning'}
            or profile['schema'] != EXECUTION_PROFILE_SCHEMA or profile['model'] != 'gpt-6-luna'
            or profile['reasoning'] not in ['medium', 'high']):
        raise ValueError('roles_execution_profile_invalid')
    p = census.prepare(reader.checked(request['census_request']))
    receipt = json.loads(reader.checked(request['census_receipt']).read_bytes())
    if (receipt['schema'] != census.ATTEMPT_SCHEMA or receipt['state'] not in {'succeeded', 'quarantined'}
            or receipt['work_id'] != p['work_id'] or receipt['bundle_sha256'] != p['bundle_sha256']):
        raise ValueError('roles_census_identity')
    marker = json.loads(reader.checked(receipt['provider_return']).read_bytes())
    if (any(marker[k] != receipt[k] for k in ['job_id', 'attempt_id', 'config_sha256'])
            or marker['result']['provider'] != 'codex' or marker['result']['model'] != 'gpt-6-luna'):
        raise ValueError('roles_census_provider_identity')
    for pin in marker['raw_artifacts']:
        reader.checked(pin)
    returned = json.loads(reader.checked(receipt['model_census']).read_bytes())
    if returned != source_projector.decode_output(marker['result']['text']):
        raise ValueError('roles_census_return_changed')
    if json.loads(reader.checked(receipt['source_catalog']).read_bytes()) != p['source_catalog']:
        raise ValueError('roles_census_source_catalog_changed')
    Draft202012Validator(p['schema']).validate(returned)
    occurrences = {}
    seen = set()
    for owner in p['targets']:
        for index, item in enumerate(returned['units'][owner]['occurrences']):
            resolved = census.resolve_occurrence(p, owner, item)
            identity = digest(resolved)
            if identity in seen:
                raise ValueError('roles_duplicate_source_occurrence')
            seen.add(identity)
            # This whitelist deliberately withholds census categories/descriptions.
            occurrences[f'{owner}:{index + 1}'] = dict(owner=owner, value_raw=item['value_raw'],
                quote=resolved['anchor']['quote'], resolved=resolved)
    all_ids = list(occurrences)
    if version == 2:
        ids = request['occurrence_ids']
        if (not isinstance(ids, list) or not 0 < len(ids) <= MAX_COMPACT_OCCURRENCES
                or any(not isinstance(key, str) for key in ids) or len(set(ids)) != len(ids)
                or any(key not in occurrences for key in ids)):
            raise ValueError('roles_occurrence_selection_invalid')
        occurrences = {key: value for key, value in occurrences.items() if key in ids}
    elif not 0 < len(occurrences) <= MAX_OCCURRENCES:
        raise ValueError('roles_occurrence_budget_exceeded')
    catalog = p['source_catalog']
    units = [dict(id=key, role=value['role'], text=value['text']) for key, value in catalog['spans'].items()]
    neutral = {key: {k: value[k] for k in ['owner', 'value_raw', 'quote']} for key, value in occurrences.items()}
    schema = output_schema(catalog, occurrences, interface_version=version)
    instruction = COMPACT_INSTRUCTION if version == 2 else INSTRUCTION
    prompt = instruction.read_text() + '\nWork ID: ' + p['work_id'] + '\nORIGINAL SOURCE UNITS\n' + canonical(units)
    prompt += '\nSOURCE OCCURRENCES\n' + canonical(neutral)
    tokens = len(tiktoken.get_encoding('cl100k_base').encode(prompt + canonical(schema), disallowed_special=()))
    if tokens > MAX_INPUT_TOKENS:
        raise ValueError('roles_input_budget_exceeded')
    pins = [reader.reference(path), request['census_receipt'], *p['input_pins'],
        receipt['provider_return'], receipt['model_census'], receipt['source_catalog'], *marker['raw_artifacts']]
    return {**p, 'schema': schema, 'prompt': prompt, 'input_tokens_estimate': tokens,
        'occurrences': occurrences, 'census_receipt': receipt,
        'interface_version': version, 'all_occurrence_ids': all_ids,
        'execution_profile': profile,
        'unselected_occurrence_ids': [key for key in all_ids if key not in occurrences],
        'input_pins': list({pin['path']: pin for pin in pins}.values())}


def configuration(p):
    profile = p['execution_profile']
    return dict(workflow=WORKFLOW, provider='codex', model='gpt-6-luna',
        reasoning=profile['reasoning'] if profile else 'medium',
        timeout_seconds=900, max_input_tokens=MAX_INPUT_TOKENS, automatic_attempts=1,
        request=p['input_pins'][0], input_pins=p['input_pins'],
        prompt_sha256=sha(p['prompt'].encode()), schema_sha256=digest(p['schema']),
        source_catalog_sha256=digest(p['source_catalog']), implementation=implementation(),
        interface_version=p['interface_version'], selected_occurrence_ids=list(p['occurrences']),
        total_source_occurrences=len(p['all_occurrence_ids']),
        output_kind='source_roles_pending_scientific_review', scientific_acceptance=False,
        **({'execution_profile': profile} if profile else {}))


def resolve_support(p, decision, occurrence):
    if p.get('interface_version', 1) == 2:
        selected = selected_quotes(p['source_catalog'], decision['witness_ids'])
        anchors = [{key: span[key] for key in ['block_id', 'start_char', 'end_char', 'quote']}
            for span in selected]
        if not all(paper_coverage.published(a, p['coverage'], p['bundle']) for a in anchors):
            raise ValueError('roles_support_not_published')
        locked = occurrence['resolved']['value_anchor'] or occurrence['resolved']['anchor']
        if not any(a['block_id'] == locked['block_id'] and a['start_char'] <= locked['start_char']
                and a['end_char'] >= locked['end_char'] for a in anchors):
            raise ValueError('roles_evidence_does_not_cover_occurrence')
        return anchors
    anchors = []
    for evidence in decision['evidence']:
        candidates = []
        for selected in selected_quotes(p['source_catalog'], evidence['witness_ids']):
            try:
                a, z = resolve_quote(selected['quote'], evidence['quote'])
            except ValueError:
                continue
            anchor = dict(block_id=selected['block_id'], start_char=selected['start_char'] + a,
                end_char=selected['start_char'] + z, quote=selected['quote'][a:z])
            if paper_coverage.published(anchor, p['coverage'], p['bundle']):
                candidates.append(anchor)
        if len(candidates) != 1:
            raise ValueError('roles_evidence_unresolved')
        anchors.append(candidates[0])
    locked = occurrence['resolved']['value_anchor'] or occurrence['resolved']['anchor']
    if not any(a['block_id'] == locked['block_id'] and a['start_char'] <= locked['start_char']
            and a['end_char'] >= locked['end_char'] for a in anchors):
        raise ValueError('roles_evidence_does_not_cover_occurrence')
    for field in ['quantity_raw', 'subject_raw']:
        raw = decision[field]
        if raw is None:
            continue
        matches = []
        for a in anchors:
            try:
                matches.append(resolve_literal(a['quote'], raw))
            except ValueError:
                pass
        if not matches:
            raise ValueError('roles_' + field + '_not_in_evidence')
    return anchors


def evaluate(p, text, directory, result):
    body = source_projector.decode_output(text)
    reader.put(directory / 'model-roles.json', body)
    reader.put(directory / 'source-catalog.json', p['source_catalog'])
    result.update(model_roles=reader.reference(directory / 'model-roles.json'),
        source_catalog=reader.reference(directory / 'source-catalog.json'))
    issues = [dict(location=list(e.absolute_path), validator=e.validator, code='roles_response_schema')
        for e in Draft202012Validator(p['schema']).iter_errors(body)]
    rows = []
    if not issues:
        for key, occurrence in p['occurrences'].items():
            decision = body['decisions'][key]
            row = dict(id=key, model_decision=decision, source_occurrence=occurrence,
                evidence=[], holds=[], scientific_acceptance=False)
            try:
                row['evidence'] = resolve_support(p, decision, occurrence)
            except ValueError as error:
                row['holds'].append(str(error))
            if decision['role'] == 'unresolved':
                row['holds'].append('roles_unresolved')
            rows.append(row)
    held = sum(bool(row['holds']) for row in rows)
    valid = not issues and not held
    report = dict(schema='materials-source-roles-validation/1', schema_issues=issues,
        interface_version=p['interface_version'], source_occurrence_count=len(p['all_occurrence_ids']),
        unselected_occurrence_ids=p['unselected_occurrence_ids'],
        occurrence_count=len(p['occurrences']), decisions=rows, held_decisions=held,
        deterministic_validation_valid=valid, scientific_roles_reviewed=False,
        scientific_relationships_resolved=False, source_completeness_established=False,
        proposal_generated=False, scientific_acceptance=False, paper_completed=False, ml_training_eligible=False)
    reader.put(directory / 'role-validation.json', report)
    result.update(role_validation=reader.reference(directory / 'role-validation.json'),
        state='succeeded' if valid else 'quarantined', outcome='roles_recorded_pending_scientific_review',
        occurrence_count=len(p['occurrences']), held_decisions=held,
        interface_version=p['interface_version'], total_source_occurrences=len(p['all_occurrence_ids']),
        unselected_occurrence_ids=p['unselected_occurrence_ids'],
        deterministic_validation_valid=valid, scientific_roles_reviewed=False,
        source_completeness_established=False)


def enqueue(store, path):
    store._require_dispatch_enabled()
    p = prepare(path)
    return store.enqueue(work_id=p['work_id'], bundle_hash=p['bundle_sha256'], config=configuration(p), max_attempts=1)


def row(store, identifier):
    return finite_stage.row(store, identifier, sys.modules[__name__])


def existing(job):
    return finite_stage.existing(job, sys.modules[__name__])


def terminal(job, directory, **kwargs):
    return finite_stage.terminal(job, directory, sys.modules[__name__], **kwargs)


def recover(store, identifier):
    return finite_stage.recover(store, identifier, sys.modules[__name__])


def run(store, identifier, *, provider_override=None):
    return finite_stage.run(store, identifier, sys.modules[__name__], provider_override=provider_override)
