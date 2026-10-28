"""Keep conditional transition bounds distinct from observed measurement windows."""
from typing import Literal

from pydantic import Field

from .contract import Quantity
from .contract_v2 import ConditionalExistence,NonDetection,TemperatureRole,TransitionStage
from .contract_v3 import ExtractionV3,ResultV3


class ConditionalExistenceV4(ConditionalExistence):
    # An author's conditional bound, never an observed point Tc or scan extent.
    tc_bound: Quantity | None = None


class NonDetectionV4(NonDetection):
    window_status: Literal["reported","not_reported_in_supplied_source","not_accessible","unresolved"]


class ResultV4(ResultV3):
    qualifiers: list[TransitionStage | ConditionalExistenceV4 | NonDetectionV4 | TemperatureRole] = Field(default_factory=list)


class ExtractionV4(ExtractionV3):
    schema_version: Literal["materials-ner/4"]
    results: list[ResultV4]
