"""Opt-in transport of frozen owner proposals and compatible support choices.

No source interpretation or canonical fields are added. A witness is selected
by the model in declarations, then replayed after verifying the same declaration,
source, inventory, catalog and item ownership. It remains scientifically unreviewed.
"""
from copy import deepcopy

from . import identity_stages as identity, item_ownership as owners, item_stages as items, source_field_stages as fields
from .contract import Quantity, digest
from .evidence import source_catalog, selected_quotes
from .validation_v6 import same_quantity

POLICY = 'source_fields_v2'
PROMPT_VERSION = 'materials-source-item-owner-prompt/4.2.0'
TRANSPORT_VERSION = 'materials-owner-witness-transport/1'
SUPPORT_POLICY = 'same_registered_quantity_support_v1'
OUTPUT_FORMAT = identity.OUTPUT_FORMAT
Declarations = fields.Declarations
Relations = fields.Relations
declare = fields.declare
check_declarations = fields.check_declarations
project = fields.project
audit_catalog = fields.audit_catalog
declaration_schema = fields.declaration_schema
owner_schema = fields.owner_schema
item_schema = fields.item_schema
relation_schema = fields.relation_schema
inventory_ledger = fields.inventory_ledger
render_declarations = fields.render_declarations
render_relations = fields.render_relations


def assemble(bundle, inventory, catalog, decisions, links, *, owner_plan,
             owner_declarations, catalog_relations, missing_item_ids=(), stage_failures=(),
             catalog_adapter=identity):
    """Recompute the selected plan from the retained declaration, never its hash alone."""
    expected_plan = catalog_adapter.project_owners(owner_declarations, inventory, bundle)
    if owner_plan != expected_plan:
        raise ValueError('staged_owner_witness_selection_mismatch')
    expected_catalog, projection = catalog_adapter.project(catalog_adapter.body(owner_declarations), catalog_relations, bundle)
    if catalog.model_dump() != expected_catalog.model_dump():
        raise ValueError('staged_owner_witness_catalog_mismatch')
    owners.check_group(items.ItemGroup(schema_version='materials-source-item-group/1',
        work_id=bundle.work_id, decisions=decisions), owner_plan)
    before = {key: value.model_dump() for key, value in decisions.items()}
    after = deepcopy(before); entries = []
    source = source_catalog(bundle)
    for item_id, decision in after.items():
        if decision['decision'] != 'emitted':
            continue
        observation = decision['observation']
        selected = owner_plan['items'][item_id]
        quotes = selected_quotes(source, selected['source_span_ids'])
        if any(observation[key] != value for key, value in selected['owners'].items()):
            raise ValueError('staged_owner_witness_owner_mismatch')
        evidence = observation['result']['evidence']
        paths = ['/sample_id', '/state_id', '/protocol_id']
        # Retain existing evidence even when it disagrees. Only append the prior
        # selection where its exact source/field binding is not already present.
        missing = [path for path in paths if not any(path in ref['fields'] and
            ref['span_ids'] == selected['source_span_ids'] for ref in evidence)]
        if missing:
            evidence.append(dict(fields=missing, span_ids=selected['source_span_ids']))
        entries.append(dict(item_id=item_id, result_id=items.result_id(item_id), owners=selected['owners'],
            selection_sha256=digest(selected), source_span_ids=selected['source_span_ids'],
            source_witness_sha256=digest(quotes), fields=paths, appended_fields=missing))
    augmented = items.ItemGroup(schema_version='materials-source-item-group/1', work_id=bundle.work_id, decisions=after)
    restored = augmented.model_dump()['decisions']
    for key, new in restored.items():
        if new['decision'] == 'emitted':
            new['observation']['result']['evidence'] = before[key]['observation']['result']['evidence']
    if restored != before:
        raise ValueError('staged_owner_witness_changed_scientific_payload')
    # Use the same assembly after adding witnesses so coverage and completion
    # are recomputed; absent decisions and held items still remain incomplete.
    projected, coverage, proof = catalog_adapter.assemble(bundle, inventory, catalog, augmented.decisions, links,
        owner_plan=owner_plan, missing_item_ids=missing_item_ids, stage_failures=stage_failures)
    proof.update(schema='materials-source-item-assembly/3',
        decisions_sha256=digest(before),
        owner_witness_transport=dict(schema=TRANSPORT_VERSION,
            owner_plan_sha256=digest(owner_plan), declarations_sha256=digest(owner_declarations.model_dump()),
            catalog_projection_sha256=digest(projection), input_decisions_sha256=digest(before),
            augmented_decisions_sha256=digest(after),
            entries=entries, scientific_payload_unchanged=True, scientific_ownership_verified=False))
    return projected, coverage, proof


def support_choices(graph):
    """Necessary compatibility only; matching quantities never establish a relation."""
    states = {s['id']: s for s in graph['states']}
    protocols = {p['id']: p for p in graph['protocols']}
    choices = []
    for observation in graph['observations']:
        result = observation['result']; state = states[observation['state_id']]
        if result['origin'] not in {'observed', 'model_derived'} or not protocols[observation['protocol_id']]['method']:
            continue
        for condition in state['conditions']:
            if result['quantity_kind'] != condition['kind']:
                continue
            try:
                equal = same_quantity(condition['kind'], Quantity.model_validate(result['quantity']),
                    Quantity.model_validate(condition['quantity']))
            except ValueError:
                equal = False
            if equal:
                choices.append(dict(result_id=observation['id'], state_id=state['id'], condition_id=condition['id']))
    return choices


def links_schema(bundle=None, inventory=None, graph=None):
    schema = items.links_schema(bundle, inventory, graph)
    if graph is not None:
        base = items.links_schema()['$defs']['SourceSupport']; choices = []
        for ids in support_choices(graph):
            choice = deepcopy(base)
            for key, value in ids.items():
                choice['properties'][key]['enum'] = [value]
            choices.append(choice)
        if choices:
            schema['$defs']['SourceSupport'] = {'anyOf': choices}
            schema['properties']['condition_supports'].pop('maxItems', None)
        else:
            schema['properties']['condition_supports']['maxItems'] = 0
    return fields.scoped_evidence_schema(schema)


OWNER_RULES = '''OWNER WITNESS TRANSPORT V1:
The program replays your frozen declaration's source spans onto each emitted
result's sample_id, state_id and protocol_id. You do not need to generate those
evidence pointers again. This preserves a prior model proposal only: if an owner
is unsupported, hold the item. Keep evidence for all other scientific fields.
'''
SUPPORT_RULES = '''CONDITION SUPPORT CHOICES V1:
A measures relation means that this result measures the same registered physical
quantity and numerical value as the condition. A Tc at a stated applied field
does not measure that field. Shared units alone do not equate different physical
quantities. Allowed choices are necessary compatibility checks, not established
relationships. Select only a source-supported edge; otherwise leave the list
empty and retain any unresolved source assertion in its context disposition.
'''
PROMPT_HASH = digest(dict(version=PROMPT_VERSION, previous=fields.PROMPT_HASH,
    transport=TRANSPORT_VERSION, owner_rules=OWNER_RULES, support_policy=SUPPORT_POLICY,
    support_rules=SUPPORT_RULES))


def prompt_identity(policy):
    identity.prompt_identity(policy)
    return PROMPT_VERSION, PROMPT_HASH


def render_items(bundle, inventory, catalog, item_ids, plan):
    return fields.render_items(bundle, inventory, catalog, item_ids, plan)+'\n'+OWNER_RULES


def render_links(bundle, inventory, graph):
    return fields.render_links(bundle, inventory, graph)+'\n'+SUPPORT_RULES


class Ownership(fields.Ownership):
    prompt_identity = staticmethod(prompt_identity)
    render_items = staticmethod(render_items)
