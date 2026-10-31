"""Versioned NER/9 stages and lossless owner-attribution witness transport.

Result identifiers remain derived from source items. Missing chemical identity
is retained as scoped reading metadata, not filled by a nearby material. The
adapter reuses existing algorithms with explicit types, so old and new jobs can
run concurrently without changing historical schemas or projection behavior.
"""
from copy import deepcopy
from typing import Literal

from pydantic import create_model, model_validator

from . import catalog_stages as catalogs, item_stages as items, item_ownership as owners
from .contract import StrictModel, digest
from .contract_v9 import SampleV9
from .evidence import source_catalog, selected_quotes
from .wire_v12 import IdentitySample, IdentityExtraction, IDENTITY_RULES

WORKFLOW = 'source_item_stages_v3'
OUTPUT_FORMAT = 'materials-source-item-transcript/3'
POLICY = 'source_item_owners_identity_v4'
PROMPT_VERSION = 'materials-source-item-owner-prompt/4.0.0'


class EntityCatalog(items.EntityCatalog):
    schema_version: Literal['materials-source-entity-catalog/2']
    samples: list[IdentitySample]

    @model_validator(mode='after')
    def formula_shapes(self):
        for sample in self.samples:
            SampleV9.formula_shape(sample)
        return self


DeclaredIdentitySample = create_model('DeclaredIdentitySample', __base__=StrictModel,
    **items.copied_fields(IdentitySample, {'id'}), states=(list[catalogs.DeclaredState], ...))


class Declarations(catalogs.Declarations):
    schema_version: Literal['materials-source-declarations/2']
    samples: list[DeclaredIdentitySample]


class OwnedDeclarations(Declarations):
    schema_version: Literal['materials-owned-source-declarations/2']
    item_owners: dict[str, owners.BoundOwner | owners.UnresolvedOwner]
    additional_item_owners: list[owners.BoundOwner | owners.UnresolvedOwner]


Relations = catalogs.Relations
relation_schema = catalogs.relation_schema
render_relations = catalogs.render_relations


def declare(declarations):
    return catalogs.declare(declarations, catalog_model=EntityCatalog)


def check_declarations(declarations, inventory, bundle, max_items, *, strict_field_owner=True):
    return catalogs.check_declarations(declarations, inventory, bundle, max_items,
        strict_field_owner=strict_field_owner, catalog_model=EntityCatalog)


def project(declarations, relations, bundle):
    return catalogs.project(declarations, relations, bundle, catalog_model=EntityCatalog)


def declaration_schema(bundle=None):
    schema = catalogs.declaration_schema(bundle, model=Declarations)
    base = schema['$defs']['DeclaredIdentitySample']
    reported, missing = deepcopy(base), deepcopy(base)
    reported['properties']['formula_raw'] = {'type': 'string', 'minLength': 1}
    reported['properties']['formula_unavailability'] = {'type': 'null'}
    missing['properties']['formula_raw'] = {'type': 'null'}
    missing['properties']['formula_unavailability'] = {'$ref': '#/$defs/FormulaUnavailability'}
    missing['properties']['composition_basis'] = {'type': 'string', 'enum': ['unresolved']}
    schema['$defs']['DeclaredIdentitySample'] = {'anyOf': [reported, missing]}
    if bundle:
        schema['$defs']['FormulaUnavailability']['properties']['checked_block_ids']['items']['enum'] = list(source_catalog(bundle)['blocks'])
    return schema


def body(declarations):
    return owners.body(declarations, model=Declarations, version='materials-source-declarations/2')


def project_owners(declarations, inventory, bundle, *, policy=POLICY):
    if policy != POLICY:
        raise ValueError('staged_item_owner_policy_unknown')
    plan = owners.project(declarations, inventory, bundle, policy=owners.REFERENCE_POLICY,
        scientific=body(declarations), catalog_model=EntityCatalog)
    plan.update(schema='materials-source-item-owner-plan/4', policy=POLICY,
        source_support_policy=owners.REFERENCE_POLICY)
    return plan


def owner_schema(bundle=None, inventory=None):
    return owners.declaration_schema(bundle, inventory, model=OwnedDeclarations,
        inherited=declaration_schema(bundle))


def assemble(bundle, inventory, catalog, decisions, links, *, owner_plan=None,
             missing_item_ids=(), stage_failures=(), graph_model=IdentityExtraction):
    augmented = {key: value.model_copy(deep=True) for key, value in decisions.items()}
    ledger = []
    if owner_plan is not None:
        if (owner_plan['policy'] != POLICY
                or owner_plan['bundle_sha256'] != digest(bundle.model_dump())
                or owner_plan['inventory_sha256'] != digest(inventory.model_dump())):
            raise ValueError('staged_attribution_witness_plan_mismatch')
        group = items.ItemGroup(schema_version='materials-source-item-group/1',
            work_id=bundle.work_id, decisions=augmented)
        owners.check_group(group, owner_plan)
        source = source_catalog(bundle)
        for key, decision in augmented.items():
            if decision.decision != 'emitted':
                continue
            attribution = owner_plan['items'][key]['attribution']
            selected_quotes(source, attribution['source_span_ids'])
            fields = ['/source_role']
            if attribution['cited_source_raw'] is not None:
                fields.append('/cited_source_raw')
            before = decision.observation.result.model_dump()
            ref = {'fields': fields, 'span_ids': attribution['source_span_ids']}
            after = deepcopy(before)
            if ref not in after['evidence']:
                after['evidence'].append(ref)
            decision.observation.result = type(decision.observation.result).model_validate(after)
            # Prove that selected owners, values, definitions and other evidence
            # were retained. The only change is this recorded evidence append.
            expected = deepcopy(decisions[key].model_dump())
            expected['observation']['result']['evidence'] = after['evidence']
            if decision.model_dump() != expected:
                raise ValueError('staged_attribution_transport_changed_scientific_payload')
            ledger.append(dict(item_id=key, result_id=items.result_id(key),
                fields=fields, source_span_ids=attribution['source_span_ids'],
                appended=after != before))
    graph, coverage, proof = items.assemble(bundle, inventory, catalog, augmented, links,
        missing_item_ids=missing_item_ids, stage_failures=stage_failures, graph_model=graph_model)
    proof.update(schema='materials-source-item-assembly/2',
        decisions_sha256=digest({key: value.model_dump() for key, value in decisions.items()}),
        attribution_witness_transport=dict(schema='materials-attribution-witness-transport/1',
            owner_plan_sha256=digest(owner_plan) if owner_plan is not None else None,
            augmented_decisions_sha256=digest({key: value.model_dump() for key, value in augmented.items()}),
            entries=ledger, scientific_payload_unchanged=True, scientific_attribution_verified=False))
    return graph, coverage, proof


def audit_catalog(catalog, inventory, bundle):
    return catalogs.audit_catalog(catalog, inventory, bundle, assemble=assemble)


IDENTITY_STAGE_RULES = IDENTITY_RULES.replace(
    'Use schema_version materials-ner-shared/8. ',
    'Use the requested stage schema. ')
ATTRIBUTION_RULES = '''The program preserves the frozen attribution source spans
as result-field evidence. This carries your proposal only; it does not determine
authorship, resolve a specimen, or establish scientific validity. Keep all other
field evidence and separate each result's actual conditions. Do not turn a
zero-temperature limit into a measured zero-temperature state. Paired component
notation can report component values as well as their ratio; decide from the
literal definitions and retain each supported assertion. Do not derive new
values from a ratio or erase explicitly reported components merely because '/'
appears in the notation. Unsupported interpretation stays unresolved.
'''
PROMPT_HASH = digest(dict(version=PROMPT_VERSION, owner=owners.REFERENCE_PROMPT_HASH,
    identity=IDENTITY_STAGE_RULES, transport=ATTRIBUTION_RULES))


def prompt_identity(policy):
    if policy != POLICY:
        raise ValueError('staged_item_owner_policy_unknown')
    return PROMPT_VERSION, PROMPT_HASH


def render_declarations(bundle, inventory, *, policy=POLICY):
    prompt_identity(policy)
    return '\n'.join([owners.REFERENCE_RULES, catalogs.render_declarations(bundle, inventory),
        IDENTITY_STAGE_RULES, ATTRIBUTION_RULES])


def render_items(bundle, inventory, catalog, item_ids, plan):
    return owners.render_items(bundle, inventory, catalog, item_ids, plan)+'\n'+ATTRIBUTION_RULES


class Ownership:
    """Explicit adapter namespace; no historical module globals are modified."""
    POLICIES = frozenset({POLICY})
    Declarations = OwnedDeclarations
    body = staticmethod(body)
    project = staticmethod(project_owners)
    declaration_schema = staticmethod(owner_schema)
    check_group = staticmethod(owners.check_group)
    item_schema = staticmethod(owners.item_schema)
    prompt_identity = staticmethod(prompt_identity)
    render_declarations = staticmethod(render_declarations)
    render_items = staticmethod(render_items)
