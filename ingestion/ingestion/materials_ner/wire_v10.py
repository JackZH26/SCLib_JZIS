"""Native graph transport with target-specific non-detection semantics."""
from typing import Literal

from .contract import canonical, digest
from .contract_v8 import ExtractionV8, ResultV8
from .evidence import source_catalog, selected_quotes
from .inventory import source_text, REPAIR_INSTRUCTIONS
from .wire import nested_model
from .wire_v2 import output_schema as common_schema
from .wire_v4 import output_schema as conditional_schema
from .wire_v8 import RelationalObservation
from .wire_v9 import (ScopedExtraction, validate_coverage, BASE_INVENTORY, SCIENTIFIC_V6,
    REGISTRY_INSTRUCTIONS, SEMANTICS, CONDITIONAL_INSTRUCTIONS, INVENTORY_COMPLETENESS,
    INVENTORY_RULES, INSTRUCTIONS as PREVIOUS_INSTRUCTIONS, PROMPT_HASH as PREVIOUS_PROMPT_HASH)

WIRE_VERSION = "materials-ner-shared/6"
PROMPT_VERSION = "materials-ner-prompt/10.0.0"
ObservationResult = nested_model("ObservationResult", ResultV8, {"id", "sample_id", "state_id", "protocol_id", "definition"})


class DetectionObservation(RelationalObservation):
    result: ObservationResult


class DetectionExtraction(ScopedExtraction):
    schema_version: Literal["materials-ner-shared/6"]
    observations: list[DetectionObservation]

    def expand(self, bundle, *, canonical_model=ExtractionV8, canonical_version="materials-ner/8"):
        catalog = source_catalog(bundle)
        if self.work_id != bundle.work_id: raise ValueError("work_binding_mismatch")
        def evidence(entity, prefix=""):
            return [{"block_id": q["block_id"], "quote": q["quote"], "field": prefix+field}
                for ref in entity.evidence for q in selected_quotes(catalog, ref.span_ids) for field in ref.fields]
        data = {"schema_version": canonical_version, "work_id": self.work_id,
                **self.completion.model_dump(), "limitations": self.limitations}
        for name in ("processed_block_ids", "unread_block_ids"):
            data[name] = [catalog["blocks"][alias]["block_id"] for alias in getattr(self, name)]
        for name in ("samples", "states", "protocols", "sample_relations", "condition_supports"):
            data[name] = [dict(entity.model_dump(exclude={"evidence"}), evidence=evidence(entity)) for entity in getattr(self, name)]
        data["results"] = []
        for observation in self.observations:
            result = observation.result.model_dump(exclude={"evidence"})
            result.update(id=observation.id, sample_id=observation.sample_id, state_id=observation.state_id,
                protocol_id=observation.protocol_id, definition=observation.definition.model_dump(exclude={"evidence"}),
                evidence=evidence(observation.result)+evidence(observation.definition,"/definition"))
            data["results"].append(result)
        return canonical_model.model_validate(data)


def output_schema(bundle=None, inventory=None):
    schema=common_schema(bundle,model=DetectionExtraction,negative_def="NonDetectionV8",conditional_def="ConditionalExistenceV4")
    schema["$defs"]["ConditionalExistenceV4"]=conditional_schema()["$defs"]["ConditionalExistenceV4"]
    if inventory is not None:
        ids=[c.id for c in inventory.context_assertions]
        schema["properties"]["context_dispositions"].update(minItems=len(ids),maxItems=len(ids))
        if ids:
            for definition in schema["$defs"].values():
                if "context_id" in definition.get("properties",{}):definition["properties"]["context_id"]["enum"]=ids
    return schema


DETECTION_INSTRUCTIONS = """TARGET-SPECIFIC NON-DETECTION V10:
non_detection is a source-reported failure to resolve one specified observable.
target=superconductivity uses resistive_transition, zero_resistance,
diamagnetic_signal, heat_capacity_anomaly or unspecified. A device supercurrent
uses target=supercurrent and observable=supercurrent. An unresolved Josephson
0-pi transition uses target=josephson_phase_transition and observable=zero_pi_transition.
These are different statements. Never infer absence of superconductivity,
Tc=0 or a conditional Tc bound from either device observable. Other targets
remain explicit unresolved source items, never forced into these choices.
The result quantity is not_applicable, with no numeric value or temperature bound.
Keep one non_detection qualifier with literal raw wording and indexed evidence.

window_condition_ids explicitly select conditions on this result's state. A
reported superconductivity window selects temperature/detection_window conditions.
Device scan windows select detection_window or study_extent conditions of
temperature, thickness, pressure or applied magnetic field. A fit window,
sample geometry point or synthesis setting is not a detection scan. Keep such
relevant settings separately on the state; do not copy another result's window.
Set window_status=reported only with nonempty supported IDs. Otherwise use an
explicit unavailable/unresolved status and empty IDs; never fabricate endpoints.

sensitivities is a sparse list, empty unless the source reports such information.
Each item has role measurement_step, instrument_resolution, detection_threshold
or noise_floor; quantity_kind electric_current; the complete source quantity;
and literal raw wording. Other sensitivity dimensions remain unresolved pending
a source-backed registry extension. A current step is measurement_step, not a calibrated detection threshold or upper
bound on the unobserved signal. Current units A, mA, uA, μA,
nA and pA are supported without changing the source unit. Select exact evidence
for /qualifiers/N and each /qualifiers/N/sensitivities/M including unit/context.
Preserve sample, fit, citation and protocol scope. Extraction remains pending
review and does not create a negative ML label or permission to promote.
"""
INSTRUCTIONS=PREVIOUS_INSTRUCTIONS.replace("materials-ner-shared/5",WIRE_VERSION).replace(
    "* non_detection states the absent superconducting observable, target and",
    "* non_detection states the specific unresolved observable, target and")+"\n"+DETECTION_INSTRUCTIONS
PROMPT_HASH=digest({"version":PROMPT_VERSION,"previous_prompt":PREVIOUS_PROMPT_HASH,"instructions":INSTRUCTIONS})


def inventory_render(bundle):
    return "\n".join([BASE_INVENTORY,INVENTORY_COMPLETENESS,INVENTORY_RULES,DETECTION_INSTRUCTIONS,
                      source_text(bundle),"Return all result items, including target-specific non-detections and unresolved physical quantities."])


def inventory_render_repair(bundle, inventory, validation):
    return "\n".join([inventory_render(bundle),REPAIR_INSTRUCTIONS,"PREVIOUS_INVENTORY: "+canonical(inventory.model_dump()),
        "DETERMINISTIC_DIAGNOSTICS: "+canonical(validation),"Return the corrected inventory JSON."])


def render(bundle, inventory):
    return "\n".join([SCIENTIFIC_V6,REGISTRY_INSTRUCTIONS,SEMANTICS,CONDITIONAL_INSTRUCTIONS,INSTRUCTIONS,
        INVENTORY_COMPLETENESS,"FIRST_READ_INVENTORY (fallible model proposals):",canonical(inventory.model_dump()),
        source_text(bundle),"END_SOURCE. Return the complete target-specific graph."])
