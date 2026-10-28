"""Exact source occurrence selectors for repeated literals such as table units.

Coordinates are zero-based Unicode character offsets in one immutable source
block, with an exclusive end. They select evidence, not scientific meaning.
Legacy quote-only bindings remain valid only when their quote is unique.
Earlier extraction contracts and serialized evidence shapes stay unchanged.
"""
from typing import Literal

from pydantic import Field, create_model, model_validator

from .contract import Evidence
from .contract_v10 import ExtractionV10


class PositionedEvidence(Evidence):
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode='after')
    def ordered(self):
        if self.end_char <= self.start_char:
            raise ValueError('evidence_position_empty_or_reversed')
        return self


def positioned_entity(name, collection):
    base = ExtractionV10.model_fields[collection].annotation.__args__[0]
    return create_model(name, __base__=base,
        evidence=(list[Evidence | PositionedEvidence], ...))


SampleV11 = positioned_entity('SampleV11', 'samples')
StateV11 = positioned_entity('StateV11', 'states')
ProcedureV11 = positioned_entity('ProcedureV11', 'protocols')
ResultV11 = positioned_entity('ResultV11', 'results')
SampleRelationV11 = positioned_entity('SampleRelationV11', 'sample_relations')
ConditionSupportV11 = positioned_entity('ConditionSupportV11', 'condition_supports')


class ExtractionV11(ExtractionV10):
    schema_version: Literal['materials-ner/11']
    samples: list[SampleV11]
    states: list[StateV11]
    protocols: list[ProcedureV11]
    results: list[ResultV11]
    sample_relations: list[SampleRelationV11]
    condition_supports: list[ConditionSupportV11]
