"""Machine-extraction report DTOs, never scientific or training approval."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class ReportQuantity(_Closed):
    status: Literal["parsed", "unreported", "invalid"]
    relation: Literal["exact", "lt", "le", "gt", "ge", "interval", "unreported"]
    value: float | None
    lower: float | None
    upper: float | None
    uncertainty: float | None
    approximate: bool
    unit: Literal["K", "GPa"]
    unit_basis: Literal["explicit", "field_schema_assumption", "endpoint_units", "unreported", "explicit_ambient_reference"]
    uncertainty_interpretation: Literal["unspecified"] | None

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "unreported" and (self.relation != "unreported" or any(value is not None for value in
                (self.value, self.lower, self.upper, self.uncertainty))):
            raise ValueError("Unreported quantity cannot supply a value")
        if self.status != "parsed":
            return self
        if self.relation == "exact":
            valid = self.value is not None and self.lower is None and self.upper is None
        elif self.relation == "interval":
            valid = self.value is None and self.lower is not None and self.upper is not None and self.lower <= self.upper and self.uncertainty is None
        elif self.relation in {"gt", "ge"}:
            valid = self.value is None and self.lower is not None and self.upper is None and self.uncertainty is None
        elif self.relation in {"lt", "le"}:
            valid = self.value is None and self.lower is None and self.upper is not None and self.uncertainty is None
        else:
            valid = False
        if not valid or self.uncertainty is not None and self.uncertainty < 0:
            raise ValueError("Parsed quantity requires its original exact relation shape")
        if (self.uncertainty is None) != (self.uncertainty_interpretation is None):
            raise ValueError("Reported uncertainty has unspecified statistical interpretation")
        return self


class ReportPressure(ReportQuantity):
    pressure_state: Literal["explicit_ambient", "reported", "not_reported", "ambiguous"]


class ReportClassification(_Closed):
    knowledge_origin: Literal["Observed", "Computed", "Inferred", "AI-Proposed", "Unknown"]
    classification_status: Literal["resolved", "unknown", "conflicted"]
    source_role: Literal["primary", "cited", "unknown", "conflicted"]


class ReportContext(_Closed):
    tc_criterion: str | None = Field(max_length=160)
    sample_label: str | None = Field(max_length=160)
    sample_form: str | None = Field(max_length=160)
    structure_phase: str | None = Field(max_length=160)
    measurement_method: str | None = Field(max_length=160)


class ScientificQueryResult(_Closed):
    version: Literal["scientific-query-result/1.0.0"] = "scientific-query-result/1.0.0"
    result_id: str = Field(pattern=r"^legacy-result:[0-9a-f]{64}$")
    record_index: int = Field(ge=0, le=999)
    formula: str = Field(min_length=1, max_length=200)
    family: str | None = Field(max_length=160)
    tc: ReportQuantity
    pressure: ReportPressure
    minimum_temperature: ReportQuantity
    result_classification: ReportClassification
    outcome_state: Literal["positive_reported", "not_detected", "unspecified", "unresolved", "conflicted"]
    reported_context: ReportContext
    warning_codes: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")]] = Field(max_length=40)
    scientific_acceptance: Literal[False] = False
    ml_training_eligible: Literal[False] = False
    detection_adequacy_verified: Literal[False] = False

    @field_validator("scientific_acceptance", "ml_training_eligible", "detection_adequacy_verified", mode="before")
    @classmethod
    def no_scientific_authority(cls, value):
        if value is not False:
            raise ValueError("Scientific authority flags must be the boolean false")
        return value

    @model_validator(mode="after")
    def units_match_fields(self):
        if self.tc.unit != "K" or self.minimum_temperature.unit != "K" or self.pressure.unit != "GPa":
            raise ValueError("Scientific report units must match their quantity fields")
        return self
