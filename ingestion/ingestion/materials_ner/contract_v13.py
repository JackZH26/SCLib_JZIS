"""Pressure declarations aligned with canonical materials-conditions/2.

An explicit ambient statement is qualitative unless the source also supplies a
numeric pressure. Existing condition quantities and their roles remain intact.
"""
from typing import Literal

from pydantic import Field, model_validator

from .contract import StrictModel
from .contract_v11 import StateV11
from .contract_v12 import ExtractionV12

VERSION = 'materials-ner/13'


class PressureDeclaration(StrictModel):
    availability: Literal['reported', 'not_reported', 'not_extracted', 'not_accessible',
                          'ambiguous', 'conflicted', 'not_applicable']
    regime: Literal['explicit_ambient', 'nonambient', 'unknown']
    condition_id: str | None = Field(min_length=1, max_length=100)
    basis_raw: str | None = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def supported_declaration(self):
        if self.regime != 'unknown' and not (self.basis_raw and self.basis_raw.strip()):
            raise ValueError('pressure_regime_requires_source_basis')
        if self.availability != 'reported' and self.regime != 'unknown':
            raise ValueError('unreported_pressure_regime_must_be_unknown')
        if self.availability == 'reported' and self.condition_id is None and self.regime != 'explicit_ambient':
            raise ValueError('reported_numeric_pressure_requires_condition')
        return self


class StateV13(StateV11):
    pressure: PressureDeclaration

    @model_validator(mode='after')
    def pressure_condition(self):
        declaration = self.pressure
        if declaration.condition_id is not None:
            matches = [c for c in self.conditions if c.id == declaration.condition_id]
            if len(matches) != 1 or matches[0].kind != 'pressure' or matches[0].role not in {'measurement', 'simulation'}:
                raise ValueError('pressure_condition_reference_invalid')
            if matches[0].quantity.status != declaration.availability:
                raise ValueError('pressure_condition_availability_mismatch')
        return self


class ExtractionV13(ExtractionV12):
    schema_version: Literal[VERSION]
    states: list[StateV13]
