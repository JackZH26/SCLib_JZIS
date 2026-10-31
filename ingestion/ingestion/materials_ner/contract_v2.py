"""Sparse scientific qualifiers for the second empirical Materials contract.

The v1 models remain unchanged for historical receipts. These are proposals,
not new canonical tables or automatic sample/measurement identities.
"""
from typing import Literal

from pydantic import Field

from .contract import Extraction, Protocol, Quantity, Result, Sample, StrictModel


class TransitionStage(StrictModel):
    kind: Literal["transition_stage"]
    stage: Literal["primary", "secondary", "other"]
    raw: str = Field(min_length=1)


class ConditionalExistence(StrictModel):
    kind: Literal["conditional_existence"]
    condition: Literal["if_superconducting"]
    raw: str = Field(min_length=1)


class NonDetection(StrictModel):
    kind: Literal["non_detection"]
    target: Literal["superconductivity"]
    observable: Literal["resistive_transition", "zero_resistance", "diamagnetic_signal",
                        "heat_capacity_anomaly", "unspecified"]
    # Not observed over a window does not establish absence at all temperatures.
    existence: Literal["not_established"]
    raw: str = Field(min_length=1)


class TemperatureRole(StrictModel):
    kind: Literal["temperature_role"]
    role: Literal["system_transition", "component_model_parameter"]
    raw: str = Field(min_length=1)


class FormulaAssertion(StrictModel):
    formula_raw: str = Field(min_length=1)
    basis: Literal["nominal", "measured", "refined", "calculation_input", "unresolved"]
    context_raw: str | None


class SampleV2(Sample):
    # The existing formula_raw is the literal display assertion, never a
    # resolved canonical composition. Additional source assertions preserve
    # alternate bases or conflicting notation; omit this list when unnecessary.
    additional_formula_assertions: list[FormulaAssertion] = Field(default_factory=list)


class ProtocolParameter(StrictModel):
    kind: Literal["frequency", "magnetic_flux_density", "magnetic_field_strength",
                  "coulomb_pseudopotential"]
    name_raw: str = Field(min_length=1)
    quantity: Quantity


class ProtocolV2(Protocol):
    method_class: Literal["resistivity", "magnetization", "specific_heat", "tunneling",
                          "muon_spin", "calculation", "other", "unspecified"] = "unspecified"
    parameters: list[ProtocolParameter] = Field(default_factory=list)


class ResultV2(Result):
    qualifiers: list[TransitionStage | ConditionalExistence | NonDetection | TemperatureRole] = Field(default_factory=list)


class ExtractionV2(Extraction):
    schema_version: Literal["materials-ner/2"]
    samples: list[SampleV2]
    protocols: list[ProtocolV2]
    results: list[ResultV2]
