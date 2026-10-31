"""Source-tested sparse conditions; historical proposal contracts stay frozen."""
from typing import Literal, get_args

from .contract import Condition, Protocol, Result, State
from .contract_v2 import ExtractionV2, ProtocolParameter, ProtocolV2, ResultV2


ConditionKind = Literal[tuple(get_args(Condition.model_fields["kind"].annotation))+("radius",)]
ResultKind = Literal[tuple(get_args(Result.model_fields["quantity_kind"].annotation))+(
    "gl_parameter","superconducting_layer_thickness","electronic_dos_per_atom")]
CriterionKind = Literal[tuple(get_args(Protocol.model_fields["criterion"].annotation))+("resistance_fraction",)]


class ConditionV3(Condition):
    kind: ConditionKind
    # This describes the extent of the *measurement*, not a Tc bound.
    # None is used outside detection windows; unknown direction is explicit.
    window_position: Literal["lower_limit","upper_limit","interval","unspecified"] | None = None


class StateV3(State):
    conditions: list[ConditionV3]


class ProtocolParameterV3(ProtocolParameter):
    kind: Literal["frequency","magnetic_flux_density","magnetic_field_strength",
                  "coulomb_pseudopotential","resistance_fraction"]


class ProtocolV3(ProtocolV2):
    criterion: CriterionKind
    parameters: list[ProtocolParameterV3]


class ResultV3(ResultV2):
    quantity_kind: ResultKind


class ExtractionV3(ExtractionV2):
    schema_version: Literal["materials-ner/3"]
    states: list[StateV3]
    protocols: list[ProtocolV3]
    results: list[ResultV3]
