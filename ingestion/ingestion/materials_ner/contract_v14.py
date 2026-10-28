"""Source-supported extrapolation targets and inverse-square penetration depth.

No new nullable fields or entity types. Existing source bases and evidence
carry the extrapolation statement; dependencies retain the reported derivation.
This opt-in contract does not change any historical producer or receipt.
"""
from typing import Literal, get_args

from pydantic import model_validator

from .contract_v10 import ConditionV10
from .contract_v12 import ResultV12
from .contract_v13 import ExtractionV13, StateV13
from .quantities_v3 import ADDITIONS

VERSION = 'materials-ner/14'


class ConditionV14(ConditionV10):
    role: Literal[tuple(get_args(ConditionV10.model_fields['role'].annotation)) + ('extrapolation_target',)]

    @model_validator(mode='after')
    def extrapolation_basis(self):
        if self.role == 'extrapolation_target' and not (self.basis_raw and self.basis_raw.strip()):
            raise ValueError('extrapolation_target_requires_source_basis')
        return self


class StateV14(StateV13):
    conditions: list[ConditionV14]


class ResultV14(ResultV12):
    quantity_kind: Literal[tuple(get_args(ResultV12.model_fields['quantity_kind'].annotation)) + tuple(ADDITIONS)]

    @model_validator(mode='after')
    def explicit_inverse_depth_name(self):
        if self.quantity_kind in ADDITIONS and not (self.quantity_name_raw and self.quantity_name_raw.strip()):
            raise ValueError('adopted_quantity_requires_source_property_name')
        return self


class ExtractionV14(ExtractionV13):
    schema_version: Literal[VERSION]
    states: list[StateV14]
    results: list[ResultV14]
