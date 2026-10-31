"""Compact source census using the existing durable single-attempt lifecycle."""
from collections import Counter
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import tiktoken

from .. import finite_stage, paper_coverage, reviewed_reader as reader, scoped_evidence, source_projector
from ..contract import canonical, digest
from ..evidence import selected_quotes
from ..sources import sha
from ..validation import resolve_quote
from .literals import VERSION as LITERAL_RESOLVER_VERSION, resolve_literal

WORKFLOW = 'source_census_v1'
INPUT_SCHEMA = 'materials-source-census-input/1'
OUTPUT_SCHEMA = 'materials-source-census/1'
ATTEMPT_SCHEMA = 'materials-source-census-attempt/1'
ATTEMPTS_DIRECTORY = 'census-attempts'
ERROR_PREFIX = 'source_census'
INVALID_OUTCOME = 'source_census_not_validated'
PROVENANCE = dict(census_authorship='gpt-6-luna', scientific_relationships_resolved=False)
RESULT_PINS = ['model_census', 'census_validation', 'source_catalog']
INSTRUCTION = Path(__file__).with_name('instruction.txt')
MAX_TARGET_UNITS = 64
MAX_INPUT_TOKENS = 40000


def implementation():
    return source_projector.implementation() + [reader.reference(path) for path in
        [Path(__file__), INSTRUCTION, Path(__file__).with_name('__init__.py'),
         Path(__file__).with_name('literals.py')]]


def output_schema(catalog):
    target = [key for key, span in catalog['spans'].items() if span['role'] == 'target']
    string = dict(type='string', minLength=1)
    nullable = dict(anyOf=[string, dict(type='null')])
    def occurrence(categories, numeric):
        return dict(type='object', additionalProperties=False,
            required=['witness_ids', 'quote', 'value_raw', 'category', 'description'], properties=dict(
                witness_ids=dict(type='array', minItems=1, maxItems=4,
                    items=dict(type='string', enum=list(catalog['spans']))),
                quote=dict(type='string', minLength=1, maxLength=1800),
                value_raw=string if numeric else nullable,
                category=dict(type='string', enum=categories),
                description=dict(type='string', minLength=1, maxLength=400)))
    def decision(status, minimum, maximum):
        return dict(type='object', additionalProperties=False, required=['disposition', 'occurrences', 'note'],
            properties=dict(disposition=dict(type='string', enum=[status]),
                occurrences=dict(type='array', minItems=minimum, maxItems=maximum, items={'$ref': '#/$defs/Occurrence'}),
                note=dict(type='string', minLength=1, maxLength=300)))
    return dict(type='object', additionalProperties=False, required=['schema_version', 'units', 'limitations'],
        properties=dict(schema_version=dict(type='string', const=OUTPUT_SCHEMA),
            units=dict(type='object', additionalProperties=False, required=target,
                properties={key: {'$ref': '#/$defs/Decision'} for key in target}),
            limitations=dict(type='array', maxItems=20, items=string)),
        **{'$defs': dict(Occurrence=dict(anyOf=[occurrence(['reported_result', 'comparison'], True),
            occurrence(['non_detection', 'figure_only', 'uncertain'], False)]),
            Decision=dict(anyOf=[decision('has_results', 1, 64), decision('no_result', 0, 0),
                decision('unresolved', 0, 64)]))})


def prepare(path):
    path = Path(path).resolve()
    request = json.loads(path.read_bytes())
    if not isinstance(request, dict) or set(request) != {'schema', 'scope', 'coverage'} or request['schema'] != INPUT_SCHEMA:
        raise ValueError('census_input_shape')
    prepared = reader.prepare_scope(reader.checked(request['scope']))
    scope = prepared['source_scope']
    if scope['image_capture'] is not None:
        raise ValueError('census_text_only_no_image_claim')
    _, bundle, _ = reader.source_input(scope['preflight'])
    coverage = json.loads(reader.checked(request['coverage']).read_bytes())
    paper_coverage.verify(coverage, bundle)
    if coverage['source']['preflight'] != scope['preflight']:
        raise ValueError('census_coverage_source_mismatch')
    catalog = scoped_evidence.build(bundle, scope)
    target = [key for key, span in catalog['spans'].items() if span['role'] == 'target']
    if not 0 < len(target) <= MAX_TARGET_UNITS:
        raise ValueError('census_unit_budget_exceeded')
    for span in catalog['spans'].values():
        if not paper_coverage.published(dict(block_id=span['block_id'], start_char=span['start_char'],
                end_char=span['end_char'], quote=span['text']), coverage, bundle):
            raise ValueError('census_unit_not_published')
    # Render neutral original units only, never coverage assertions or references.
    units = [dict(id=key, role=span['role'], text=span['text']) for key, span in catalog['spans'].items()]
    prompt = INSTRUCTION.read_text() + '\nWork ID: ' + bundle.work_id + '\nORIGINAL SOURCE UNITS\n' + canonical(units)
    schema = output_schema(catalog)
    tokens = len(tiktoken.get_encoding('cl100k_base').encode(prompt + canonical(schema), disallowed_special=()))
    if tokens > MAX_INPUT_TOKENS:
        raise ValueError('census_input_budget_exceeded')
    pins = [reader.reference(path), request['scope'], request['coverage'], *prepared['input_pins']]
    return dict(work_id=bundle.work_id, bundle_sha256=digest(bundle.model_dump()),
        scope=scope, bundle=bundle, coverage=coverage, source_catalog=catalog, targets=target,
        schema=schema, prompt=prompt, input_tokens_estimate=tokens,
        input_pins=list({pin['path']: pin for pin in pins}.values()))


def configuration(prepared):
    return dict(workflow=WORKFLOW, provider='codex', model='gpt-6-luna', reasoning='medium',
        timeout_seconds=900, max_input_tokens=MAX_INPUT_TOKENS, automatic_attempts=1,
        request=prepared['input_pins'][0], input_pins=prepared['input_pins'],
        prompt_sha256=sha(prepared['prompt'].encode()), schema_sha256=digest(prepared['schema']),
        source_catalog_sha256=digest(prepared['source_catalog']), implementation=implementation(),
        literal_resolver_version=LITERAL_RESOLVER_VERSION,
        output_kind='source_occurrences_pending_context_resolution', scientific_acceptance=False)


def resolve_occurrence(p, owner, occurrence):
    ids = occurrence['witness_ids']
    if owner not in ids:
        raise ValueError('census_owner_witness_missing')
    spans = p['source_catalog']['spans']
    if owner not in p['targets']:
        raise ValueError('census_owner_not_target')
    candidates = []
    for selected in selected_quotes(p['source_catalog'], ids):
        try:
            a, z = resolve_quote(selected['quote'], occurrence['quote'])
        except ValueError:
            continue
        anchor = dict(block_id=selected['block_id'], start_char=selected['start_char'] + a,
            end_char=selected['start_char'] + z, quote=selected['quote'][a:z])
        if not paper_coverage.published(anchor, p['coverage'], p['bundle']):
            continue
        raw = occurrence['value_raw']
        if raw is not None:
            try:
                start, end = resolve_literal(anchor['quote'], raw)
            except ValueError:
                continue
            value_anchor = dict(block_id=anchor['block_id'], start_char=anchor['start_char'] + start,
                end_char=anchor['start_char'] + end, quote=anchor['quote'][start:end])
            owner_start = value_anchor['start_char']
        else:
            value_anchor = None
            owner_start = anchor['start_char']
        unit = spans[owner]
        if anchor['block_id'] == unit['block_id'] and unit['start_char'] <= owner_start < unit['end_char']:
            candidates.append(dict(anchor=anchor, value_anchor=value_anchor))
    if len(candidates) != 1:
        raise ValueError('census_occurrence_unresolved_or_wrong_owner')
    return candidates[0]


def evaluate(p, text, directory, result):
    returned = source_projector.decode_output(text)
    reader.put(directory / 'model-census.json', returned)
    reader.put(directory / 'source-catalog.json', p['source_catalog'])
    result.update(model_census=reader.reference(directory / 'model-census.json'),
        source_catalog=reader.reference(directory / 'source-catalog.json'))
    issues = [dict(location=list(error.absolute_path), validator=error.validator, code='census_response_schema')
        for error in Draft202012Validator(p['schema']).iter_errors(returned)]
    rows = []
    unresolved = []
    seen = set()
    if not issues:
        for owner in p['targets']:
            decision = returned['units'][owner]
            if decision['disposition'] == 'unresolved':
                unresolved.append(owner)
            for index, item in enumerate(decision['occurrences']):
                identity = f'{owner}:{index + 1}'
                row = dict(id=identity, owner=owner, model_occurrence=item, resolved=None,
                    holds=[], scientific_acceptance=False, scientific_relationships_resolved=False)
                try:
                    row['resolved'] = resolve_occurrence(p, owner, item)
                    key = digest(dict(anchor=row['resolved']['anchor'], value_anchor=row['resolved']['value_anchor']))
                    if key in seen:
                        row['holds'].append('census_duplicate_source_occurrence')
                    seen.add(key)
                except ValueError as error:
                    row['holds'].append(str(error))
                rows.append(row)
    observed = returned.get('units', {}) if isinstance(returned, dict) else {}
    observed = observed if isinstance(observed, dict) else {}
    held = sum(bool(row['holds']) for row in rows)
    complete = not issues
    valid = complete and not held and not unresolved
    report = dict(schema='materials-source-census-validation/1', target_units=len(p['targets']),
        literal_resolver_version=LITERAL_RESOLVER_VERSION,
        accounted_target_units=len(set(observed) & set(p['targets'])),
        missing_units=sorted(set(p['targets']) - set(observed)), extra_units=sorted(set(observed) - set(p['targets'])),
        schema_issues=issues, unresolved_units=unresolved, held_occurrences=held, occurrences=rows,
        model_disposition_counts=dict(Counter(row['disposition'] for row in observed.values())) if complete else {},
        complete_unit_accounting=complete, deterministic_validation_valid=valid,
        source_completeness_established=False, scientific_acceptance=False, proposal_generated=False,
        paper_completed=False, ml_training_eligible=False)
    reader.put(directory / 'census-validation.json', report)
    result.update(census_validation=reader.reference(directory / 'census-validation.json'),
        state='succeeded' if valid else 'quarantined', outcome='census_recorded_pending_scientific_review',
        target_units=len(p['targets']), complete_unit_accounting=complete,
        occurrence_count=len(rows), held_occurrences=held, unresolved_units=len(unresolved),
        deterministic_validation_valid=valid, source_completeness_established=False)


def enqueue(store, path):
    store._require_dispatch_enabled()
    prepared = prepare(path)
    return store.enqueue(work_id=prepared['work_id'], bundle_hash=prepared['bundle_sha256'],
        config=configuration(prepared), max_attempts=1)


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
