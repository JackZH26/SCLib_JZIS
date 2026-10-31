"""Sparse component ownership and source-reported geometry in the native graph."""
from typing import Literal

from pydantic import Field, model_validator

from .contract import canonical, digest
from .contract_v6 import (ExtractionV6, StateV6, ProcedureV6, ResultV6,
    SampleRelationV6, ConditionSupportV6, relation_references)
from .evidence import source_catalog, selected_quotes
from .inventory import source_text, INSTRUCTIONS as BASE_INVENTORY, REPAIR_INSTRUCTIONS
from .wire import nested_model
from .wire_v2 import output_schema as common_schema
from .wire_v4 import output_schema as v4_schema
from .wire_v6 import DefinedObservation, DefinitionContextBinding, CarriedDefinitionContext, ExcludedDefinitionContext
from .wire_v7 import (NativeExtraction, validate_coverage,
    SCIENTIFIC_V6, REGISTRY_INSTRUCTIONS, SEMANTICS_V6, CONDITIONAL_INSTRUCTIONS, INVENTORY_COMPLETENESS,
    INSTRUCTIONS as NATIVE_INSTRUCTIONS, PROMPT_HASH as NATIVE_PROMPT_HASH)

WIRE_VERSION = "materials-ner-shared/4"
PROMPT_VERSION = "materials-ner-prompt/8.2.0"
RelationalState = nested_model("RelationalState", StateV6, set())
RelationalProcedure = nested_model("RelationalProcedure", ProcedureV6, set())
ObservationResult = nested_model("ObservationResult", ResultV6,
                                {"id", "sample_id", "state_id", "protocol_id", "definition"})
SampleRelation = nested_model("SampleRelation", SampleRelationV6, set())
ConditionSupport = nested_model("ConditionSupport", ConditionSupportV6, set())


class RelationalObservation(DefinedObservation):
    result: ObservationResult


class RelationContextBinding(DefinitionContextBinding):
    entity: Literal["sample", "state", "protocol", "definition", "result", "sample_relation", "condition_support"]


class CarriedRelationContext(CarriedDefinitionContext):
    bindings: list[RelationContextBinding] = Field(min_length=1)


class ExcludedRelationContext(ExcludedDefinitionContext):
    bindings: list[RelationContextBinding] = Field(max_length=0)


class RelationalExtraction(NativeExtraction):
    schema_version: Literal["materials-ner-shared/4"]
    states: list[RelationalState]
    protocols: list[RelationalProcedure]
    observations: list[RelationalObservation]
    sample_relations: list[SampleRelation] = Field(default_factory=list)
    condition_supports: list[ConditionSupport] = Field(default_factory=list)
    context_dispositions: list[CarriedRelationContext | ExcludedRelationContext]

    @model_validator(mode="after")
    def relation_graph(self):
        relation_references(self.samples, self.states, self.protocols, self.observations,
                            self.sample_relations, self.condition_supports)
        return self

    def entity_maps(self):
        return dict(super().entity_maps(), sample_relation={x.id:x for x in self.sample_relations},
                    condition_support={x.id:x for x in self.condition_supports})

    def expand(self, bundle):
        catalog = source_catalog(bundle)
        if self.work_id != bundle.work_id: raise ValueError("work_binding_mismatch")
        def evidence(entity, prefix=""):
            return [{"block_id": q["block_id"], "quote": q["quote"], "field": prefix + field}
                for ref in entity.evidence for q in selected_quotes(catalog, ref.span_ids) for field in ref.fields]
        data = {"schema_version":"materials-ner/6", "work_id":self.work_id,
                **self.completion.model_dump(), "limitations":self.limitations}
        for name in ("processed_block_ids", "unread_block_ids"):
            data[name] = [catalog["blocks"][a]["block_id"] for a in getattr(self,name)]
        for name in ("samples", "states", "protocols", "sample_relations", "condition_supports"):
            data[name] = [dict(e.model_dump(exclude={"evidence"}),evidence=evidence(e)) for e in getattr(self,name)]
        data["results"] = []
        for observation in self.observations:
            result = observation.result.model_dump(exclude={"evidence"})
            result.update(id=observation.id, sample_id=observation.sample_id, state_id=observation.state_id,
                protocol_id=observation.protocol_id, definition=observation.definition.model_dump(exclude={"evidence"}),
                evidence=evidence(observation.result)+evidence(observation.definition,"/definition"))
            data["results"].append(result)
        return ExtractionV6.model_validate(data)

    def validation_entity_ids(self):
        return dict(super().validation_entity_ids(), sample_relations=[x.id for x in self.sample_relations],
                    condition_supports=[x.id for x in self.condition_supports])


def output_schema(bundle=None, inventory=None):
    schema=common_schema(bundle, model=RelationalExtraction, negative_def="NonDetectionV4", conditional_def="ConditionalExistenceV4")
    schema["$defs"]["ConditionalExistenceV4"]=v4_schema()["$defs"]["ConditionalExistenceV4"]
    if inventory is not None:
        ids=[c.id for c in inventory.context_assertions]
        schema["properties"]["context_dispositions"].update(minItems=len(ids),maxItems=len(ids))
        if ids:
            for definition in schema["$defs"].values():
                if "context_id" in definition.get("properties", {}):
                    definition["properties"]["context_id"]["enum"]=ids
    return schema


INSTRUCTIONS = NATIVE_INSTRUCTIONS.replace("materials-ner-shared/3", WIRE_VERSION).replace("condition_index", "condition_id") + """

SOURCE OWNERSHIP V8:
Use one sample object for each explicitly described specimen or component. A
secondary phase, intergrowth or constituent is a separate source-scoped sample
with its own literal formula and target_kind, linked by sample_relations with
relation=component_of. The edge runs FROM component TO parent specimen. Its
relation_raw and each endpoint require source evidence. Do not put a different
component's formula into the parent's additional_formula_assertions. Those
assertions describe only that same subject's alternate bases or literal source
disagreements. A component relation never copies Tc or other parent results into
the component, and never proves a canonical material identity or independent sample.

Every state condition has a local stable id. A procedure context_uses references
state_id and condition_id, never a list index. Actual sample geometry uses role
sample_geometry. Keep the source's full quantity shape and literal expression.
Total specimen thickness is now an allowed result quantity_kind=thickness. It is
different from fitted superconducting_layer_thickness. When two methods each
report a specimen thickness, preserve each method-specific result and the shared
specimen. Repeated mentions without distinct measurement provenance are not extra
independent experiments. Do not label genuine geometry results not_a_result.

A condition_supports edge with relation=measures links a reported property to the
state condition it measures: result_id, state_id and condition_id. Bind its raw
relation and endpoints to the source. Both owners must be the same state/sample,
and property kind and full numeric semantics must agree with the condition.
A fit of superconducting-layer thickness does not measure total specimen geometry.
An approximate repeated total thickness cannot silently replace an exact assertion.
Use no support edge when the relationship is unreported or only a comparison.
Do not invent a measurement method or copy a nearby sample's method to close it.

All source blocks must be accounted for as processed or unread, including context
blocks. This describes the declared read coverage; only the target window's results
are emitted. Root scope is not automatically copied from the inventory read.
Return empty relation/support arrays when no source warrants them. Do not create
extra material-wide columns, automatic scientific approval or training eligibility.

RELATION AND CONDITION OWNERSHIP:
component_of means physical constituent containment, with two distinct subjects.
Repeated runs, new specimens, a pressure/temperature-induced transformation and
comparisons are not component_of. A homogeneous specimen in successive phases
can have distinct source-scoped states without a component relation. Do not
invent individual specimen identities for an aggregate statement about runs.
An inventory assertion's kind is fallible and does not mandate a graph edge.
If a relationship cannot be faithfully represented, retain its context_id with
resolution=unresolved, bindings=[], and a source-grounded explanation. Do not
declare it carried or not_applicable merely to satisfy context accounting.

A reported pressure interval qualifying a result belongs to that result's state
conditions with its literal numeric shape, applicable role and field evidence.
A phase label alone does not preserve this condition. A condition_support edge
requires an actual property result that measures that same condition; it is not
a container for a pressure range or a general inventory-context relationship.
Keep measurement conditions, detection limits and normal-state fitting ranges
separate. If the schema cannot express a fitting role, preserve the source's
fitting description in its applicable procedure and mark that typed context
unresolved. Never relabel it as a measurement or detection window to fit the enum.

Before returning, resolve every context binding against the entities actually
emitted in this response. Do not reference a planned but absent entity. Bind a
state condition to its actual /conditions/N field and source evidence. Only
generated nonempty fields can be carried; unresolved information stays explicit.

EVIDENCE AND SCOPE SELF-CHECK BEFORE RETURNING:
For every sample bind /label when present, /target_kind, /formula_raw,
/form_raw and /substrate_raw when present, plus every reported
/additional_formula_assertions/N and a conflicted /identity_resolution.
For every relation bind /from_sample_id, /to_sample_id, /relation and
/relation_raw. Every separately declared constituent needs its own relation to
the actual parent; a sibling constituent's relation does not connect it.
A homogeneous sample's named phase need not be duplicated as a component object
merely because the source uses the word phase. Retain only useful source-owned
distinctions. A conflicted formula assertion must retain each source spelling on
the same relevant subject, without borrowing another specimen's formula.

Every *_raw value is literal source text, including PDF spelling, hyphenation
and adjacent joined tokens. Only whitespace differences may be ignored. Do not
paraphrase a raw criterion, relation or qualifier. A short exact source excerpt
is preferable to an invented explanatory phrase. Explanations belong in reason
or limitations. Check /criterion and /criterion_raw separately on definitions.
Use the actual span containing a quantity, not only a nearby context span.
For text split across spans select both. Do not add units to a raw numeric token
when the source puts the unit elsewhere; preserve the typed unit and its evidence.
Every context binding must point to a present nonempty field and that field's
evidence must include the source context. Never point to an empty qualifier list.

Look again at each TARGET span after completing the inventory accounting. An
approximate transition without a stated criterion is still a reported Tc with
criterion=unspecified. It must not disappear into a context description. Add a
missed result using additional_items even if the first read put it only in context.
Apply the same rule to explicitly reported geometric measurements. Context
closure is not completeness, and an explanation is not an extracted result.
"""

SEMANTICS = SEMANTICS_V6.replace(
    "Actual film thickness is a state thickness condition; fitted superconducting\nlayer thickness is a superconducting_layer_thickness result.",
    "Actual film thickness supplies a state geometry condition. An explicitly\nreported specimen-thickness measurement is ALSO a thickness result with its\nown method, linked by condition_supports when the source and numeric semantics\nagree. Fitted superconducting-layer thickness is a different result.")

INVENTORY_RULES = """V8 INVENTORY SCOPE:
Inventory every source-reported property relevant to the sample, including
explicit measured specimen geometry and fitted/effective physical lengths.
When separate methods report the same specimen property, keep separate items
with their method provenance. Do not merge them merely because numbers agree.
A bare geometry description can supply state context without inventing a new
measurement. Keep a repeated approximate assertion and its source occurrence
visible; do not silently replace it with a more precise report elsewhere.
An approximate superconducting transition without a stated criterion remains
a result item. Calling it a context assertion alone does not account for it.
Do not reinterpret it as onset by looking at another passage.

Keep specimen geometry, measurement/synthesis/simulation conditions, substrate,
composition basis and procedure context with their own source scopes. Each
secondary phase or intergrowth has its own subject and relationship to the
parent sample. A constituent formula is not an alternate whole-sample formula.
Retain genuine source spelling disagreements on the correct subject. A
context-only fact about a distinct unidentified sample stays unassigned, never
borrowed by nearby named samples. Keep conditional Tc bounds separate from
measurement scan limits. Inventory closure is not scientific acceptance.

Use sample_relation for a source statement about specimen/component identity or
containment, not as a default label for phase changes, repeated measurements or
correlated properties. Describe those facts as state/condition/procedure context
with their own spans and explicit unresolved scope when necessary. Inventory
categories never require the extractor to invent a supported relation type.
"""


def inventory_render(bundle):
    return "\n".join([BASE_INVENTORY, INVENTORY_COMPLETENESS, INVENTORY_RULES,
        source_text(bundle), "Return the source inventory with all reported result items."])


def inventory_render_repair(bundle, inventory, validation):
    return "\n".join([inventory_render(bundle), REPAIR_INSTRUCTIONS,
        "PREVIOUS_INVENTORY: "+canonical(inventory.model_dump()),
        "DETERMINISTIC_DIAGNOSTICS: "+canonical(validation), "Return the corrected inventory JSON."])


PROMPT_HASH=digest({"version":PROMPT_VERSION,"native_prompt":NATIVE_PROMPT_HASH,"instructions":INSTRUCTIONS,
    "semantics":SEMANTICS,"inventory":BASE_INVENTORY,"inventory_rules":INVENTORY_RULES,
    "inventory_completeness":INVENTORY_COMPLETENESS,"inventory_repair":REPAIR_INSTRUCTIONS})


def render(bundle, inventory):
    return "\n".join([SCIENTIFIC_V6,REGISTRY_INSTRUCTIONS,SEMANTICS,CONDITIONAL_INSTRUCTIONS,
        INSTRUCTIONS,INVENTORY_COMPLETENESS,"FIRST_READ_INVENTORY (fallible model proposals):",
        canonical(inventory.model_dump()),source_text(bundle),"END_SOURCE. Return the complete native relation graph."])
