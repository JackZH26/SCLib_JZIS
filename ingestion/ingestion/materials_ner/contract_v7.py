"""Source extents and fit windows retain roles distinct from measurement conditions.

This aligns the proposal roles with the existing canonical conditions contract.
Historical v6 payloads remain frozen; no fields or relation kinds are added.
"""
from typing import Literal, get_args

from .contract_v6 import ConditionV6, StateV6, ExtractionV6


class ConditionV7(ConditionV6):
    role: Literal[tuple(get_args(ConditionV6.model_fields["role"].annotation)) + ("study_extent", "fit_window")]


class StateV7(StateV6):
    conditions: list[ConditionV7]


class ExtractionV7(ExtractionV6):
    schema_version: Literal["materials-ner/7"]
    states: list[StateV7]
