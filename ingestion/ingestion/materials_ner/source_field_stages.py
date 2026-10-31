"""Opt-in source-coordinate prompts and entity-scoped evidence generation.

No scientific graph type or projection changes. The complete original inventory
is retained in the parent/receipt; only its fallible prose is omitted from model
prompts. Source bytes and literal values are unchanged. Field constraints prevent
invented owner paths but cannot establish source applicability or correctness.
"""
from copy import deepcopy
import re

from . import identity_stages as identity, item_ownership as owners, item_stages as items
from .contract import canonical, digest

POLICY = 'source_fields_v1'
LEDGER_VERSION = 'materials-source-item-ledger/1'
PROMPT_VERSION = 'materials-source-item-owner-prompt/4.1.0'
OUTPUT_FORMAT = identity.OUTPUT_FORMAT
Declarations = identity.Declarations
Relations = identity.Relations
declare = identity.declare
check_declarations = identity.check_declarations
project = identity.project
audit_catalog = identity.audit_catalog
assemble = identity.assemble
relation_schema = identity.relation_schema


def item_coordinates(item):
    return {key: getattr(item, key) for key in ('id', 'source_span_ids', 'context_span_ids', 'value_raw')}


def context_coordinates(context):
    return dict(id=context.id, span_ids=context.span_ids)


def inventory_ledger(inventory):
    return dict(schema=LEDGER_VERSION, work_id=inventory.work_id,
        items=[item_coordinates(item) for item in inventory.items],
        context_assertions=[context_coordinates(context) for context in inventory.context_assertions],
        processed_block_ids=inventory.processed_block_ids, unread_block_ids=inventory.unread_block_ids,
        scientific_interpretation_supplied=False)


def _pointer_patterns(node, definitions, prefix='', seen=frozenset()):
    """Finite legal paths, including indexed elements but no whole-array binds."""
    if '$ref' in node:
        name = node['$ref'].removeprefix('#/$defs/')
        if name in seen:
            return []
        return _pointer_patterns(definitions[name], definitions, prefix, seen | {name})
    if 'anyOf' in node:
        return sorted({p for branch in node['anyOf'] for p in _pointer_patterns(branch, definitions, prefix, seen)})
    if node.get('type') == 'array':
        return _pointer_patterns(node['items'], definitions, prefix+r'/(?:0|[1-9][0-9]*)', seen)
    paths = [prefix] if prefix else []
    if node.get('type') == 'object':
        for name, child in node.get('properties', {}).items():
            if name in {'id', 'evidence', 'inventory_item_ids'}:
                continue
            paths.extend(_pointer_patterns(child, definitions, prefix+'/'+re.escape(name), seen))
    return paths


def scoped_evidence_schema(schema):
    """Constrain references on every inline/defined entity, without rewriting data."""
    schema = deepcopy(schema)
    definitions = schema['$defs'];base = deepcopy(definitions['EvidenceReference'])
    references = {}

    def visit(node, owner_name=None):
        if isinstance(node, list):
            for child in node: visit(child, owner_name)
        elif isinstance(node, dict):
            properties = node.get('properties', {})
            if 'evidence' in properties:
                method = properties.get('method', {})
                if any(x.get('type') == 'null' for x in method.get('anyOf', [])):
                    reported, missing = deepcopy(node), deepcopy(node)
                    branches = [x for x in method['anyOf'] if x.get('type') != 'null']
                    reported['properties']['method'] = branches[0] if len(branches) == 1 else {'anyOf': branches}
                    missing['properties']['method'] = {'type': 'null'}
                    node.clear();node['anyOf'] = [reported, missing]
                    visit(node['anyOf'], owner_name)
                    return
                body = deepcopy(node)
                # These belong to nested entities or operational reading scope.
                for key in ('states', 'result', 'definition', 'formula_unavailability'):
                    body['properties'].pop(key, None)
                for key, child in list(body['properties'].items()):
                    if child.get('type') == 'null': body['properties'].pop(key)
                paths = set(_pointer_patterns(body, definitions))
                if owner_name == 'DeclaredState': paths.add('/sample_id')
                if node.get('title') == 'ObservationResult':
                    # The compact body omits these fields; expansion copies the
                    # selected observation owners onto the canonical result.
                    paths.update(('/sample_id', '/state_id', '/protocol_id'))
                pattern = '^(?:'+'|'.join(sorted(paths))+')$'
                if pattern not in references:
                    name = 'ScopedEvidence'+str(len(references)+1)
                    reference = deepcopy(base)
                    reference['properties']['fields']['items'] = {'type': 'string', 'pattern': pattern}
                    definitions[name] = reference;references[pattern] = name
                properties['evidence']['items'] = {'$ref': '#/$defs/'+references[pattern]}
            for key, child in list(node.items()):
                if key == '$defs':
                    for name, definition in list(child.items()): visit(definition, name)
                else: visit(child, owner_name)
    visit(schema)
    return schema


def declaration_schema(bundle=None):
    return scoped_evidence_schema(identity.declaration_schema(bundle))


def owner_schema(bundle=None, inventory=None):
    return scoped_evidence_schema(identity.owner_schema(bundle, inventory))


def item_schema(bundle=None, catalog=None, item_ids=(), all_items=(), *, plan=None):
    return scoped_evidence_schema(owners.item_schema(bundle, catalog, item_ids, all_items, plan=plan))


FIELD_RULES = r'''SOURCE FIELDS V1:
The item ledger contains operational IDs, exact source coordinates and literal
numeric text only. It is not a scientific answer key. Read the source to decide
quantity meaning, authorship, specimen association, method and conditions.
Previous inventory names, sample descriptions and interpretation prose are not
source literals and are intentionally absent from this prompt. The complete
original inventory remains in the audit record; no historical decision changes.

Use only the scoped evidence paths allowed for the actual entity. Nested states
support /sample_id, not /sample_index. The code assigns the ID from nesting;
your selected spans must support that scientific association. Do not bind a null
field, /id, an undeclared member, or a whole array instead of its actual element.
An entity with no reported conditions may still have valid ownership evidence.

Every *_raw string must be contiguous original text, including TeX delimiters,
braces and macros. Put explanatory wording in labels/limitations, never in a raw
name. A quantity's symbol and its orientation/interpretation are separate source
assertions; use component_raw and interpretation_raw on the result when needed.

A variable T denoting temperature is not the unit T (tesla). A limit such as
T -> 0 is not an applied zero field or a directly measured zero-temperature
condition. Preserve a stated limit as result interpretation using the literal
source text; leave experimental conditions empty when not actually reported.
Do not copy a result value into its own independent condition. Do not infer a
fit/extrapolation method solely from limit notation. Keep unstated method null.
Shared procedure details must apply to every linked result. Put a result-specific
limit on that result instead of extending it to finite-temperature observations.
Condition quantity/raw/unit/role and direction each need actual source support.
'''
CONTEXT_RULES = '''SOURCE CONTEXT V1:
Context IDs designate source spans, not prior inventory interpretations. Read
those original spans and the frozen graph. Do not infer cited status, specimen
identity or procedure applicability from an inventory label. Carry source facts
only to actual applicable fields. For a source assertion already represented,
select its existing field; do not require a duplicate object. If a context is not
applicable to these target results, explain why. If applicability cannot be
resolved, keep it unresolved with the actual source-based reason. Never mark a
real missing assertion not_applicable merely to make completeness pass.
'''
PROMPT_HASH = digest(dict(version=PROMPT_VERSION, previous=identity.PROMPT_HASH,
    policy=POLICY, ledger=LEDGER_VERSION, fields=FIELD_RULES, context=CONTEXT_RULES,
    generation='entity-scoped-indexed-evidence-pointers/1'))


def prompt_identity(policy):
    identity.prompt_identity(policy)
    return PROMPT_VERSION, PROMPT_HASH


def render_declarations(bundle, inventory, *, policy=identity.POLICY):
    text = identity.render_declarations(bundle, inventory, policy=policy)
    old = 'SOURCE_INVENTORY: '+canonical(inventory.model_dump())
    assert text.count(old) == 1
    return text.replace(old, 'SOURCE_ITEM_LEDGER: '+canonical(inventory_ledger(inventory)))+'\n'+FIELD_RULES


def render_items(bundle, inventory, catalog, item_ids, plan):
    text = identity.render_items(bundle, inventory, catalog, item_ids, plan)
    all_items, _ = items.inventory_items(inventory, catalog)
    selected = [x for x in all_items if x.id in item_ids]
    old = 'REQUESTED_ITEMS: '+canonical([x.model_dump() for x in selected])
    assert text.count(old) == 1
    return text.replace(old, 'REQUESTED_ITEMS: '+canonical([item_coordinates(x) for x in selected]))+'\n'+FIELD_RULES


def _context_prompt(text, inventory):
    old = 'SOURCE_CONTEXT_ASSERTIONS: '+canonical([x.model_dump() for x in inventory.context_assertions])
    assert text.count(old) == 1
    return text.replace(old, 'SOURCE_CONTEXT_ASSERTIONS: '+canonical([context_coordinates(x) for x in inventory.context_assertions]))+'\n'+CONTEXT_RULES


def render_relations(bundle, inventory, catalog):
    return _context_prompt(identity.render_relations(bundle, inventory, catalog), inventory)+'\n'+FIELD_RULES


def render_links(bundle, inventory, graph):
    return _context_prompt(items.render_links(bundle, inventory, graph), inventory)


class Ownership:
    POLICIES = identity.Ownership.POLICIES
    Declarations = identity.OwnedDeclarations
    body = staticmethod(identity.body)
    project = staticmethod(identity.project_owners)
    declaration_schema = staticmethod(owner_schema)
    check_group = staticmethod(owners.check_group)
    item_schema = staticmethod(item_schema)
    prompt_identity = staticmethod(prompt_identity)
    render_declarations = staticmethod(render_declarations)
    render_items = staticmethod(render_items)
