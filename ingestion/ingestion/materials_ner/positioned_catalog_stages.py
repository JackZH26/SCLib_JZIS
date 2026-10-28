"""Position-preserving catalog transport for native NER/11.

Table proofs copy source syntax only. Kind, criterion, applicability and
scientific ownership remain independently reviewable model proposals.
"""
from functools import partial
from typing import Literal

from pydantic import Field, JsonValue, create_model

from . import condition_catalog_stages as previous, catalog_stages as catalogs
from . import identity_stages as identity, item_ownership as owners, item_stages as items
from . import table_value_binding as values, table_ownership as tables
from .contract import StrictModel
from .contract_v11 import ExtractionV11, PositionedEvidence


class PositionedQuote(previous.SourceQuote):
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)


class ExactReference(previous.ExactReference):
    exact_quotes: list[previous.SourceQuote | PositionedQuote] = Field(default_factory=list)


AtomSample = create_model('PositionedAtomSample', __base__=previous.AtomSample,
    evidence=(list[ExactReference], ...))
AtomState = create_model('PositionedAtomState', __base__=previous.AtomState,
    evidence=(list[ExactReference], ...))
AtomProcedure = create_model('PositionedAtomProcedure', __base__=previous.AtomProcedure,
    evidence=(list[ExactReference], ...))


class EntityCatalog(previous.EntityCatalog):
    schema_version: Literal['materials-source-entity-catalog/4']
    samples: list[AtomSample]
    states: list[AtomState]
    protocols: list[AtomProcedure]


DeclaredState = create_model('PositionedDeclaredState', __base__=previous.DeclaredState,
    evidence=(list[ExactReference], ...))
DeclaredSample = create_model('PositionedDeclaredSample', __base__=previous.DeclaredSample,
    evidence=(list[ExactReference], ...), states=(list[DeclaredState], ...))
DeclaredProcedure = create_model('PositionedDeclaredProcedure', __base__=previous.DeclaredProcedure,
    evidence=(list[ExactReference], ...))


class Declarations(previous.Declarations):
    schema_version: Literal['materials-source-declarations/4']
    samples: list[DeclaredSample]
    protocols: list[DeclaredProcedure]


class OwnedDeclarations(Declarations):
    schema_version: Literal['materials-owned-source-declarations/4']
    item_owners: dict[str, owners.BoundOwner | owners.UnresolvedOwner]
    additional_item_owners: list[owners.BoundOwner | owners.UnresolvedOwner]


class TableValueSource(StrictModel):
    result_id: str
    cell: dict[str, JsonValue]
    binding: dict[str, JsonValue]


class AtomExtraction(previous.AtomExtraction):
    schema_version: Literal['materials-source-atoms-graph/2']
    samples: list[AtomSample]
    states: list[AtomState]
    protocols: list[AtomProcedure]
    table_value_sources: list[TableValueSource] = Field(default_factory=list)

    def expand(self, bundle):
        native = previous.expand_atom(self, bundle, native_model=ExtractionV11,
            native_version='materials-ner/11', positioned=True)
        sources = {s.result_id:s for s in self.table_value_sources}
        if len(sources) != len(self.table_value_sources) or set(sources) != {r.id for r in native.results}:
            raise ValueError('staged_positioned_table_proof_not_closed')
        for result in native.results:
            source = sources[result.id]
            proof = values.verify_binding(source.binding, bundle,
                dict(policy=tables.POLICY, cells=[source.cell]))
            if result.quantity.model_dump() != proof['quantity'] or result.quantity_name_raw != proof['quantity_name_raw']:
                raise ValueError('staged_positioned_table_value_changed')
            # Preserve authored witnesses; append exact compiler witnesses.
            # The transcript and full graph retain both for audit and revision.
            result.evidence.extend(PositionedEvidence.model_validate(e) for e in proof['evidence'])
        return ExtractionV11.model_validate(native.model_dump())


from_projection = partial(previous.from_projection, declaration_model=Declarations,
    version='materials-source-declarations/4', positioned=True)
declare = partial(catalogs.declare, catalog_model=EntityCatalog)
check_declarations = partial(catalogs.check_declarations, catalog_model=EntityCatalog)
project = partial(catalogs.project, catalog_model=EntityCatalog)
body = partial(owners.body, model=Declarations, version='materials-source-declarations/4')


def project_owners(declarations, inventory, bundle):
    plan = owners.project(declarations, inventory, bundle, policy=owners.REFERENCE_POLICY,
        scientific=body(declarations), catalog_model=EntityCatalog)
    plan.update(schema='materials-source-item-owner-plan/4', policy=identity.POLICY,
        source_support_policy=owners.REFERENCE_POLICY)
    return plan


def assemble(bundle, inventory, catalog, decisions, links, **kwargs):
    return identity.assemble(bundle, inventory, catalog, decisions, links,
        graph_model=AtomExtraction, **kwargs)


def audit_catalog(catalog, inventory, bundle):
    return catalogs.audit_catalog(catalog, inventory, bundle, assemble=assemble)
