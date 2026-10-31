"""Opt-in, source-tested device descriptors and fit-intersection definitions.

The existing state/definition objects remain sparse. A reported displacement
field is deliberately distinct from a gate voltage or an SI electric field.
The source basis identifies what was measured/inferred; no angle symmetry,
preparation-to-measurement equality or field convention is inferred here.
"""
from typing import Literal, get_args

from pydantic import model_validator

from .contract_v14 import ConditionV14, StateV14, ResultV14, ExtractionV14
from .contract_v5 import ResultDefinitionV5

VERSION = 'materials-ner/15'
DESCRIPTORS = ('twist_angle', 'reported_displacement_field')
INTERSECTION = 'linear_fit_intersection'


class ConditionV15(ConditionV14):
    kind: Literal[tuple(get_args(ConditionV14.model_fields['kind'].annotation)) + DESCRIPTORS]

    @model_validator(mode='after')
    def source_descriptor_basis(self):
        if self.kind in DESCRIPTORS and not (self.basis_raw and self.basis_raw.strip()):
            raise ValueError('device_descriptor_requires_source_basis')
        return self


class DefinitionV15(ResultDefinitionV5):
    criterion: Literal[tuple(get_args(ResultDefinitionV5.model_fields['criterion'].annotation)) + (INTERSECTION,)]

    @model_validator(mode='after')
    def fit_definition(self):
        if self.criterion == INTERSECTION:
            if not (self.criterion_raw and self.criterion_raw.strip()):
                raise ValueError('linear_fit_intersection_requires_source_definition')
            if self.parameters:
                raise ValueError('linear_fit_intersection_has_no_resistance_fraction')
        return self


class StateV15(StateV14):
    conditions: list[ConditionV15]


class ResultV15(ResultV14):
    definition: DefinitionV15


class ExtractionV15(ExtractionV14):
    schema_version: Literal[VERSION]
    states: list[StateV15]
    results: list[ResultV15]
