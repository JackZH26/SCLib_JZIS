"""Retain a reported magnetic field without inferring its electromagnetic convention.

H expressed in tesla is common source notation, but does not independently
establish B or mu0 H. This sparse condition kind preserves the existing raw
basis and quantity. It has no canonical numeric normalization or ML feature.
All earlier contracts remain unchanged.
"""
from typing import Literal, get_args
from pydantic import model_validator

from .contract_v7 import ConditionV7, StateV7
from .contract_v9 import ExtractionV9


class ConditionV10(ConditionV7):
    kind: Literal[tuple(get_args(ConditionV7.model_fields['kind'].annotation)) + ('reported_magnetic_field',)]

    @model_validator(mode='after')
    def unresolved_field_basis(self):
        if self.kind == 'reported_magnetic_field' and not (self.basis_raw and self.basis_raw.strip()):
            raise ValueError('reported_magnetic_field_requires_source_basis')
        return self


class StateV10(StateV7):
    conditions: list[ConditionV10]


class ExtractionV10(ExtractionV9):
    schema_version: Literal['materials-ner/10']
    states: list[StateV10]
