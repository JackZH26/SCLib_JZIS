"""Closed development-grammar interpretations, not reviewed scientific results."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, strict=True)


class QuerySpan(_Closed):
    raw_text: str = Field(min_length=1, max_length=2000)
    start: int = Field(ge=0, le=20000)
    end: int = Field(ge=1, le=20000)

    @model_validator(mode="after")
    def valid_span(self):
        if self.end <= self.start or self.end - self.start != len(self.raw_text):
            raise ValueError("Query span must retain exact original characters")
        return self


class FormulaNormalization(_Closed):
    version: Literal["formula-query/1.0.0"] = "formula-query/1.0.0"
    raw_formula: str = Field(min_length=1, max_length=200)
    normalized_formula: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["normalized", "unresolved"]
    reason_codes: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def coherent(self):
        if (self.status == "normalized") != (self.normalized_formula is not None):
            raise ValueError("Unresolved formula cannot assert a normalized identity")
        if self.status == "unresolved" and not self.reason_codes:
            raise ValueError("Unresolved formula requires a reason")
        return self


class QueryFormula(QuerySpan):
    normalization: FormulaNormalization

    @model_validator(mode="after")
    def raw_formula_matches(self):
        if self.normalization.raw_formula != self.raw_text:
            raise ValueError("Formula normalization must retain its original mention")
        return self


FormulaMention = QueryFormula


class QuantityConstraint(QuerySpan):
    field: Literal["tc_kelvin", "pressure_gpa"]
    relation: Literal["exact", "lt", "le", "gt", "ge", "interval"]
    value: float | None = Field(default=None, ge=0)
    lower: float | None = Field(default=None, ge=0)
    upper: float | None = Field(default=None, ge=0)
    unit: Literal["K", "GPa"]
    unit_basis: Literal["explicit", "explicit_ambient_reference"] = "explicit"

    @model_validator(mode="after")
    def coherent(self):
        if self.unit != {"tc_kelvin": "K", "pressure_gpa": "GPa"}[self.field]:
            raise ValueError("Quantity field and canonical unit conflict")
        if self.relation == "exact":
            valid = self.value is not None and self.lower is None and self.upper is None
        elif self.relation in {"lt", "le"}:
            valid = self.upper is not None and self.value is None and self.lower is None
        elif self.relation in {"gt", "ge"}:
            valid = self.lower is not None and self.value is None and self.upper is None
        else:
            valid = self.lower is not None and self.upper is not None and self.value is None and self.lower <= self.upper
        if not valid:
            raise ValueError("Quantity relation requires exact matching value/bound fields")
        if self.unit_basis == "explicit_ambient_reference" and (self.field != "pressure_gpa" or self.relation != "exact" or self.value != 0):
            raise ValueError("Ambient is an explicit reference, not an inferred zero")
        return self


class EvidenceConstraint(QuerySpan):
    field: Literal["knowledge_origin", "source_role", "experimental_outcome"]
    value: Literal["Observed", "Computed", "Inferred", "AI-Proposed", "Unknown", "primary", "cited", "positive_reported", "not_detected"]

    @model_validator(mode="after")
    def coherent(self):
        choices = {"knowledge_origin": {"Observed", "Computed", "Inferred", "AI-Proposed", "Unknown"},
                   "source_role": {"primary", "cited"}, "experimental_outcome": {"positive_reported", "not_detected"}}
        if self.value not in choices[self.field]:
            raise ValueError("Evidence category field/value mismatch")
        return self


class UnresolvedClause(QuerySpan):
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")


class ScientificQueryInterpretation(_Closed):
    version: Literal["scientific-query/1.0.0"] = "scientific-query/1.0.0"
    raw_query: str = Field(min_length=1, max_length=2000)
    normalized_query: str = Field(min_length=1, max_length=4000)
    language: Literal["en", "zh", "mixed"]
    intent: Literal["numerical", "mechanism", "mixed", "comparison", "general"]
    status: Literal["resolved", "clarification_required"]
    requested_fields: list[Literal["tc_kelvin", "pressure_gpa"]] = Field(default_factory=list, max_length=2)
    formulas: list[QueryFormula] = Field(default_factory=list, max_length=32)
    constraints: list[QuantityConstraint] = Field(default_factory=list, max_length=32)
    evidence_constraints: list[EvidenceConstraint] = Field(default_factory=list, max_length=32)
    unresolved_clauses: list[UnresolvedClause] = Field(default_factory=list, max_length=128)
    clarification_questions: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=8)
    scientific_acceptance: Literal[False] = False

    @field_validator("scientific_acceptance", mode="before")
    @classmethod
    def no_scientific_authority(cls, value):
        if value is not False:
            raise ValueError("Scientific acceptance must be the boolean false")
        return value

    @model_validator(mode="after")
    def faithful(self):
        spans = [*self.formulas, *self.constraints, *self.evidence_constraints, *self.unresolved_clauses]
        if any(self.raw_query[item.start:item.end] != item.raw_text for item in spans):
            raise ValueError("Interpretation spans must match the original query")
        unresolved = bool(self.unresolved_clauses) or any(item.normalization.status != "normalized" for item in self.formulas)
        if (self.status == "clarification_required") != unresolved or bool(self.clarification_questions) != unresolved:
            raise ValueError("Unresolved conditions require explicit clarification")
        if len(set(self.requested_fields)) != len(self.requested_fields):
            raise ValueError("Repeated requested field")
        return self
