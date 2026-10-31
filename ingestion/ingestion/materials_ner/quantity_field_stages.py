"""Opt-in registered quantity/unit coupling without adding scientific fields.

The source item may supply a literal explicit unit, never an authoritative
quantity interpretation. Bare table values and unsupported unit syntax retain
the ordinary source-review path. Units are not inferred from quantity names.
"""
from collections import defaultdict
from copy import deepcopy

from . import identity_stages as identity, owner_witness_stages as previous
from .contract import digest
from .evidence import source_catalog, selected_quotes
from .quantities import UNITS, REGISTRY_VERSION, NUMERIC_PREFIX, lexical, numeric_presentation, unit_key

POLICY = 'source_fields_v3'
PROMPT_VERSION = 'materials-source-item-owner-prompt/4.3.0'
DIMENSION_POLICY = 'registered_result_source_units_v1'
OUTPUT_FORMAT = previous.OUTPUT_FORMAT
Declarations = previous.Declarations
Relations = previous.Relations
declare = previous.declare
check_declarations = previous.check_declarations
project = previous.project
audit_catalog = previous.audit_catalog
assemble = previous.assemble
declaration_schema = previous.declaration_schema
owner_schema = previous.owner_schema
relation_schema = previous.relation_schema
links_schema = previous.links_schema
inventory_ledger = previous.inventory_ledger
render_relations = previous.render_relations


def explicit_source_unit(bundle, item):
    """Recognize only a complete literal item with an explicit registered unit.

    This is not a value parser or a scientific quantity classifier. No unit is
    appended from a header, and unsupported syntax must not erase a result.
    """
    if bundle is None or item is None or item.value_raw is None:
        return None
    raw = item.value_raw
    quotes = selected_quotes(source_catalog(bundle), item.source_span_ids)
    matching = [q for q in quotes if ' '.join(raw.split()) in ' '.join(q['quote'].split())]
    if not matching:
        return None
    match = NUMERIC_PREFIX.fullmatch(numeric_presentation(lexical(raw)))
    if match is None or not match[2]:
        return None
    literal = match[2]; key = unit_key(literal)
    units = sorted({u for _, allowed, _ in UNITS.values() for u in allowed if unit_key(u) == key})
    if not units:
        return None
    return dict(item_id=item.id, value_raw=raw, unit_literal=literal, unit_key=key,
        registry_unit_spellings=units, source_span_ids=item.source_span_ids,
        source_witness_sha256=digest(matching), scientific_meaning_verified=False)


def coupled_result_schema(definition, definitions, hint=None, quantity_names=None):
    """Split existing branches by registered units; keep missingness and non-detection."""
    quantity_names = {} if quantity_names is None else quantity_names
    branches = []
    for original in definition['anyOf']:
        grouped = defaultdict(list)
        for kind in original['properties']['quantity_kind']['enum']:
            if kind == 'non_detection':
                branches.append(deepcopy(original))
                continue
            if kind == 'unmapped':
                units = tuple(hint['registry_unit_spellings']) if hint else None
            else:
                if kind not in UNITS:
                    raise ValueError('staged_result_quantity_not_registered')
                units = tuple(UNITS[kind][1])
                if hint:
                    units = tuple(u for u in units if unit_key(u) == hint['unit_key'])
                    if not units:
                        continue
            grouped[units].append(kind)
        for units, kinds in grouped.items():
            branch = deepcopy(original)
            branch['properties']['quantity_kind']['enum'] = kinds
            if units is not None:
                if units not in quantity_names:
                    name = 'RegisteredResultQuantity'+str(len(quantity_names)+1)
                    quantity = deepcopy(definitions['Quantity'])
                    for variant in quantity['anyOf']:
                        if variant['properties']['status'].get('enum') == ['reported']:
                            variant['properties']['unit'] = {'type': 'string', 'enum': list(units)}
                    definitions[name] = quantity
                    quantity_names[units] = name
                branch['properties']['quantity'] = {'$ref': '#/$defs/'+quantity_names[units]}
            branches.append(branch)
    return {'anyOf': branches}


def prune_unused_definitions(schema):
    """Remove unreachable definitions only; retain the exact reachable constraint graph."""
    definitions = schema['$defs']; seen = set()
    def visit(value):
        if isinstance(value, list):
            for child in value: visit(child)
        elif isinstance(value, dict):
            if '$ref' in value:
                reference = value['$ref']
                if not reference.startswith('#/$defs/'):
                    raise ValueError('staged_external_schema_reference')
                name = reference.removeprefix('#/$defs/')
                if name not in seen:
                    seen.add(name); visit(definitions[name])
            for key, child in value.items():
                if key != '$defs': visit(child)
    visit(schema)
    schema['$defs'] = {key:value for key,value in definitions.items() if key in seen}
    return schema


def item_schema(bundle=None, catalog=None, item_ids=(), all_items=(), *, plan=None):
    schema = previous.item_schema(bundle, catalog, item_ids, all_items, plan=plan)
    definitions = schema['$defs']; names = {}; specialized = {}
    items = {item.id:item for item in all_items}
    # Owner-specific result references may be shared by items with different
    # source units. Specialize each item before removing unused definitions.
    if plan is not None:
        for item_id, decision in schema['properties']['decisions']['properties'].items():
            if plan['items'][item_id]['resolution'] != 'bound':
                continue
            observation = decision['anyOf'][0]['properties']['observation']
            result = observation['properties']['result']
            original = deepcopy(definitions[result['$ref'].removeprefix('#/$defs/')])
            hint = explicit_source_unit(bundle, items.get(item_id))
            key = (digest(original), hint['unit_key'] if hint else None)
            if key not in specialized:
                name = 'SourceUnitResult'+str(len(specialized)+1)
                definitions[name] = coupled_result_schema(original, definitions, hint, names)
                specialized[key] = name
            result.clear(); result['$ref'] = '#/$defs/'+specialized[key]
    else:
        definitions['ObservationResult'] = coupled_result_schema(definitions['ObservationResult'], definitions, quantity_names=names)
    return prune_unused_definitions(schema) if item_ids else schema


DIMENSION_RULES = '''REGISTERED SOURCE UNITS V1:
Choose the physical quantity from the actual source name and definition, then
preserve its reported unit. The schema couples registered kinds and units; a
source unit does not by itself identify the physical quantity. Never change a
source unit merely to fit a previously selected kind. T for tesla differs from
temperature T, H and B differ, and a critical field is not a pressure. Preserve
the source field convention; do not introduce a mu0 conversion. Unknown meaning
can remain unmapped or explicitly held, with the original assertion retained.
Bare table values may use a unit explicitly provided by their own header/context;
do not append that unit to value_raw or silently copy another column's unit.
'''
STATE_RULES = '''ATOMIC RESULT CONDITIONS V1:
Before freezing the catalog, read the local conditions of every target result.
When several values are paired with several settings using respectively or an
equivalent table layout, keep each value-setting association in its own applicable
state. A common specimen or apparatus does not make different measurements one
condition tuple. Put applied fields/pressures in measurement-role conditions;
interpretation_raw, qualifiers and a paragraph-level context disposition do not
replace those structured conditions. Never copy the target critical threshold
as an independent applied condition of itself. Keep zero-temperature limits as
interpretations; do not invent zero-temperature measurements or zero fields.
If an association is unresolved, say so rather than silently dropping its setting.
Raw fields must be contiguous original substrings. For a paired sentence, retain
the whole source sentence if necessary; do not join fragments into invented raw
wording. Verify each zero-based owner index against the actual declared catalog.
'''
PROMPT_HASH = digest(dict(version=PROMPT_VERSION, previous=previous.PROMPT_HASH,
    dimension_policy=DIMENSION_POLICY, registry=REGISTRY_VERSION, registered_units=UNITS,
    dimension_rules=DIMENSION_RULES, state_rules=STATE_RULES))


def prompt_identity(policy):
    previous.prompt_identity(policy)
    return PROMPT_VERSION, PROMPT_HASH


def render_declarations(bundle, inventory, *, policy=identity.POLICY):
    return previous.render_declarations(bundle, inventory, policy=policy)+'\n'+DIMENSION_RULES+'\n'+STATE_RULES


def render_items(bundle, inventory, catalog, item_ids, plan):
    return previous.render_items(bundle, inventory, catalog, item_ids, plan)+'\n'+DIMENSION_RULES+'\n'+STATE_RULES


def render_links(bundle, inventory, graph):
    return previous.render_links(bundle, inventory, graph)+'\n'+STATE_RULES


class Ownership(previous.Ownership):
    prompt_identity = staticmethod(prompt_identity)
    render_declarations = staticmethod(render_declarations)
    render_items = staticmethod(render_items)
    item_schema = staticmethod(item_schema)
