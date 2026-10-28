"""Opt-in source selections: copy immutable characters, never repair a response.

The model chooses result semantics. Deterministic selection preserves source
numbers and statements without claiming that the selected attribution is true.
"""
from copy import deepcopy
from typing import Literal

from pydantic import Field

from .contract import StrictModel, canonical, digest
from .sources import sha
from .evidence import source_catalog
from .inventory import strict_schema, source_text, targets
from . import typed_inventory as base, typed_inventory_v2 as previous
from .source_role_inventory import selection_catalog

VERSION = 'materials-typed-source-inventory/3'
PROJECTION = 'materials-typed-inventory-projection/3'
VALIDATION = 'materials-typed-inventory-validation/3'
RESULT_KINDS = previous.RESULT_KINDS


class NumericResult(StrictModel):
    type: Literal['numeric_result']
    sample_description: str = Field(min_length=1, max_length=1200)
    quantity_description: str = Field(min_length=1, max_length=1200)
    quantity_kind: str
    numeric_candidate_id: str
    context_span_ids: list[str] = Field(max_length=64)
    attribution: base.Attribution
    unresolved_reason: str | None


class UnvaluedResult(StrictModel):
    type: Literal['unvalued_result']
    sample_description: str = Field(min_length=1, max_length=1200)
    quantity_description: str = Field(min_length=1, max_length=1200)
    quantity_kind: str
    statement_text_id: str
    context_span_ids: list[str] = Field(max_length=64)
    attribution: base.Attribution
    value_status: Literal['explicit_non_detection', 'figure_not_digitized', 'qualitative', 'unresolved']
    unresolved_reason: str = Field(min_length=1, max_length=2000)


class TypedInventory(StrictModel):
    schema_version: Literal[VERSION]
    work_id: str
    entries: list[NumericResult | UnvaluedResult] = Field(max_length=512)
    context_assertions: list[base.Context] = Field(max_length=256)
    span_assessments: dict[str, base.SpanRead]
    unread_block_ids: list[str]
    limitations: list[str]


def catalog(bundle):
    """Existing lexical partition plus coordinate-bound numeric/unit witnesses."""
    cat = selection_catalog(bundle)
    witnesses = {k: dict(block_id=v['block_id'], start_char=v['start_char'],
        end_char=v['end_char'], quote=v['quote']) for k, v in cat['texts'].items() if v['selectable']}
    for k, v in source_catalog(bundle)['spans'].items():
        witnesses[k] = dict(block_id=v['block_id'], start_char=v['start_char'],
            end_char=v['end_char'], quote=v['text'])
    for k, v in cat['numeric_catalog']['numeric_candidates'].items():
        if not v['selectable']:
            continue
        witnesses[k] = {n: v[n] for n in ('block_id', 'start_char', 'end_char', 'quote')}
        if v['evidence'].get('unit'):
            witnesses['U' + k[1:]] = dict(v['evidence']['unit'], block_id=v['block_id'])
    return dict(cat, witness_selections=witnesses)


def output_schema(bundle=None):
    schema = strict_schema(TypedInventory)
    for name in ('NumericResult', 'UnvaluedResult'):
        schema['$defs'][name]['properties']['quantity_kind']['enum'] = RESULT_KINDS + (
            ['non_detection'] if name == 'UnvaluedResult' else [])
    if bundle is None:
        return schema
    source, cat = source_catalog(bundle), catalog(bundle)
    target = sorted(targets(source))
    schema['properties']['work_id']['enum'] = [bundle.work_id]
    schema['properties']['unread_block_ids']['items']['enum'] = list(source['blocks'])
    schema['properties']['span_assessments'] = dict(type='object', additionalProperties=False,
        properties={k: {'$ref': '#/$defs/SpanRead'} for k in target}, required=target)
    for name, field in [('NumericResult', 'context_span_ids'), ('UnvaluedResult', 'context_span_ids'),
                        ('Context', 'span_ids'), ('Attribution', 'span_ids')]:
        schema['$defs'][name]['properties'][field]['items']['enum'] = list(source['spans'])
    for name, field, ids in [
        ('NumericResult', 'numeric_candidate_id', [k for k, v in cat['numeric_catalog']['numeric_candidates'].items() if v['selectable']]),
        ('UnvaluedResult', 'statement_text_id', [k for k, v in cat['texts'].items() if v['target'] and v['selectable']])]:
        # Empty enums are invalid in provider schemas. The inspector still rejects
        # every unknown selection if a source contains no selectable occurrences.
        if ids:
            schema['$defs'][name]['properties'][field]['enum'] = ids
    return schema


def compile_selection(model, bundle):
    cat = catalog(bundle)
    entries, selections = [], []
    for i, entry in enumerate(model.entries):
        data = entry.model_dump()
        if entry.type == 'numeric_result':
            key = data.pop('numeric_candidate_id')
            row = cat['numeric_catalog']['numeric_candidates'].get(key)
            if row is None or not row['selectable']:
                raise ValueError('selected_inventory_numeric_not_selectable')
            data.update(value_raw=row['quote'], unit=row['unit_raw'],
                unit_span_ids=row['source_span_ids'] if row['unit_raw'] else [],
                source_span_ids=row['source_span_ids'])
        else:
            key = data.pop('statement_text_id')
            row = cat['texts'].get(key)
            if row is None or not row['selectable'] or not row['target']:
                raise ValueError('selected_inventory_statement_not_selectable')
            data.update(statement_raw=row['quote'], source_span_ids=row['source_span_ids'])
        entries.append(data)
        selections.append(dict(item_id=f'I{i + 1}', selection_id=key,
            location={k: row[k] for k in ('block_id', 'start_char', 'end_char', 'quote')},
            exact_original_characters=True))
    data = model.model_dump()
    data.update(schema_version=previous.VERSION, entries=entries)
    return previous.TypedInventoryV2.model_validate(data), selections


def inspect(model, bundle):
    try:
        compiled, selections = compile_selection(model, bundle)
        checked = previous.inspect(compiled, bundle)
    except (KeyError, ValueError) as exc:
        return dict(schema=VALIDATION, valid=False,
            issues=[dict(code=str(exc) if str(exc).startswith('selected_inventory_') else 'selected_inventory_compile_invalid', path='/entries')],
            input_sha256=digest(model.model_dump()), scientific_acceptance=False)
    return dict(schema=VALIDATION, valid=checked['valid'], issues=checked['issues'],
        input_sha256=digest(model.model_dump()), compiled_validation=checked,
        selections=selections, scientific_acceptance=False)


def project(model, bundle):
    checked = inspect(model, bundle)
    if not checked['valid']:
        raise ValueError('selected_inventory_not_valid')
    compiled, selections = compile_selection(model, bundle)
    inventory, proof = previous.project(compiled, bundle)
    return inventory, dict(schema=PROJECTION, input_sha256=digest(model.model_dump()),
        inventory_sha256=digest(inventory.model_dump()), validation=checked,
        compiled_inventory=compiled.model_dump(), compiled_projection=proof,
        selections=selections, original_numeric_characters_preserved=True,
        scientific_acceptance=False, ml_training_eligible=False)


def render_catalog(bundle, *, first_read=False):
    cat = catalog(bundle)
    numbers = {k: {n: v[n] for n in ('block_id', 'source_span_ids', 'quote', 'unit_raw', 'selectable', 'issues')}
        for k, v in cat['numeric_catalog']['numeric_candidates'].items()}
    texts = {k: {n: v[n] for n in ('block_id', 'source_span_ids', 'quote', 'selectable')}
        for k, v in cat['texts'].items() if v['target']}
    body = dict(numeric_candidates=numbers, target_text_selections=texts)
    if not first_read:
        # S text is already printed verbatim in SOURCE; only its positions need
        # an index here. Full catalogs remain reconstructible from the bundle.
        body['witness_selections'] = {k: v if not k.startswith('S') else
            {n: v[n] for n in ('block_id', 'start_char', 'end_char')}
            for k, v in cat['witness_selections'].items()
            if not k.startswith('T') or k in texts}
        body['span_text_location'] = 'S identifiers refer to the exact BEGIN_SPAN source text above.'
    return canonical(body)


RULES = '''Use materials-typed-source-inventory/3. Select numeric_candidate_id
for each numeric outcome and statement_text_id for each unvalued outcome. Do not
retype values or quotations: the program copies their exact original characters,
including approximation, minus signs, uncertainties, units and whitespace.
The catalog is lexical, not a result list: ticks, pressure settings, methods and
instrument limits are not outcomes. Generic method definitions belong in context
unless they assert a specific result. Inspect all original experiment context,
including column continuations and images. Select connected source context for
the specimen/run and measurement. Do not use a neighboring caption as ownership.
All inherited instructions about value_raw or statement_raw mean choosing the
source selection in this version. Classifications remain fallible proposals.
'''


def render(bundle, layout=None):
    return previous.render(bundle, layout) + '\n' + RULES + '\nSOURCE_SELECTIONS:\n' + render_catalog(bundle, first_read=True)


def verify_read(receipt, bundle):
    from .frozen_inventory import parse
    config = receipt['config']
    if (config.get('inventory_link_projection_version') != PROJECTION
            or config.get('inventory_schema_sha256') != digest(output_schema())):
        raise ValueError('typed3_read_policy_mismatch')
    reads = receipt.get('inventory_reads', [])
    if not reads:
        if 'inventory' in receipt or 'typed_inventory' in receipt:
            raise ValueError('typed3_read_missing')
        return
    stages = [s for s in receipt.get('stages', []) if s['name'] == 'inventory']
    if len(reads) != 1 or len(stages) != 1:
        raise ValueError('typed3_read_count_invalid')
    read, stage = reads[0], stages[0]
    raw = read.get('raw_output')
    if (not isinstance(raw, str) or sha(raw.encode()) != stage.get('raw_output_sha256')
            or stage.get('schema_sha256') != digest(output_schema(bundle))
            or stage.get('prompt_sha256') != sha(render(bundle).encode())):
        raise ValueError('typed3_read_capture_mismatch')
    model = TypedInventory.model_validate(parse(raw)); checked = inspect(model, bundle)
    if model.model_dump() != receipt.get('typed_inventory') or checked != read.get('validation') or checked != receipt.get('inventory_validation'):
        raise ValueError('typed3_read_validation_mismatch')
    if not checked['valid']:
        if 'inventory' in receipt or 'extraction' in receipt or read.get('link_projection'):
            raise ValueError('typed3_invalid_read_was_admitted')
        return
    inventory, proof = project(model, bundle)
    if inventory.model_dump() != receipt.get('inventory') or proof != read.get('link_projection'):
        raise ValueError('typed3_read_projection_mismatch')
