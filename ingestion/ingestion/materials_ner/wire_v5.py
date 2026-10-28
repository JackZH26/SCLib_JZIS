"""Source-scoped shared entity transport; canonical proposal semantics stay v4.

Sharing is explicit in the model response, never inferred from equal formulas.
Expansion resolves references and quotes only. The flat adapter is used solely
by historical inventory checks; the stored extraction keeps the shared graph.
"""
from copy import deepcopy
from typing import Literal

from pydantic import Field, model_validator

from .contract import StrictModel, canonical, digest
from .contract_v2 import SampleV2
from .contract_v3 import StateV3, ProtocolV3
from .contract_v4 import ExtractionV4
from .evidence import source_catalog, selected_quotes
from .inventory import InventoryItem, source_text
from .wire import nested_model, EmptyCompletion, ResultsCompletion, IncompleteCompletion
from .wire_v2 import UnextractedItem, output_schema as shared_schema
from .wire_v4 import (ObservationResult, CompactExtractionV4, SCIENTIFIC_INSTRUCTIONS,
    REGISTRY_INSTRUCTIONS, INSTRUCTIONS as V4_INSTRUCTIONS, inventory_render,
    inventory_render_repair, PROMPT_HASH as V4_PROMPT_HASH, validate_coverage as flat_coverage)

WIRE_VERSION = "materials-ner-shared/1"
PROMPT_VERSION = "materials-ner-prompt/5.0.0"
SharedSample = nested_model("SharedSample", SampleV2, set())
SharedState = nested_model("SharedState", StateV3, set())
SharedProtocol = nested_model("SharedProtocol", ProtocolV3, set())


class SharedObservation(StrictModel):
    id: str = Field(min_length=1)
    inventory_item_ids: list[str] = Field(min_length=1)
    sample_id: str = Field(min_length=1)
    state_id: str = Field(min_length=1)
    protocol_id: str = Field(min_length=1)
    result: ObservationResult


class ContextBinding(StrictModel):
    entity: Literal["sample", "state", "protocol", "result"]
    entity_id: str = Field(min_length=1)
    field: str = Field(pattern=r"^/")


class CarriedContext(StrictModel):
    context_id: str
    resolution: Literal["carried"]
    bindings: list[ContextBinding] = Field(min_length=1)
    explanation: None


class ExcludedContext(StrictModel):
    context_id: str
    resolution: Literal["not_applicable", "unresolved"]
    bindings: list[ContextBinding] = Field(max_length=0)
    explanation: str = Field(min_length=1)


class SharedExtraction(StrictModel):
    schema_version: Literal["materials-ner-shared/1"]
    work_id: str
    completion: EmptyCompletion | ResultsCompletion | IncompleteCompletion
    processed_block_ids: list[str]
    unread_block_ids: list[str]
    limitations: list[str]
    samples: list[SharedSample]
    states: list[SharedState]
    protocols: list[SharedProtocol]
    observations: list[SharedObservation]
    additional_items: list[InventoryItem]
    unextracted_items: list[UnextractedItem]
    context_dispositions: list[CarriedContext | ExcludedContext]

    @model_validator(mode="after")
    def references(self):
        maps = self.entity_maps()
        for name, rows in (("sample", self.samples), ("state", self.states),
                           ("protocol", self.protocols), ("result", self.observations)):
            if len(maps[name]) != len(rows) or any(not r.id.strip() for r in rows):
                raise ValueError("duplicate_or_empty_shared_" + name + "_id")
        for state in self.states:
            if state.sample_id not in maps["sample"]:
                raise ValueError("shared_state_sample_reference_invalid")
        for observation in self.observations:
            if observation.state_id not in maps["state"] or observation.protocol_id not in maps["protocol"]:
                raise ValueError("shared_observation_reference_invalid")
            if observation.sample_id != maps["state"][observation.state_id].sample_id:
                raise ValueError("shared_observation_state_sample_mismatch")
        used_states = {o.state_id for o in self.observations}
        used_protocols = {o.protocol_id for o in self.observations}
        used_samples = {maps["state"][sid].sample_id for sid in used_states}
        if (used_states != set(maps["state"]) or used_protocols != set(maps["protocol"])
                or used_samples != set(maps["sample"])):
            raise ValueError("unreferenced_shared_entity_requires_explicit_scope_review")
        for disposition in self.context_dispositions:
            for binding in disposition.bindings:
                if binding.entity_id not in maps[binding.entity]:
                    raise ValueError("shared_context_target_invalid")
        return self

    def entity_maps(self):
        return {name: {row.id: row for row in rows} for name, rows in (
            ("sample", self.samples), ("state", self.states),
            ("protocol", self.protocols), ("result", self.observations))}

    def scientific_payload(self):
        data = self.model_dump()
        for name in ("samples", "states", "protocols"):
            for row in data[name]: row.pop("evidence")
        for observation in data["observations"]: observation["result"].pop("evidence")
        return data

    def expand(self, bundle):
        catalog = source_catalog(bundle)
        if self.work_id != bundle.work_id: raise ValueError("work_binding_mismatch")
        data = {"schema_version": "materials-ner/4", "work_id": self.work_id,
                **self.completion.model_dump(), "limitations": self.limitations}
        for key in ("processed_block_ids", "unread_block_ids"):
            data[key] = [catalog["blocks"][alias]["block_id"] for alias in getattr(self, key)]
        def expand_entity(entity, identifiers=None):
            row = entity.model_dump(exclude={"evidence"})
            row.update(identifiers or {})
            row["evidence"] = [{"block_id": q["block_id"], "quote": q["quote"], "field": field}
                for ref in entity.evidence for q in selected_quotes(catalog, ref.span_ids) for field in ref.fields]
            return row
        for key in ("samples", "states", "protocols"):
            data[key] = [expand_entity(entity) for entity in getattr(self, key)]
        states = self.entity_maps()["state"]
        data["results"] = [expand_entity(o.result, {"id": o.id, "sample_id": o.sample_id,
            "state_id": o.state_id, "protocol_id": o.protocol_id}) for o in self.observations]
        return ExtractionV4.model_validate(data)

    def as_flat(self):
        """Compatibility read for inventory checks, never stored as canonical output."""
        maps = self.entity_maps()
        payload = self.model_dump(exclude={"samples", "states", "protocols", "observations", "context_dispositions"})
        payload["schema_version"] = "materials-ner-compact/6"
        payload["observations"] = []
        links = {}
        for observation in self.observations:
            state, protocol = maps["state"][observation.state_id], maps["protocol"][observation.protocol_id]
            sample = maps["sample"][state.sample_id]
            payload["observations"].append({"id": observation.id, "inventory_item_ids": observation.inventory_item_ids,
                "sample": sample.model_dump(exclude={"id"}), "state": state.model_dump(exclude={"id", "sample_id"}),
                "protocol": protocol.model_dump(exclude={"id"}), "result": observation.result.model_dump()})
            for kind, identifier in (("sample", sample.id), ("state", state.id),
                                     ("protocol", protocol.id), ("result", observation.id)):
                links.setdefault((kind, identifier), []).append(observation.id)
        payload["context_dispositions"] = []
        for disposition in self.context_dispositions:
            row = disposition.model_dump(exclude={"bindings"})
            row["bindings"] = [{"observation_id": oid, "entity": b.entity, "field": b.field}
                for b in disposition.bindings for oid in links[(b.entity, b.entity_id)]]
            payload["context_dispositions"].append(row)
        return CompactExtractionV4.model_validate(payload)


def validate_coverage(compact, inventory, bundle):
    report = flat_coverage(compact.as_flat(), inventory, bundle)
    indexes = {name: {row.id: index for index, row in enumerate(getattr(compact, name))}
               for name in ("samples", "states", "protocols")}
    states = compact.entity_maps()["state"]
    # Historical inventory diagnostics index observation-scoped entity copies.
    # Remap these to the authoritative shared entity array before review_rows.
    remapped = []
    for issue in report["issues"]:
        parts = issue["path"].split("/")
        if len(parts) > 2 and parts[1] in indexes and parts[2].isdigit():
            observation = compact.observations[int(parts[2])]
            identifier = {"samples": states[observation.state_id].sample_id,
                          "states": observation.state_id, "protocols": observation.protocol_id}[parts[1]]
            parts[2] = str(indexes[parts[1]][identifier])
            issue = {**issue, "path": "/".join(parts)}
        if issue not in remapped: remapped.append(issue)
    report.update(issues=remapped, valid=not remapped, context_dispositions=[d.model_dump() for d in compact.context_dispositions],
                  shared_entity_counts={name: len(getattr(compact, name)) for name in indexes},
                  context_binding_scope="shared_source_entity")
    return report


def output_schema(bundle=None):
    schema = shared_schema(bundle, model=SharedExtraction,
        negative_def="NonDetectionV4", conditional_def="ConditionalExistenceV4")
    # Reuse the exact v4 conditional-bound restriction without changing its semantics.
    from .wire_v4 import output_schema as v4_schema
    schema["$defs"]["ConditionalExistenceV4"] = v4_schema()["$defs"]["ConditionalExistenceV4"]
    return schema


INSTRUCTIONS = """OUTPUT TRANSPORT: materials-ner-shared/1.
The JSON schema uses separate samples, states, protocols and observations arrays.
Declare each source-scoped sample once. Different samples with similar formulas
stay separate. A state names its sample_id and retains that sample's actual
geometry, preparation and applicable conditions. Results reference sample_id,
state_id and protocol_id. The state's sample_id must equal the result's sample_id;
the program checks those explicit links, never formula equality.
Share a state/protocol only when its entire stated meaning applies to every
referencing result. Different measurement orientations, conditions or criteria
may need separate states/protocols. Do not share solely to minimize output size.
Sample thickness must survive for ALL results of that state, not just a fitted
layer-thickness result. Total film thickness and fitted superconducting-layer
thickness are different quantities. Do not infer missing geometry.

Keep inventory_item_ids on each observation, including explicit unextracted
items. Source inventories are fallible; re-read the actual source. Evidence is
still {span_ids, fields}, selecting literal source spans. All IDs are local to
this source window; no global material/sample identity is established.

Context bindings name entity plus entity_id plus an indexed field. Bind a shared
sample/state/protocol once, not once per result. Carried means the actual field
retains the actual fact. A generic 'thin film' form does not carry a thickness,
phase composition or synthesis condition. Separate multi-fact context into all
the fields that retain it. Missing or unsupported context stays unresolved with
an explanation; do not invent fields or claim it was carried. Excluded context
has no bindings. Every declared shared entity must be referenced by a result;
otherwise retain the out-of-scope assertion in inventory/limitations for review.

Each observation contains a result, sample_id, state_id and protocol_id; it has no inline
sample, state or protocol. Dependencies refer to observation IDs. Bind result
/sample_id, /state_id and /protocol_id evidence as before. Never invent
observations to satisfy a reference.
"""


SEMANTICS = """Account for every first-read inventory item exactly once, in an
observation or an explicit unextracted entry. Several inventory IDs can describe
repeated mentions of one result, never different samples or methods. A missed
TARGET result can be added with its own literal source-bound additional_item.
An inventory does not override the original paper. Preserve disagreements.

Use method_class and a source-supported criterion. An observed specific-heat
jump uses heat_capacity_anomaly; a fitted transition parameter uses fit_parameter
and its appropriate temperature_role. Resistance percentages use resistance_fraction
with an evidenced protocol parameter and the stated normal-state reference.
Do not rename a 90% criterion onset without an explicit source definition.
Keep primary/secondary stage as a transition_stage qualifier, separate from onset.
All qualifier raw strings are literal source expressions, with /qualifiers/N
bindings. Protocol parameters and state conditions need indexed evidence.

Classify provenance by inputs: algebra or fits using measured data are
model_derived. Theoretical electronic/phonon calculations are computed. A Tc
from theoretical gap solutions can be system_transition; a band/component model
temperature is model_temperature_scale. Keep source_role and origin independent.
Never invent dependency IDs for inputs outside the target window.

Preserve additional source formulas/bases with their own evidence, not an
inferred corrected formula. Explicit formula conflicts remain conflicted.
Actual film thickness is a state thickness condition; fitted superconducting
layer thickness is a superconducting_layer_thickness result. A GL parameter is
gl_parameter, not electron_phonon_lambda. electronic_dos_per_atom requires an
explicit per-atom basis. Keep source-reported radius, resistance fraction and
calculation parameters in their registered typed fields. Unknown facts remain
unknown; registration does not permit deduction or scientific approval.
"""
CONDITIONAL_INSTRUCTIONS = V4_INSTRUCTIONS[V4_INSTRUCTIONS.index(
    "V4 CONDITIONAL ASSERTIONS AND WINDOW MISSINGNESS:"):]


def render(bundle, inventory):
    return "\n".join([SCIENTIFIC_INSTRUCTIONS, REGISTRY_INSTRUCTIONS, SEMANTICS,
        CONDITIONAL_INSTRUCTIONS, INSTRUCTIONS,
        "FIRST_READ_INVENTORY (fallible proposals, not source truth): " + canonical(inventory.model_dump()),
        source_text(bundle), "Return the source-scoped shared entity JSON."])


PROMPT_HASH = digest({"version": PROMPT_VERSION, "base_scientific_prompt": V4_PROMPT_HASH,
                      "shared_transport": INSTRUCTIONS, "semantics": SEMANTICS,
                      "conditional": CONDITIONAL_INSTRUCTIONS})
