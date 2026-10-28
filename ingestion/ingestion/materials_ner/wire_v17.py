"""Source-selected literals and condition quantities into the existing native /13.

Selections copy source bytes, not scientific meaning. Previous transports and
responses are unchanged. The first-read prose remains in its receipt, not here.
"""
from copy import deepcopy
from typing import Literal

from pydantic import Field, create_model, model_validator

from .contract import StrictModel, Quantity, canonical, digest
from .inventory import strict_schema
from .evidence import source_catalog
from .source_field_stages import inventory_ledger
from . import typed_inventory_v3 as selected, wire_v11 as accounting
from . import wire_v14 as positioned, wire_v16 as previous, item_stages

WIRE_VERSION = 'materials-ner-inline/3'
PROMPT_VERSION = 'materials-ner-prompt/17.0.0'
PROJECTION_VERSION = 'materials-inline-item-projection/3'
AccountingError = accounting.AccountingError
validate_coverage = previous.validate_coverage


class SourceText(StrictModel):
    selection_id: str = Field(min_length=1)
    quote: str | None = Field(min_length=1, max_length=1600)


class SourceQuantity(StrictModel):
    quantity_selection_id: str | None
    quantity_status: Literal['not_reported', 'not_accessible', 'not_extracted',
                             'ambiguous', 'conflicted', 'not_applicable'] | None

    @model_validator(mode='after')
    def one_source(self):
        if (self.quantity_selection_id is None) == (self.quantity_status is None):
            raise ValueError('source_quantity_selection_or_status_required')
        return self


_COLLECTIONS = {'samples', 'states', 'protocols', 'sample_relations', 'condition_supports', 'additional_items'}
_MAPPINGS = {'decisions', 'context_decisions'}
Base = create_model('SourceSelectedBase', __base__=StrictModel,
    **accounting.copied_fields(previous.AccountedExtraction,
        _COLLECTIONS | _MAPPINGS | {'schema_version', 'processed_block_ids', 'unread_block_ids'}))


def _literal(name):
    return name == 'raw' or name.endswith('_raw')


class AccountedExtraction(Base):
    schema_version: Literal[WIRE_VERSION]
    block_decisions: dict[str, Literal['processed', 'unread']]
    samples: list[dict]
    states: list[dict]
    protocols: list[dict]
    sample_relations: list[dict]
    condition_supports: list[dict]
    decisions: dict[str, dict]
    additional_items: list[dict]
    context_decisions: dict[str, dict]

    parse_response = classmethod(accounting.AccountedExtraction.parse_response.__func__)

    def project(self, inventory, bundle):
        catalog = selected.catalog(bundle)
        blocks = source_catalog(bundle)['blocks']
        if set(self.block_decisions) != set(blocks):
            raise AccountingError('source_block_decisions_not_closed')
        literal_copies, quantity_copies = [], []

        def add(owner, selection_id, fields):
            if owner is not None:
                owner['references'].append(dict(selection_id=selection_id, fields=fields))

        def visit(value, path='', owner=None, field_name=None):
            relative = path[len(owner['path']):] if owner is not None else path
            if field_name is not None and _literal(field_name):
                if value is None:
                    return None
                reference = SourceText.model_validate(value)
                try:
                    witness = positioned.resolve_reference(positioned.EvidenceReference(
                        **reference.model_dump(), fields=[relative]), catalog)[0]
                except ValueError as exc:
                    raise AccountingError(str(exc)) from exc
                add(owner, reference.selection_id, [relative])
                # The model explicitly selects this statement as the declaration
                # basis. This binds its source, not its regime or applicability.
                if relative.endswith('/pressure/basis_raw'):
                    add(owner, reference.selection_id, [relative.removesuffix('/basis_raw')])
                literal_copies.append(dict(path=path, selection=reference.model_dump(), source=witness))
                return witness['quote']
            if isinstance(value, list):
                return [visit(v, f'{path}/{i}', owner) for i, v in enumerate(value)]
            if not isinstance(value, dict):
                return value
            if any(not isinstance(key, str) for key in value):
                raise AccountingError('source_selection_object_keys_invalid')
            if set(value) == {'quantity_selection_id', 'quantity_status'}:
                choice = SourceQuantity.model_validate(value)
                if choice.quantity_selection_id is None:
                    return Quantity(status=choice.quantity_status).model_dump()
                key = choice.quantity_selection_id
                row = catalog['numeric_catalog']['numeric_candidates'].get(key)
                if row is None or not row['selectable'] or row['quantity'] is None:
                    raise AccountingError('source_quantity_selection_not_compilable')
                quantity = deepcopy(row['quantity'])
                quantity['unit'] = row['unit_raw']
                quantity = Quantity.model_validate(quantity).model_dump()
                add(owner, key, [relative, relative + '/raw'])
                if row['unit_raw'] is not None:
                    add(owner, 'U' + key[1:], [relative + '/unit'])
                quantity_copies.append(dict(path=path, selection_id=key, quantity=quantity,
                    source={k: row[k] for k in ('block_id', 'start_char', 'end_char', 'quote')}))
                return quantity
            if 'evidence' in value and not isinstance(value['evidence'], list):
                raise AccountingError('source_selection_evidence_list_invalid')
            local = dict(path=path, references=[]) if 'evidence' in value else owner
            output = {k: visit(v, path + '/' + k.replace('~', '~0').replace('/', '~1'), local, k)
                for k, v in value.items()}
            if 'evidence' in value:
                output['evidence'].extend(local['references'])
            return output

        data = visit(self.model_dump(exclude={'schema_version', 'block_decisions'}))
        data.update(schema_version=previous.WIRE_VERSION,
            processed_block_ids=[key for key, decision in self.block_decisions.items() if decision == 'processed'],
            unread_block_ids=[key for key, decision in self.block_decisions.items() if decision == 'unread'])
        # Complete validation uses the unchanged prior transport/native contract.
        # Unknown fields, bad references and unsupported quantities still fail.
        transport = previous.AccountedExtraction.model_validate(data)
        compact, proof = transport.project(inventory, bundle)
        return compact, dict(schema=PROJECTION_VERSION, transport_sha256=digest(self.model_dump()),
            inventory_sha256=digest(inventory.model_dump()), bundle_sha256=digest(bundle.model_dump()),
            selected_transport_sha256=digest(transport.model_dump()), graph_projection=proof,
            copied_literal_fields=literal_copies, copied_condition_or_parameter_quantities=quantity_copies,
            source_copy_path_scope='transport_json_pointers',
            source_field_values_copied_without_paraphrase=True,
            scientific_relations_inferred_by_compiler=False, scientific_acceptance=False)


def output_schema(bundle=None, inventory=None):
    schema = deepcopy(previous.output_schema(bundle, inventory))
    schema['properties']['schema_version'] = dict(type='string', enum=[WIRE_VERSION])
    for name in ('processed_block_ids', 'unread_block_ids'):
        schema['properties'].pop(name)
        schema['required'].remove(name)
    blocks = list(source_catalog(bundle)['blocks']) if bundle is not None else []
    schema['properties']['block_decisions'] = item_stages._keyed(blocks,
        dict(type='string', enum=['processed', 'unread']))
    schema['required'].append('block_decisions')
    definitions = schema['$defs']
    text = strict_schema(SourceText)
    numeric = strict_schema(SourceQuantity)
    if bundle is not None:
        catalog = selected.catalog(bundle)
        text['properties']['selection_id']['enum'] = list(catalog['witness_selections'])
        numeric['properties']['quantity_selection_id']['anyOf'][0]['enum'] = [
            k for k, v in catalog['numeric_catalog']['numeric_candidates'].items()
            if v['selectable'] and v['quantity'] is not None] or ['no_compilable_numeric_selection']
    reported, missing = deepcopy(numeric), deepcopy(numeric)
    reported['properties']['quantity_selection_id'] = reported['properties']['quantity_selection_id']['anyOf'][0]
    reported['properties']['quantity_status'] = {'type': 'null'}
    missing['properties']['quantity_selection_id'] = {'type': 'null'}
    missing['properties']['quantity_status'] = missing['properties']['quantity_status']['anyOf'][0]
    definitions['Quantity'] = dict(anyOf=[reported, missing])

    def replace(node):
        if isinstance(node, list):
            for child in node: replace(child)
        elif isinstance(node, dict):
            for name, child in list(node.get('properties', {}).items()):
                if _literal(name):
                    branches = child.get('anyOf', [child])
                    nullable = any(b.get('type') == 'null' for b in branches)
                    nonnull = [b for b in branches if b.get('type') != 'null']
                    if not nonnull:
                        continue
                    if nonnull and not all(b.get('type') == 'string' for b in nonnull):
                        raise ValueError('unsupported_literal_source_field_shape:' + name)
                    source = {'$ref': '#/$defs/SourceText'}
                    node['properties'][name] = (dict(anyOf=[source, {'type': 'null'}]) if nullable else source)
            for child in node.values(): replace(child)
    replace(schema)
    definitions['SourceText'] = text
    return schema


RULES = '''SOURCE-SELECTED FIELDS, INLINE /3:
The SOURCE_COORDINATE_LEDGER contains IDs, exact source coordinates and numeric
text only. Previous model classifications and interpretation prose are omitted
from this prompt. Their original receipt is retained for audit. Independently
read the source to identify results, specimens/runs, methods and conditions.

Every *_raw field (and a standalone raw field) is now a source choice object:
{selection_id, quote}, or null when that field permits absence. quote=null copies
the complete selected text. Otherwise quote must be one exact UNIQUE substring
of that selection, including source whitespace and symbols. The compiler copies
it unchanged and binds its source to that field. Choose the literal formula, not
a normalized formula or full prose sentence. Model explanations belong in the
existing labels, limitations and unresolved explanations, never in a raw field.
Do not emit the source choice object in an ordinary non-raw string field.

Every condition/protocol/sample Quantity is now a choice object containing
quantity_selection_id and quantity_status, exactly one non-null. A numeric
selection copies that complete occurrence, including uncertainty, approximation
and printed unit spelling. Do not transfer an approximate marker from a nearby
Tc to its pressure, or vice versa. Do not type a synthetic numeric quantity.
Result quantities retain their existing selection fields. A source number does
not establish its role, ownership or meaning; supply those independently with
their applicable source evidence. Every state still needs /sample_id evidence.

Ordinary pressure at a reported Tc is a measurement condition, not automatically
a critical_pressure result. A pressure at an extremum is not by itself evidence
of a critical-pressure observable. A physical critical-pressure result requires
source support for that meaning and definition. If an inventoried item is only a
setting, hold it with reason=not_a_result and explain its actual role. Carry the
known condition in the applicable state with its own witnesses. Holding a false
positive does not erase it or independently approve its exclusion.

block_decisions contains every supplied block alias exactly once, as processed
or unread. Processed means reviewed within its declared TARGET/CONTEXT scope,
not that every full-paper numerical/graphical result was extracted. Do not mark
unread context as processed merely to pass coverage. Do not output the old
processed_block_ids/unread_block_ids arrays; the compiler derives them from your
explicit choices without inventing a reading decision.

Source-backed context can bind to a field already present on an entity. Shared
physical specimen identity need not be resolved to preserve a source-scoped
method or protocol assertion. Do not mark all contexts unresolved merely because
the paper has several experiments. Do not transfer a method or condition across
those experiments without evidence. Follow the named run through its complete
paragraph and original column continuation. Retain reported criterion wording
and observable even when its controlled category remains unspecified. Preserve
an operation temperature through existing condition/context fields and its role,
not through a paraphrase labelled preparation. No new scientific facts are
supplied by this compiler. All candidates still require scientific review.
'''
PROMPT_HASH = digest(dict(version=PROMPT_VERSION, previous=previous.PROMPT_HASH,
    rules=RULES, ledger='materials-source-item-ledger/1'))


def render(bundle, inventory):
    prompt = previous.render(bundle, inventory)
    prior = canonical(inventory.model_dump())
    if prompt.count(prior) != 1:
        raise ValueError('native_inventory_ledger_prompt_binding_invalid')
    prompt = prompt.replace(prior, canonical(inventory_ledger(inventory)))
    prompt = prompt.replace('FRESH_INVENTORY (fallible; verify against original source):',
        'SOURCE_COORDINATE_LEDGER (not a scientific answer key):')
    prompt = prompt.replace(previous.WIRE_VERSION, WIRE_VERSION)
    return RULES + '\n' + prompt + '\nReturn the complete materials-ner-inline/3 source-selected transport.\n'


def verify_extraction(receipt, bundle, raw_output):
    return accounting.verify_extraction(receipt, bundle, raw_output, model=AccountedExtraction)
