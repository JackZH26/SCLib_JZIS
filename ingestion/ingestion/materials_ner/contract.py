"""Typed extraction contract; source values precede deterministic normalization.

This is an additive proposal contract, not a change to frozen rv2/ML v4.
The model never assigns canonical material IDs, acceptance, or ML eligibility.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Evidence(StrictModel):
    block_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    # JSON pointer relative to the containing sample/state/protocol/result.
    field: str = Field(pattern=r"^/")


class Uncertainty(StrictModel):
    kind: Literal["standard_deviation", "standard_error", "confidence_interval",
                  "resolution", "reported_unspecified"]
    minus: float = Field(ge=0)
    plus: float = Field(ge=0)
    level: float | None = Field(default=None, gt=0, lt=1)
    raw: str


class Quantity(StrictModel):
    status: Literal["reported", "not_reported", "not_accessible", "not_extracted",
                    "ambiguous", "conflicted", "not_applicable"]
    raw: str | None = None
    relation: Literal["exact", "interval", "lt", "le", "gt", "ge"] | None = None
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str | None = Field(default=None, description=(
        "Source unit for dimensional values. Use '1' for a dimensionless quantity, "
        "which does not imply that the paper printed a unit. A conflicted raw quantity "
        "may preserve its known unit without choosing a number."))
    approximate: bool = False
    uncertainty: Uncertainty | None = None

    @model_validator(mode="after")
    def shape(self):
        supplied = {name for name in ("value", "lower", "upper")
                    if getattr(self, name) is not None}
        if self.status != "reported":
            if supplied or self.relation or self.uncertainty:
                raise ValueError("unresolved quantity cannot carry a selected numeric value")
            return self
        expected = {"exact": {"value"}, "interval": {"lower", "upper"},
                    "lt": {"upper"}, "le": {"upper"}, "gt": {"lower"}, "ge": {"lower"}}
        if supplied != expected.get(self.relation) or not self.raw or not self.unit:
            raise ValueError("reported quantity needs a complete mutually exclusive shape and raw token")
        if self.relation == "interval" and self.lower > self.upper:
            raise ValueError("reversed quantity interval")
        return self


class Isotope(StrictModel):
    element: str = Field(pattern=r"^[A-Z][a-z]?$")
    mass_number: int = Field(gt=0)
    fraction: Quantity


class CompositionVariable(StrictModel):
    symbol: str
    site: str | None = None
    basis: Literal["nominal", "measured", "refined", "calculation_input", "unresolved"]
    amount: Quantity


class Sample(StrictModel):
    id: str
    label: str | None
    formula_raw: str
    composition_basis: Literal["nominal", "measured", "refined", "calculation_input", "unresolved"]
    identity_resolution: Literal["source_scoped", "unresolved", "conflicted"]
    target_kind: Literal["bulk", "film", "interface", "device", "phase", "component",
                         "calculation_model", "unresolved"]
    form_raw: str | None
    substrate_raw: str | None
    isotopes: list[Isotope]
    variables: list[CompositionVariable]
    evidence: list[Evidence]


class Condition(StrictModel):
    kind: Literal["pressure", "temperature", "magnetic_flux_density", "magnetic_field_strength",
                  "mu0_h", "thickness", "strain", "carrier_density", "gate_voltage", "delay"]
    role: Literal["measurement", "synthesis", "simulation", "detection_window", "pump", "unknown"]
    quantity: Quantity
    orientation_raw: str | None
    basis_raw: str | None


class State(StrictModel):
    id: str
    sample_id: str
    label: str | None
    conditions: list[Condition]
    preparation_raw: str | None
    evidence: list[Evidence]


class Protocol(StrictModel):
    id: str
    method: str | None
    observable: str | None
    criterion: Literal["onset", "midpoint", "zero_resistance", "offset",
                       "diamagnetic_onset", "heat_capacity_anomaly", "gap_closure",
                       "bkt", "fit_parameter", "not_applicable", "unspecified"]
    criterion_raw: str | None
    details_raw: str | None
    evidence: list[Evidence]


class Dependency(StrictModel):
    result_id: str
    relation: Literal["derived_from", "same_measurement", "compares_with"]


class Result(StrictModel):
    id: str
    sample_id: str
    state_id: str
    protocol_id: str
    quantity_kind: Literal["tc", "model_temperature_scale", "critical_pressure", "hc2",
                           "gap_energy", "electron_phonon_lambda", "omega_log",
                           "superfluid_stiffness", "debye_temperature",
                           "magnetic_transition_temperature", "heat_capacity_maximum_temperature",
                           "hc2_field_strength", "pauli_limit_flux_density",
                           "hc2_flux_density_slope", "hc2_field_strength_slope",
                           "tc_flux_density_slope", "tc_field_strength_slope",
                           "penetration_depth", "coherence_length", "crystalline_domain_size",
                           "charge_gap_energy", "sommerfeld_coefficient_molar",
                           "lattice_heat_capacity_beta_molar", "heat_capacity_jump_over_tc_molar",
                           "normalized_heat_capacity_jump", "heat_capacity_fraction",
                           "lattice_strain", "relative_debye_temperature_change",
                           "gap_amplitude_ratio", "pairing_component_fraction",
                           "surface_resistance", "quality_factor", "nmr_relaxation_power_law_exponent",
                           "non_detection", "unmapped"]
    quantity_name_raw: str | None = None
    quantity: Quantity
    origin: Literal["observed", "computed", "model_derived", "unknown"]
    source_role: Literal["primary", "cited", "unknown"]
    component_raw: str | None
    interpretation_raw: str | None
    cited_source_raw: str | None
    dependencies: list[Dependency]
    evidence: list[Evidence]


class Extraction(StrictModel):
    schema_version: Literal["materials-ner/1"]
    work_id: str
    outcome: Literal["results", "empty", "incomplete"]
    empty_reason: str | None
    processed_block_ids: list[str]
    unread_block_ids: list[str]
    limitations: list[str]
    samples: list[Sample]
    states: list[State]
    protocols: list[Protocol]
    results: list[Result]

    @model_validator(mode="after")
    def references(self):
        def index(items):
            result = {item.id: item for item in items}
            if len(result) != len(items) or any(not key.strip() for key in result):
                raise ValueError("duplicate or empty local identifier")
            return result
        samples, states, protocols, results = map(
            index, (self.samples, self.states, self.protocols, self.results))
        for state in states.values():
            if state.sample_id not in samples:
                raise ValueError("state points to unknown sample")
        for result in results.values():
            if result.sample_id not in samples or result.state_id not in states or result.protocol_id not in protocols:
                raise ValueError("result has a dangling sample/state/protocol")
            if states[result.state_id].sample_id != result.sample_id:
                raise ValueError("cross-sample state binding")
            if result.quantity_kind == "unmapped" and not result.quantity_name_raw:
                raise ValueError("unmapped physical quantity needs its source name")
            for edge in result.dependencies:
                if edge.result_id not in results or edge.result_id == result.id:
                    raise ValueError("dangling or self dependency")
        visiting, done = set(), set()

        def visit(identifier):
            if identifier in visiting:
                raise ValueError("cyclic derivation")
            if identifier in done:
                return
            visiting.add(identifier)
            for edge in results[identifier].dependencies:
                if edge.relation == "derived_from":
                    visit(edge.result_id)
            visiting.remove(identifier)
            done.add(identifier)
        for identifier in results:
            visit(identifier)
        if (self.outcome == "results" and not self.results
                or self.outcome == "empty" and (self.results or not self.empty_reason)):
            raise ValueError("empty is an explicit, reasoned outcome")
        return self


def output_schema() -> dict:
    """OpenAI strict subset: every object field is required, nullable where declared."""
    schema = Extraction.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(schema)
    # Pydantic's cross-field validators are not represented in JSON Schema.
    # Express the mutually exclusive numeric shapes at generation time as well.
    # Keep the parsed Python contract unchanged for historical attempt receipts.
    quantity = schema["$defs"]["Quantity"]
    variants = []
    shapes = {"exact": {"value"}, "interval": {"lower", "upper"},
              "lt": {"upper"}, "le": {"upper"}, "gt": {"lower"}, "ge": {"lower"}}
    for relation, numeric in shapes.items():
        branch = deepcopy(quantity)
        properties = branch["properties"]
        properties["status"] = {"type": "string", "enum": ["reported"]}
        properties["relation"] = {"type": "string", "enum": [relation]}
        properties["raw"] = {"type": "string", "minLength": 1}
        properties["unit"] = {"type": "string", "minLength": 1}
        for name in ("value", "lower", "upper"):
            properties[name] = {"type": "number" if name in numeric else "null"}
        variants.append(branch)
    unresolved = deepcopy(quantity)
    unresolved["properties"]["status"]["enum"] = [
        status for status in quantity["properties"]["status"]["enum"] if status != "reported"]
    for name in ("value", "lower", "upper", "relation", "uncertainty"):
        unresolved["properties"][name] = {"type": "null"}
    variants.append(unresolved)
    schema["$defs"]["Quantity"] = {"anyOf": variants}
    return schema


def parse_extraction(value):
    """Dispatch only explicitly versioned contracts; preserve old field shapes."""
    if value.get("schema_version") == "materials-ner/15":
        from .contract_v15 import ExtractionV15
        return ExtractionV15.model_validate(value)
    if value.get("schema_version") == "materials-ner/14":
        from .contract_v14 import ExtractionV14
        return ExtractionV14.model_validate(value)
    if value.get("schema_version") == "materials-ner/13":
        from .contract_v13 import ExtractionV13
        return ExtractionV13.model_validate(value)
    if value.get("schema_version") == "materials-ner/12":
        from .contract_v12 import ExtractionV12
        return ExtractionV12.model_validate(value)
    if value.get("schema_version") == "materials-ner/11":
        from .contract_v11 import ExtractionV11
        return ExtractionV11.model_validate(value)
    if value.get("schema_version") == "materials-ner/10":
        from .contract_v10 import ExtractionV10
        return ExtractionV10.model_validate(value)
    if value.get("schema_version") == "materials-ner/9":
        from .contract_v9 import ExtractionV9
        return ExtractionV9.model_validate(value)
    if value.get("schema_version") == "materials-ner/8":
        from .contract_v8 import ExtractionV8
        return ExtractionV8.model_validate(value)
    if value.get("schema_version") == "materials-ner/7":
        from .contract_v7 import ExtractionV7
        return ExtractionV7.model_validate(value)
    if value.get("schema_version") == "materials-ner/6":
        from .contract_v6 import ExtractionV6
        return ExtractionV6.model_validate(value)
    if value.get("schema_version") == "materials-ner/5":
        from .contract_v5 import ExtractionV5
        return ExtractionV5.model_validate(value)
    if value.get("schema_version") == "materials-ner/4":
        from .contract_v4 import ExtractionV4
        return ExtractionV4.model_validate(value)
    if value.get("schema_version") == "materials-ner/3":
        from .contract_v3 import ExtractionV3
        return ExtractionV3.model_validate(value)
    if value.get("schema_version") == "materials-ner/2":
        from .contract_v2 import ExtractionV2
        return ExtractionV2.model_validate(value)
    return Extraction.model_validate(value)
