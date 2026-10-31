"""Target-specific non-detections; legacy superconductivity-only receipts stay frozen."""
from typing import Literal

from pydantic import Field, model_validator

from .contract import Quantity, StrictModel
from .contract_v2 import TemperatureRole, TransitionStage
from .contract_v4 import ConditionalExistenceV4, NonDetectionV4
from .contract_v6 import ResultV6
from .contract_v7 import ExtractionV7

TARGET_OBSERVABLES = {
    "superconductivity": {"resistive_transition", "zero_resistance", "diamagnetic_signal", "heat_capacity_anomaly", "unspecified"},
    "supercurrent": {"supercurrent"},
    "josephson_phase_transition": {"zero_pi_transition"},
}


class DetectionSensitivity(StrictModel):
    role: Literal["measurement_step", "instrument_resolution", "detection_threshold", "noise_floor"]
    # The first source-backed extension is a current step in a junction paper.
    # Additional dimensions need their own source cases and unit semantics.
    quantity_kind: Literal["electric_current"]
    quantity: Quantity
    raw: str = Field(min_length=1)


class NonDetectionV8(NonDetectionV4):
    target: Literal["superconductivity", "supercurrent", "josephson_phase_transition"]
    observable: Literal["resistive_transition", "zero_resistance", "diamagnetic_signal", "heat_capacity_anomaly",
                        "unspecified", "supercurrent", "zero_pi_transition"]
    # IDs select conditions on this result's own state. Other state conditions
    # remain applicable context; geometry is not automatically a scan window.
    window_condition_ids: list[str] = Field(default_factory=list)
    sensitivities: list[DetectionSensitivity] = Field(default_factory=list)

    @model_validator(mode="after")
    def target_scope(self):
        if self.observable not in TARGET_OBSERVABLES[self.target]:
            raise ValueError("non_detection_target_observable_mismatch")
        if len(set(self.window_condition_ids)) != len(self.window_condition_ids):
            raise ValueError("non_detection_duplicate_window_reference")
        if (self.window_status == "reported") != bool(self.window_condition_ids):
            raise ValueError("non_detection_window_reference_status_mismatch")
        return self


class ResultV8(ResultV6):
    qualifiers: list[TransitionStage | ConditionalExistenceV4 | NonDetectionV8 | TemperatureRole] = Field(default_factory=list)

    @model_validator(mode="after")
    def negative_shape(self):
        negatives = [q for q in self.qualifiers if q.kind == "non_detection"]
        if self.quantity_kind == "non_detection":
            if len(negatives) != 1 or self.quantity.status != "not_applicable":
                raise ValueError("non_detection_single_qualifier_without_quantity_required")
            if negatives[0].target != "superconductivity" and any(q.kind == "conditional_existence" for q in self.qualifiers):
                raise ValueError("device_non_detection_cannot_imply_conditional_tc")
        elif negatives:
            raise ValueError("non_detection_qualifier_kind_mismatch")
        return self


class ExtractionV8(ExtractionV7):
    schema_version: Literal["materials-ner/8"]
    results: list[ResultV8]
