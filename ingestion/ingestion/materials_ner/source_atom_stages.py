"""Source atoms and table ownership on the existing durable v4 stage workflow.

No alternate provider, store, worker, result generator or promotion path exists
here. Model source choices compile into NER/10 bodies before ordinary relations,
frozen owners, result groups and context accounting run.
"""
from copy import deepcopy
from types import SimpleNamespace

from . import source_atoms as atoms, condition_catalog_stages as bridge
from . import frozen_owner_stages as frozen, target_context_stages as previous
from . import identity_stages as identity, owner_witness_stages as witnesses
from . import source_field_stages as fields, quantity_field_stages as quantities
from . import table_ownership, item_stages as items
from .contract import canonical, digest
from .inventory import source_text, strict_schema
from .evidence import source_catalog

POLICY = 'source_atoms_v1'
WORKFLOW = frozen.WORKFLOW
OUTPUT_FORMAT = frozen.OUTPUT_FORMAT
PROMPT_VERSION = 'materials-source-atom-stage-prompt/1.0.0'
BINDING_VERSION = frozen.BINDING_VERSION
PROMPT_HASH = digest(dict(version=PROMPT_VERSION, atom_policy=atoms.POLICY,
    atom_rules=atoms.RULES, scientific_rules=atoms.previous.INSTRUCTIONS,
    later_stages=previous.PROMPT_HASH, table_policy=table_ownership.POLICY,
    compact_prompt_view='omit-redundant-exact-quotes/1', owner_schema='closed-item-table-ids/1'))
inventory_ledger = fields.inventory_ledger


def prompt_view(value):
    """Omit repeated quote carriers only; retain every scientific value and span."""
    if isinstance(value, list):
        return [prompt_view(v) for v in value]
    if isinstance(value, dict):
        return {k: prompt_view(v) for k, v in value.items()
                if not (k == 'exact_quotes' and {'fields', 'span_ids'} <= set(value))}
    return value


def compact_prompt(text, value):
    original = canonical(value)
    if text.count(original) != 1:
        raise ValueError('staged_atom_prompt_view_target_mismatch')
    return text.replace(original, canonical(prompt_view(value)))


class Adapter:
    POLICY = POLICY
    WORKFLOW = WORKFLOW
    OUTPUT_FORMAT = OUTPUT_FORMAT
    PROMPT_VERSION = PROMPT_VERSION
    PROMPT_HASH = PROMPT_HASH
    BINDING_VERSION = BINDING_VERSION
    Bridge = bridge
    NATIVE_SCHEMA = 'materials-ner/10'
    Declarations = atoms.CatalogChoices
    Relations = frozen.Relations
    OwnerBindings = frozen.OwnerBindings
    inventory_ledger = staticmethod(inventory_ledger)
    relation_schema = staticmethod(frozen.relation_schema)
    item_schema = staticmethod(frozen.item_schema)
    links_schema = staticmethod(frozen.links_schema)
    def audit_catalog(self, catalog, inventory, bundle):
        return self.Bridge.audit_catalog(catalog, inventory, bundle)

    def __init__(self, context=None):
        self.context = deepcopy(context)
        self.Ownership = SimpleNamespace(POLICIES=identity.Ownership.POLICIES,
            prompt_identity=self.prompt_identity, declaration_schema=self.declaration_schema,
            render_declarations=self.render_declarations, check_group=frozen.Ownership.check_group,
            item_schema=frozen.Ownership.item_schema, render_items=self.render_items)

    @staticmethod
    def prompt_identity(policy):
        identity.prompt_identity(policy)
        return PROMPT_VERSION, PROMPT_HASH

    def ownership(self, bundle):
        if self.context is None or self.context.get('schema') != atoms.CONTEXT or self.context.get('bundle_sha256') != digest(bundle.model_dump()):
            raise ValueError('staged_atom_context_binding_mismatch')
        compiled = table_ownership.compile_ownership(bundle, self.context['ledger'],
            marker_convention=self.context['marker_convention'])
        if digest(compiled) != self.context['ownership_sha256']:
            raise ValueError('staged_atom_table_source_changed')
        return compiled

    def compile(self, declarations, bundle):
        projection = atoms.project(declarations, bundle, self.ownership(bundle))
        return self.Bridge.from_projection(projection, bundle), projection

    def declaration_schema(self, bundle=None, inventory=None):
        return atoms.schema(bundle, self.ownership(bundle) if bundle is not None else None)

    def render_declarations(self, bundle, inventory, *, policy=identity.POLICY):
        identity.prompt_identity(policy)
        ownership, _ = atoms.verify_context(self.context, bundle, inventory)
        # Remove the earlier free-literal transport instructions only; all
        # scientific missingness and applicability rules remain explicit.
        rules = atoms.previous.INSTRUCTIONS
        rules = '\n'.join(line for line in rules.splitlines() if not line.startswith('Select T candidate IDs'))
        return '\n'.join([rules, atoms.RULES, 'WORK_ID: '+bundle.work_id,
            'SOURCE_ITEM_LEDGER: '+canonical(inventory_ledger(inventory)),
            'SOURCE: '+source_text(bundle), atoms.render_candidates(atoms.candidates(bundle, ownership), ownership)])

    def check_declarations(self, declarations, inventory, bundle, max_items, *, strict_field_owner=True):
        atoms.verify_context(self.context, bundle, inventory)
        compiled, _ = self.compile(declarations, bundle)
        return self.Bridge.check_declarations(compiled, inventory, bundle, max_items, strict_field_owner=strict_field_owner)

    def project(self, declarations, relations, bundle):
        compiled, source_projection = self.compile(declarations, bundle)
        catalog, proof = self.Bridge.project(compiled, relations, bundle)
        proof['source_atom_projection'] = source_projection
        proof['source_choices_sha256'] = digest(declarations.model_dump())
        proof['source_atom_context_sha256'] = digest(self.context)
        return catalog, proof

    @staticmethod
    def render_relations(bundle, inventory, catalog):
        return compact_prompt(previous.render_relations(bundle, inventory, catalog), catalog.model_dump())

    @staticmethod
    def render_items(bundle, inventory, catalog, item_ids, plan):
        return compact_prompt(frozen.Ownership.render_items(bundle, inventory, catalog, item_ids, plan), catalog.model_dump())

    @staticmethod
    def render_links(bundle, inventory, graph):
        return compact_prompt(frozen.render_links(bundle, inventory, graph), graph)

    def binding_schema(self, bundle=None, inventory=None, catalog=None, *, declarations=None):
        schema = strict_schema(frozen.OwnerBindings)
        bound = schema['$defs']['BoundIdOwner']
        if catalog is not None:
            for key, values in [('sample_id', catalog.samples), ('state_id', catalog.states), ('protocol_id', catalog.protocols)]:
                if values:
                    bound['properties'][key]['enum'] = [v.id for v in values]
            schema['properties']['catalog_sha256']['enum'] = [digest(catalog.model_dump())]
        if bundle is not None:
            schema['properties']['work_id']['enum'] = [bundle.work_id]
            spans = list(source_catalog(bundle)['spans'])
            for name in ('BoundIdOwner', 'UnresolvedOwner', 'Attribution'):
                schema['$defs'][name]['properties']['source_span_ids']['items']['enum'] = spans
        all_items, _ = items.inventory_items(inventory, catalog) if inventory is not None and catalog is not None else ([], [])
        choices = {'anyOf': [{'$ref': '#/$defs/BoundIdOwner'}, {'$ref': '#/$defs/UnresolvedOwner'}]}
        if catalog is not None and not catalog.protocols:
            choices = {'$ref': '#/$defs/UnresolvedOwner'}
        schema['properties']['decisions'] = items._keyed([i.id for i in all_items], choices)
        if declarations is not None:
            _, projection = self.compile(declarations, bundle)
            _, mapping = atoms.verify_context(self.context, bundle, inventory)
            for item_id, cell_id in mapping.items():
                owner = projection['table_assignments'].get(cell_id)
                branch = {'$ref': '#/$defs/UnresolvedOwner'}
                if owner is not None and catalog.protocols:
                    scoped = deepcopy(bound)
                    for key, value in owner.items():
                        scoped['properties'][key]['enum'] = [value]
                    branch = {'anyOf': [scoped, branch]}
                schema['properties']['decisions']['properties'][item_id] = branch
        return quantities.prune_unused_definitions(schema)

    def render_bindings(self, bundle, inventory, catalog, *, declarations):
        _, projection = self.compile(declarations, bundle)
        _, mapping = atoms.verify_context(self.context, bundle, inventory)
        return '\n'.join([compact_prompt(previous.render_bindings(bundle, inventory, catalog), catalog.model_dump()),
            'FROZEN TABLE SCOPE PROPOSALS: '+canonical(projection['table_assignments']),
            'SOURCE ITEM TO EXACT TABLE CELL: '+canonical(mapping),
            'These are structural constraints on fallible earlier proposals. A table item may only bind to its declared cell owner. '
            'Use unresolved if that owner is scientifically wrong or missing. Never choose a nearby row or repair the frozen catalog.'])

    def bind(self, selection, declarations, relations, inventory, bundle):
        _, mapping = atoms.verify_context(self.context, bundle, inventory)
        compiled, source_projection = self.compile(declarations, bundle)
        owned, plan, proof = frozen.bind(selection, compiled, relations, inventory, bundle, catalog_adapter=self.Bridge)
        checks = []
        for item_id, cell_id in mapping.items():
            decision = selection.decisions[item_id]
            expected = source_projection['table_assignments'].get(cell_id)
            if decision.resolution == 'bound' and (expected is None or any(getattr(decision, k) != v for k, v in expected.items())):
                raise ValueError('staged_atom_result_table_owner_mismatch')
            checks.append(dict(item_id=item_id, cell_id=cell_id, resolution=decision.resolution,
                selected_owner=expected, source_structure_verified=True, scientific_ownership_verified=False))
        proof.update(source_choices_sha256=digest(declarations.model_dump()),
            source_atom_projection_sha256=digest(source_projection), source_atom_context_sha256=digest(self.context),
            table_owner_checks=checks)
        return owned, plan, proof

    def assemble(self, bundle, inventory, catalog, decisions, links, *, owner_plan, owner_declarations,
                 catalog_relations, source_declarations, owner_bindings, missing_item_ids=(), stage_failures=()):
        owned, expected, binding = self.bind(owner_bindings, source_declarations, catalog_relations, inventory, bundle)
        if owned != owner_declarations or owner_plan != expected:
            raise ValueError('staged_atom_owner_projection_changed')
        graph, coverage, proof = witnesses.assemble(bundle, inventory, catalog, decisions, links,
            owner_plan=owner_plan, owner_declarations=owned, catalog_relations=catalog_relations,
            missing_item_ids=missing_item_ids, stage_failures=stage_failures, catalog_adapter=self.Bridge)
        proof.update(schema='materials-source-item-assembly/4', frozen_owner_projection=binding,
            source_atom_context_sha256=digest(self.context), native_schema=self.NATIVE_SCHEMA)
        return graph, coverage, proof
