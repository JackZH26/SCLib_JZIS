"""Compact Luna transport; deterministic expansion into the scientific contract.

Source spans are selected, never retyped. A nested observation is a
closed sample/state/protocol/result graph. Expansion only assigns local IDs and
copies references; it never fills a scientific value or merges sample identities.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Literal

from pydantic import Field, create_model, model_validator

from .contract import (Extraction, Protocol, Result, Sample, State, StrictModel,
                       output_schema as canonical_schema)
from .evidence import selected_quotes, source_catalog
from .sources import Bundle

WIRE_VERSION = "materials-ner-compact/3"


class EvidenceReference(StrictModel):
    span_ids: list[str] = Field(min_length=1, description="Select exact source span IDs such as S1; no quotations.")
    fields: list[str] = Field(min_length=1)


def nested_model(name, original, excluded):
    fields = {key: (field.annotation, deepcopy(field)) for key, field in original.model_fields.items()
              if key not in set(excluded) | {"evidence"}}
    description = (
        "Required source bindings. Include /sample_id even when conditions is empty."
        if name == "ObservationState" else
        "Source bindings for every asserted field required by the extraction instructions."
    )
    return create_model(name, __base__=StrictModel, **fields,
                        evidence=(list[EvidenceReference], Field(description=description)))


ObservationSample = nested_model("ObservationSample", Sample, {"id"})
ObservationState = nested_model("ObservationState", State, {"id", "sample_id"})
ObservationProtocol = nested_model("ObservationProtocol", Protocol, {"id"})
ObservationResult = nested_model("ObservationResult", Result, {"id", "sample_id", "state_id", "protocol_id"})


class Observation(StrictModel):
    id: str
    sample: ObservationSample
    state: ObservationState
    protocol: ObservationProtocol
    result: ObservationResult


class EmptyCompletion(StrictModel):
    outcome: Literal["empty"]
    empty_reason: str = Field(min_length=1, description="Concrete reason this target has no results.")


class ResultsCompletion(StrictModel):
    outcome: Literal["results"]
    empty_reason: None


class IncompleteCompletion(StrictModel):
    outcome: Literal["incomplete"]
    empty_reason: None


class CompactExtraction(StrictModel):
    schema_version: Literal["materials-ner-compact/3"]
    work_id: str
    completion: EmptyCompletion | ResultsCompletion | IncompleteCompletion
    processed_block_ids: list[str]
    unread_block_ids: list[str]
    limitations: list[str]
    observations: list[Observation]

    @model_validator(mode="after")
    def references(self):
        ids = {o.id for o in self.observations}
        if len(ids) != len(self.observations) or any(not i.strip() for i in ids):
            raise ValueError("duplicate or empty observation ID")
        for obs in self.observations:
            for entity in (obs.sample, obs.state, obs.protocol, obs.result):
                for evidence in entity.evidence:
                    if any(not f.startswith("/") for f in evidence.fields):
                        raise ValueError("malformed field pointer")
        return self

    def expand(self, bundle: Bundle) -> Extraction:
        catalog = source_catalog(bundle)
        if self.work_id != bundle.work_id:
            raise ValueError("work_binding_mismatch")
        if any(alias not in catalog["blocks"] for alias in self.processed_block_ids + self.unread_block_ids):
            raise ValueError("unknown_source_block_alias")
        result = {"work_id": self.work_id, "limitations": self.limitations}
        for field in ("processed_block_ids", "unread_block_ids"):
            result[field] = [catalog["blocks"][alias]["block_id"] for alias in getattr(self, field)]
        result.update(self.completion.model_dump())
        result.update(schema_version="materials-ner/1", samples=[], states=[], protocols=[], results=[])
        for obs in self.observations:
            sample_id, state_id, protocol_id = f"s:{obs.id}", f"st:{obs.id}", f"p:{obs.id}"
            for name, entity, identifiers in (
                ("samples", obs.sample, {"id": sample_id}),
                ("states", obs.state, {"id": state_id, "sample_id": sample_id}),
                ("protocols", obs.protocol, {"id": protocol_id}),
                ("results", obs.result, {"id": obs.id, "sample_id": sample_id,
                                         "state_id": state_id, "protocol_id": protocol_id}),
            ):
                row = entity.model_dump(exclude={"evidence"})
                row.update(identifiers)
                row["evidence"] = [
                    {"block_id": quote["block_id"], "quote": quote["quote"], "field": field}
                    for ref in entity.evidence for quote in selected_quotes(catalog, ref.span_ids)
                    for field in ref.fields
                ]
                result[name].append(row)
        return Extraction.model_validate(result)


def output_schema(bundle: Bundle | None = None):
    schema = CompactExtraction.model_json_schema()
    def walk(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(schema)
    schema["$defs"]["Quantity"] = canonical_schema()["$defs"]["Quantity"]
    # Non-detection is a categorical observation, never a point/bound Tc.
    # Express this at generation time as well as in the canonical validator.
    result = schema["$defs"]["ObservationResult"]
    numeric, negative = deepcopy(result), deepcopy(result)
    numeric["properties"]["quantity_kind"]["enum"].remove("non_detection")
    negative["properties"]["quantity_kind"]["enum"] = ["non_detection"]
    unresolved = deepcopy(schema["$defs"]["Quantity"]["anyOf"][-1])
    unresolved["properties"]["status"]["enum"] = ["not_applicable"]
    negative["properties"]["quantity"] = unresolved
    schema["$defs"]["ObservationResult"] = {"anyOf": [numeric, negative]}
    if bundle is not None:
        catalog = source_catalog(bundle)
        schema["properties"]["work_id"]["enum"] = [bundle.work_id]
        for field in ("processed_block_ids", "unread_block_ids"):
            schema["properties"][field]["items"]["enum"] = list(catalog["blocks"])
        schema["$defs"]["EvidenceReference"]["properties"]["span_ids"]["items"]["enum"] = list(catalog["spans"])
    return schema


INSTRUCTIONS = r"""
OUTPUT TRANSPORT: materials-ner-compact/3. This compact transport replaces the
separate samples/states/protocols/results arrays described by the scientific
rules above. Return observations, as defined by the JSON schema.
The outcome and empty_reason fields are nested in completion. For example:
completion={"outcome":"empty","empty_reason":"No material observations in this target."}
or completion={"outcome":"results","empty_reason":null}. For an incomplete window
use completion={"outcome":"incomplete","empty_reason":null} and explain limitations.
Each observation has one id, one sample, one state, one protocol and one result.
The program assigns the graph IDs; you must supply all scientific attributes.
Dependencies refer to observation IDs. Do not refer to any nonexistent ID.
Source-scoped samples repeated across observations remain unmerged candidates.

The source already has immutable spans S1, S2, etc. Do not write any quotation
or evidence_pool. Each entity's evidence is [{span_ids,fields}]. Select the
smallest set of spans supporting the actual asserted fields. The program copies
their exact original text and records its offsets/hashes. It does not infer support.
Use multiple spans for a table row plus headings, or an assertion plus its citation.
For example one result reference may use span_ids=["S2","S3"] and
fields=["/quantity_kind","/quantity","/sample_id","/state_id","/protocol_id",
"/origin","/source_role"]. Link pointers are required even though the program
assigns their IDs. A state's /sample_id is likewise supported by a quotation.
Every numeric raw token must still occur contiguously in the selected source
spans. Copy quantity.raw literally, including TeX braces/backslashes. It should
contain the numeric token, its bounds/approximation/uncertainty, and an adjacent
unit if printed there. Do not include a variable assignment or rewrite a formula.
Use table headings and captions to determine units; if unresolved, mark ambiguous.
Only bind fields that actually have non-null values. Never add /criterion_raw,
/details_raw, /component_raw or /cited_source_raw when their value is null.
Return the actual observations; mentioning omitted results in limitations is
not a substitute for extraction. If genuinely incomplete, keep all completed
observations and mark incomplete. An empty observation list requires a reason.
Use the full response budget. Brevity is not a goal for this data extraction;
do not omit observations merely to keep the response short.

FINAL OUTPUT CHECK:
* outcome=empty requires observations=[] AND a nonempty empty_reason string.
  Put the reason in empty_reason even if limitations already explains it.
* outcome=results requires at least one observation.
* Account for every short block alias B1, B2, etc exactly once in
  processed_block_ids or unread_block_ids, including context blocks.
* Every observation.state.evidence includes a reference whose fields contains
  "/sample_id", even when state.conditions is empty. It can use the same
  source quote that supports this observation.result's "/sample_id".
* If method/criterion is asserted, the protocol.evidence must explicitly bind
  "/method" and "/criterion". Keep unreported methods null and criteria unspecified.
* source_role=cited keeps the actual citation marker/name in cited_source_raw
  and a source quote binding "/cited_source_raw". If the original citation
  cannot be identified in these blocks, keep null and describe the unresolved
  attribution in limitations; the program will isolate that observation.
* composition_basis stays unresolved unless the source states that basis.
  A printed formula alone is not evidence of nominal or measured composition.
* Every asserted isotope/variable must have its indexed evidence pointer,
  e.g. /variables/0, even if its numeric amount is unresolved.
* A span containing a number does not support an unrelated material or method.
  Inspect each selected span and each field; do not attach all fields blindly.
* A missing method is null and must have NO /method evidence pointer. A missing
  criterion_raw is null and must have NO /criterion_raw evidence pointer.
* Preserve the printed detection limit in its source units. Never change
  value=15 mK to value=0.015 while retaining unit=mK. A stated lowest measured
  temperature may be an exact detection-window threshold; do not invent an
  inequality that is absent from quantity.raw. Keep window semantics in the
  condition's basis_raw and result interpretation, with source evidence.
"""
