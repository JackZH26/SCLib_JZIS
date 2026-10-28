"""Typed NER/10 bridge for source-compiled declarations, without a new worker.

Source quote selections survive the compact wire graph. Historical NER/9
types, default algorithms and their serialized projections remain unchanged.
"""
from copy import deepcopy
from typing import Literal

from pydantic import Field, create_model

from . import identity_stages as identity, catalog_stages as catalogs, item_stages as items
from . import item_ownership as owners
from .contract import StrictModel, Evidence
from .contract_v6 import ProcedureV6
from .contract_v9 import SampleV9
from .contract_v10 import StateV10, ExtractionV10
from .evidence import source_catalog, selected_quotes
from .validation import resolve_quote, resolve_evidence
from .contract_v11 import PositionedEvidence
from .wire import EvidenceReference, nested_model
from .wire_v10 import DetectionExtraction


class SourceQuote(StrictModel):
    block_id: str
    quote: str


class ExactReference(EvidenceReference):
    exact_quotes: list[SourceQuote] = Field(default_factory=list)


class AtomSample(nested_model('AtomSampleBody', SampleV9, set())):
    evidence: list[ExactReference]


class AtomState(nested_model('AtomStateBody', StateV10, set())):
    evidence: list[ExactReference]


class AtomProcedure(nested_model('AtomProcedureBody', ProcedureV6, set())):
    evidence: list[ExactReference]


class EntityCatalog(identity.EntityCatalog):
    schema_version: Literal['materials-source-entity-catalog/3']
    samples: list[AtomSample]
    states: list[AtomState]
    protocols: list[AtomProcedure]


DeclaredCondition = create_model('AtomDeclaredCondition', __base__=StrictModel,
    **items.copied_fields(StateV10.model_fields['conditions'].annotation.__args__[0], {'id'}))
DeclaredState = create_model('AtomDeclaredState', __base__=StrictModel,
    **items.copied_fields(AtomState, {'id', 'sample_id', 'conditions'}), conditions=(list[DeclaredCondition], ...))
DeclaredSample = create_model('AtomDeclaredSample', __base__=StrictModel,
    **items.copied_fields(AtomSample, {'id'}), states=(list[DeclaredState], ...))
DeclaredProcedure = create_model('AtomDeclaredProcedure', __base__=StrictModel,
    **items.copied_fields(AtomProcedure, {'id', 'context_uses'}))


class Declarations(catalogs.Declarations):
    schema_version: Literal['materials-source-declarations/3']
    samples: list[DeclaredSample]
    protocols: list[DeclaredProcedure]


class OwnedDeclarations(Declarations):
    schema_version: Literal['materials-owned-source-declarations/3']
    item_owners: dict[str, owners.BoundOwner | owners.UnresolvedOwner]
    additional_item_owners: list[owners.BoundOwner | owners.UnresolvedOwner]


class AtomExtraction(DetectionExtraction):
    schema_version: Literal['materials-source-atoms-graph/1']
    samples: list[AtomSample]
    states: list[AtomState]
    protocols: list[AtomProcedure]

    def expand(self, bundle):
        return expand_atom(self, bundle)


def expand_atom(original_graph, bundle, *, native_model=ExtractionV10, native_version='materials-ner/10', positioned=False):
    source = source_catalog(bundle); copy = original_graph.model_copy(deep=True)
    for sample in copy.samples:
        if sample.formula_unavailability is not None:
            sample.formula_unavailability.checked_block_ids = [source['blocks'][x]['block_id']
                for x in sample.formula_unavailability.checked_block_ids]
    # The shared expansion copies model-selected scientific fields only.
    # Remove the transport-only quote carrier before native validation.
    # DetectionExtraction excludes whole evidence objects itself.
    result = DetectionExtraction.expand(copy, bundle, canonical_model=native_model, canonical_version=native_version)
    blocks = {b.id: b for b in bundle.blocks}
    for kind in ('samples', 'states', 'protocols'):
        for original, expanded in zip(getattr(original_graph, kind), getattr(result, kind), strict=True):
            refs = []
            for ref in original.evidence:
                carriers = selected_quotes(source, ref.span_ids)
                quotes = [q.model_dump() for q in ref.exact_quotes] if ref.exact_quotes else carriers
                for quote in quotes:
                    if ref.exact_quotes:
                        block = blocks.get(quote['block_id'])
                        if block is None:
                            raise ValueError('staged_atom_exact_quote_block_missing')
                        binding = (PositionedEvidence if 'start_char' in quote else Evidence)(field='/', **quote)
                        start, end = resolve_evidence(block.text, binding)
                        if not any(c['block_id'] == block.id and max(start, c['start_char']) < min(end, c['end_char']) for c in carriers):
                            raise ValueError('staged_atom_exact_quote_carrier_mismatch')
                    native_quote = {k:v for k,v in quote.items() if k in {'block_id','quote','start_char','end_char'}}
                    cls = PositionedEvidence if 'start_char' in native_quote else Evidence
                    # Legacy span carriers must retain their quote-only serialized shape.
                    if not positioned: native_quote = {k:v for k,v in native_quote.items() if k in {'block_id','quote'}}; cls = Evidence
                    refs.extend(cls(**native_quote, field=field) for field in ref.fields)
            expanded.evidence = refs
    return native_model.model_validate(result.model_dump())

def from_projection(projection, bundle, *, declaration_model=Declarations, version='materials-source-declarations/3', positioned=False):
    graph = deepcopy(projection['graph']); source = source_catalog(bundle)
    blocks = {b.id: b for b in bundle.blocks}
    aliases = {v['block_id']: k for k, v in source['blocks'].items()}

    def evidence(rows):
        result = []
        for row in rows:
            binding = (PositionedEvidence if 'start_char' in row else Evidence).model_validate(row)
            start, end = resolve_evidence(blocks[row['block_id']].text, binding)
            ids = [sid for sid, span in source['spans'].items() if span['block_id'] == row['block_id']
                   and max(start, span['start_char']) < min(end, span['end_char'])]
            if not ids:
                raise ValueError('staged_atom_exact_quote_carrier_missing')
            result.append(dict(fields=[row['field']], span_ids=ids,
                exact_quotes=[{k:v for k,v in row.items() if k in ({'block_id','quote','start_char','end_char'} if positioned else {'block_id','quote'})}]))
        return result

    samples = []
    for sample in graph['samples']:
        states = []
        for state in graph['states']:
            if state['sample_id'] != sample['id']:
                continue
            state = deepcopy(state); state.pop('id'); state.pop('sample_id')
            state['evidence'] = evidence(state['evidence'])
            for condition in state['conditions']:
                condition.pop('id')
            states.append(state)
        sample.pop('id'); sample['states'] = states
        sample['evidence'] = evidence(sample['evidence'])
        if sample['formula_unavailability'] is not None:
            sample['formula_unavailability']['checked_block_ids'] = [aliases[k] for k in sample['formula_unavailability']['checked_block_ids']]
        samples.append(sample)
    protocols = []
    for protocol in graph['protocols']:
        protocol.pop('id'); protocol.pop('context_uses')
        protocol['evidence'] = evidence(protocol['evidence']); protocols.append(protocol)
    # Remove only the compiler's first-stage operational sentence. All authored
    # limitations and structured unresolved source fields stay in the receipt.
    limitations = graph['limitations'][:-1]
    if projection['unresolved_fields']:
        limitations += ['Source-atom compilation retains unresolved source fields; inspect catalog_projection before review.']
    return declaration_model.model_validate(dict(schema_version=version, work_id=bundle.work_id,
        processed_block_ids=[aliases[k] for k in graph['processed_block_ids']],
        unread_block_ids=[aliases[k] for k in graph['unread_block_ids']], limitations=limitations,
        samples=samples, protocols=protocols, additional_source_items=[], no_result_reason=None))


def declare(declarations):
    return catalogs.declare(declarations, catalog_model=EntityCatalog)


def check_declarations(declarations, inventory, bundle, max_items, *, strict_field_owner=True):
    return catalogs.check_declarations(declarations, inventory, bundle, max_items,
        strict_field_owner=strict_field_owner, catalog_model=EntityCatalog)


def project(declarations, relations, bundle):
    return catalogs.project(declarations, relations, bundle, catalog_model=EntityCatalog)


def body(declarations):
    return owners.body(declarations, model=Declarations, version='materials-source-declarations/3')


def project_owners(declarations, inventory, bundle):
    plan = owners.project(declarations, inventory, bundle, policy=owners.REFERENCE_POLICY,
        scientific=body(declarations), catalog_model=EntityCatalog)
    plan.update(schema='materials-source-item-owner-plan/4', policy=identity.POLICY, source_support_policy=owners.REFERENCE_POLICY)
    return plan


def assemble(bundle, inventory, catalog, decisions, links, **kwargs):
    return identity.assemble(bundle, inventory, catalog, decisions, links, graph_model=AtomExtraction, **kwargs)


def audit_catalog(catalog, inventory, bundle):
    return catalogs.audit_catalog(catalog, inventory, bundle, assemble=assemble)
