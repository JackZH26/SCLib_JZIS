"""Explicit result definitions with shared source-scoped measurement background.

The historical v4 proposal combines a procedure and a result's definition in a
protocol. The adapter builds one explicit protocol variant per observation; it
does not infer criteria, merge results, or copy conditions between states.
"""
from typing import Literal

from pydantic import Field, model_validator

from .contract import StrictModel, canonical, digest
from .contract_v2 import ProtocolParameter
from .contract_v3 import CriterionKind, ProtocolParameterV3, ProtocolV3
from .wire import EvidenceReference, nested_model
from .wire_v2 import output_schema as common_schema
from .wire_v5 import (SharedExtraction, SharedObservation, ContextBinding,
    CarriedContext, ExcludedContext, SCIENTIFIC_INSTRUCTIONS, REGISTRY_INSTRUCTIONS,
    SEMANTICS, CONDITIONAL_INSTRUCTIONS, inventory_render as prior_inventory_render,
    inventory_render_repair as prior_inventory_repair,
    validate_coverage as shared_coverage)
from .inventory import source_text
from .wire_v4 import output_schema as v4_schema
from .validation import pointer_exists

WIRE_VERSION = "materials-ner-shared/2"
PROMPT_VERSION = "materials-ner-prompt/6.0.1"


class ProcedureContract(ProtocolV3):
    # Frequency/field/mu-star can be shared. A resistance threshold defines a
    # particular result and is therefore only allowed in its definition.
    parameters: list[ProtocolParameter]


SharedProcedure = nested_model("SharedProcedure", ProcedureContract,
                               {"criterion", "criterion_raw"})


class DefinitionParameter(ProtocolParameterV3):
    kind: Literal["resistance_fraction"]


class ResultDefinition(StrictModel):
    criterion: CriterionKind
    criterion_raw: str | None
    parameters: list[DefinitionParameter]
    evidence: list[EvidenceReference]


class DefinedObservation(SharedObservation):
    definition: ResultDefinition


class DefinitionContextBinding(ContextBinding):
    entity: Literal["sample", "state", "protocol", "definition", "result"]


class CarriedDefinitionContext(CarriedContext):
    bindings: list[DefinitionContextBinding] = Field(min_length=1)


class ExcludedDefinitionContext(ExcludedContext):
    bindings: list[DefinitionContextBinding] = Field(max_length=0)


def variant_id(observation_id):
    return "definition-protocol:" + observation_id


def definition_field(field, common_parameter_count):
    """Translate an explicit definition pointer into the legacy protocol view."""
    parts = field.split("/")
    if len(parts) > 2 and parts[1] == "parameters" and parts[2].isdigit():
        parts[2] = str(int(parts[2]) + common_parameter_count)
    return "/".join(parts)


class DefinedExtraction(SharedExtraction):
    schema_version: Literal["materials-ner-shared/2"]
    protocols: list[SharedProcedure]
    observations: list[DefinedObservation]
    context_dispositions: list[CarriedDefinitionContext | ExcludedDefinitionContext]

    @model_validator(mode="after")
    def definition_ownership(self):
        # A pointer that is invalid in the authored object must not accidentally
        # become valid after concatenating parameters into a legacy variant.
        maps = self.entity_maps()
        for kind in ("protocol", "definition"):
            for entity in maps[kind].values():
                if any(not pointer_exists(entity.model_dump(), field)
                       for ref in entity.evidence for field in ref.fields):
                    raise ValueError("evidence_definition_ownership_invalid")
        for disposition in self.context_dispositions:
            for binding in disposition.bindings:
                if binding.entity in {"protocol", "definition"} and not pointer_exists(
                        maps[binding.entity][binding.entity_id].model_dump(), binding.field):
                    raise ValueError("context_definition_ownership_invalid")
        return self

    def entity_maps(self):
        maps = super().entity_maps()
        maps["definition"] = {o.id: o.definition for o in self.observations}
        return maps

    def scientific_payload(self):
        def strip(value):
            if isinstance(value, dict):
                return {k: strip(v) for k, v in value.items() if k != "evidence"}
            if isinstance(value, list): return [strip(v) for v in value]
            return value
        return strip(self.model_dump())

    def as_shared_v1(self):
        """Lossless explicit-field adaptation, not canonical procedure identity."""
        data = self.model_dump()
        data["schema_version"] = "materials-ner-shared/1"
        procedures = self.entity_maps()["protocol"]
        data["protocols"] = []
        variants = {}
        for observation in data["observations"]:
            procedure_id = observation["protocol_id"]
            body = procedures[procedure_id].model_dump()
            count = len(body["parameters"])
            definition = observation.pop("definition")
            body.update(id=variant_id(observation["id"]),
                criterion=definition["criterion"], criterion_raw=definition["criterion_raw"])
            body["parameters"].extend(definition["parameters"])
            body["evidence"].extend({"span_ids": e["span_ids"],
                "fields": [definition_field(f, count) for f in e["fields"]]}
                for e in definition["evidence"])
            observation["protocol_id"] = body["id"]
            data["protocols"].append(body)
            variants.setdefault(procedure_id, []).append(body["id"])
        for disposition in data["context_dispositions"]:
            bindings = []
            for binding in disposition["bindings"]:
                kind, identifier, field = binding["entity"], binding["entity_id"], binding["field"]
                if kind == "protocol":
                    bindings.extend(dict(binding, entity_id=pid) for pid in variants[identifier])
                elif kind == "definition":
                    observation = self.entity_maps()["result"][identifier]
                    count = len(procedures[observation.protocol_id].parameters)
                    bindings.append(dict(binding, entity="protocol", entity_id=variant_id(identifier),
                                         field=definition_field(field, count)))
                else: bindings.append(binding)
            disposition["bindings"] = bindings
        return SharedExtraction.model_validate(data)

    def expand(self, bundle):
        return self.as_shared_v1().expand(bundle)

    def as_flat(self):
        return self.as_shared_v1().as_flat()

    def validation_entity_ids(self):
        return {"samples": [s.id for s in self.samples], "states": [s.id for s in self.states],
                "protocols": [variant_id(o.id) for o in self.observations],
                "results": [o.id for o in self.observations]}

    def projection_manifest(self):
        return {"schema": "materials-result-definition-projection/1",
            "wire_schema": WIRE_VERSION, "proposal_schema": "materials-ner/4",
            "procedure_identity_is_source_scoped_proposal": True,
            "variants_are_not_distinct_measurement_assertions": True,
            "observations": [{"observation_id": o.id, "procedure_id": o.protocol_id,
                "definition_owner_id": o.id, "proposal_protocol_id": variant_id(o.id)}
                for o in self.observations]}

    def source_protocol_field(self, variant, field):
        """Route diagnostics back to the field's unique authored owner."""
        observation = next(o for o in self.observations if variant_id(o.id) == variant)
        procedure = self.entity_maps()["protocol"][observation.protocol_id]
        parts = field.split("/")
        if parts[1] in {"criterion", "criterion_raw"}:
            return "definition", observation.id, field
        if len(parts) > 2 and parts[1] == "parameters" and parts[2].isdigit():
            index = int(parts[2]) - len(procedure.parameters)
            if index >= 0:
                parts[2] = str(index)
                return "definition", observation.id, "/".join(parts)
        return "protocol", observation.protocol_id, field


def validate_coverage(compact, inventory, bundle):
    report = shared_coverage(compact.as_shared_v1(), inventory, bundle)
    report.update(context_dispositions=[d.model_dump() for d in compact.context_dispositions],
        shared_entity_counts={"samples": len(compact.samples), "states": len(compact.states),
                              "procedures": len(compact.protocols)},
        explicit_result_definitions=len(compact.observations),
        context_binding_scope="shared_background_and_result_specific_definition")
    return report


def output_schema(bundle=None, inventory=None):
    schema = common_schema(bundle, model=DefinedExtraction,
        negative_def="NonDetectionV4", conditional_def="ConditionalExistenceV4")
    schema["$defs"]["ConditionalExistenceV4"] = v4_schema()["$defs"]["ConditionalExistenceV4"]
    if inventory is not None:
        ids = [c.id for c in inventory.context_assertions]
        # Only the source inventory's actual IDs may be dispositioned. The
        # validator still checks exact-once closure and semantic field support.
        schema["properties"]["context_dispositions"].update(minItems=len(ids), maxItems=len(ids))
        if ids:
            for name in ("CarriedDefinitionContext", "ExcludedDefinitionContext"):
                schema["$defs"][name]["properties"]["context_id"]["enum"] = ids
    return schema


SCIENTIFIC_V6 = SCIENTIFIC_INSTRUCTIONS.replace(
    "is a JSON pointer relative to its sample/state/protocol/result.",
    "is a JSON pointer relative to its sample/state/protocol/definition/result.").replace(
    "Each known protocol method and non-unspecified/non-not_applicable criterion\nneeds /method and /criterion.",
    "Each known protocol method needs /method. Each result definition with a known\ncriterion needs /criterion on that definition.")
SEMANTICS_V6 = SEMANTICS.replace("an evidenced protocol parameter", "an evidenced result-definition parameter")

INSTRUCTIONS = """OUTPUT TRANSPORT: materials-ner-shared/2.
Declare source-scoped samples, states, protocols, and observations. A protocol
now means SHARED PROCEDURE BACKGROUND ONLY: method, method_class, observable,
details_raw and common parameters. It has NO criterion or criterion_raw.
Each observation MUST contain its own definition: criterion, criterion_raw,
parameters, evidence. This is required even when several results share a method.
Choose a source-supported criterion independently for EACH result. Onset and
zero resistance are different definitions of results from the same curve;
secondary onset is criterion=onset plus result.qualifiers.transition_stage.
Unspecified is appropriate only when this result's supplied source gives no
criterion. Do not replace explicit result definitions with a generic method.
An Hc2 extracted at a fraction of normal-state resistance has definition
criterion=resistance_fraction and a typed resistance_fraction parameter. Such
thresholds are forbidden in common protocol parameters. Frequency, probe field
and mu-star stay in common procedure parameters only when applicable to every
referencing result. Use separate procedures if these settings differ.

Each observation names sample_id, state_id and protocol_id explicitly. Equal
formulas never identify samples. Re-read the sentence/paragraph subjects before
assigning a value. Verify the subject again when a paragraph changes samples.
Every state belongs to one sample. A shared state retains all source-supported
geometry/preparation and applicable conditions. Thickness of the actual film
and fitted superconducting-layer thickness are distinct. Do not leave geometry
out of a generic state when the source explicitly assigns it to that sample;
do not copy it from another sample or treatment. Do not deduce missing facts.

For EACH result, classify origin by its inputs, not words like 'calculate' or
'fit'. A fit/extrapolation of measured transport or magnetic data is
model_derived. Computed means a theoretical prediction from calculation inputs.
The presence of a theoretical fit equation does not turn measured input data
into a theoretical prediction. Bind /origin to the actual source support and
retain method details. Missing input results do not justify fabricated IDs.

Evidence still selects literal catalog spans. Definition evidence paths are
/criterion, /criterion_raw and /parameters/N, relative to that definition.
Result evidence still binds /sample_id, /state_id and /protocol_id as well as
the result's own fields. Context bindings may target definition with entity_id
equal to its observation ID. A definition binding affects ONLY that result.
Other bindings target sample/state/protocol/result by their explicit IDs.
Carried context must survive in the named typed fields, not just a vague label.
All source inventory items and context assertions require explicit dispositions.
Use each supplied context_assertion ID EXACTLY ONCE as context_id; never invent
replacement IDs, merge entries, or substitute descriptive names. An entry that
cannot be represented faithfully must remain unresolved with a reason. A form
description that mentions a thickness does not retain that quantity as a typed
condition. Carry it in the appropriate state.conditions entry, with source
evidence, when the supplied source assigns it to that sample and state.
All declared entities must be referenced. Preserve unresolved context honestly.
Return no scientific corrections, implied ambient pressure, averaged table
values or silently repaired formulas. No tools or external knowledge.
"""

INVENTORY_COMPLETENESS = """INVENTORY ACCOUNTING: Fitted/derived physical results
in TARGET, including superconducting-layer thickness, belong in items even when
they also supply context. A context_assertion alone does not extract a result.
Keep total specimen geometry distinct from fitted/effective physical lengths.
Preserve an approximate numeric report even if another passage gives a more
specific value; do not assume the measurements or states are identical. The
extraction may later record a reviewed relationship between occurrences.
Preserve conflicting literal chemical formulas as context requiring resolution,
including notation that looks like a typo. Do not silently correct the authors.
Use separate context assertions for separate facts and identify the subject.
"""


def inventory_render(bundle):
    return INVENTORY_COMPLETENESS + "\n" + prior_inventory_render(bundle)


def inventory_render_repair(bundle, inventory, validation):
    return INVENTORY_COMPLETENESS + "\n" + prior_inventory_repair(bundle, inventory, validation)


def render(bundle, inventory):
    return "\n".join([SCIENTIFIC_V6, REGISTRY_INSTRUCTIONS, SEMANTICS_V6,
        CONDITIONAL_INSTRUCTIONS, INSTRUCTIONS,
        "FIRST_READ_INVENTORY (fallible proposals, not source truth): " + canonical(inventory.model_dump()),
        source_text(bundle), "Return shared background and explicit result definitions."])


PROMPT_HASH = digest({"version": PROMPT_VERSION, "scientific": SCIENTIFIC_V6,
    "registry": REGISTRY_INSTRUCTIONS, "semantics": SEMANTICS_V6,
    "conditional": CONDITIONAL_INSTRUCTIONS, "wire": INSTRUCTIONS,
    "inventory_accounting": INVENTORY_COMPLETENESS})
