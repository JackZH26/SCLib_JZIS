"""Source-scoped conditional assertions with honest measurement-window missingness."""
from typing import Literal

from .contract import canonical,digest
from .contract_v4 import ExtractionV4,ResultV4
from .evidence_patch import INSTRUCTIONS as PATCH_INSTRUCTIONS
from .inventory import INSTRUCTIONS as INVENTORY_BASE,source_text,REPAIR_INSTRUCTIONS
from .prompt import INSTRUCTIONS as SCIENTIFIC_BASE
from .quantities import REGISTRY_INSTRUCTIONS
from .wire import nested_model
from .wire_v2 import output_schema as shared_schema
from .wire_v3 import (CompactExtractionV3,Observation as ObservationV3,INSTRUCTIONS as V3_INSTRUCTIONS,
    CONTEXT_INVENTORY_INSTRUCTIONS,validate_coverage)

WIRE_VERSION="materials-ner-compact/6"
PROMPT_VERSION="materials-ner-prompt/4.0.0"
ObservationResult=nested_model("ObservationResult",ResultV4,{"id","sample_id","state_id","protocol_id"})


class Observation(ObservationV3):
    result: ObservationResult


class CompactExtractionV4(CompactExtractionV3):
    schema_version: Literal["materials-ner-compact/6"]
    observations: list[Observation]

    def expand(self,bundle):
        payload=self.expanded_payload(bundle)
        payload["schema_version"]="materials-ner/4"
        return ExtractionV4.model_validate(payload)


SCIENTIFIC_INSTRUCTIONS=SCIENTIFIC_BASE.replace(
    "non-numeric not_applicable quantity, and a temperature detection_window in its\nstate.",
    "non-numeric not_applicable quantity. A source-reported temperature detection_window\nbelongs in its state; otherwise window_status records its unavailability.")
INVENTORY_INSTRUCTIONS=INVENTORY_BASE.replace(
    "a measurement floor is not an unconditional superconducting transition.",
    "a threshold is not an unconditional superconducting transition or a reported scan window.")
INSTRUCTIONS=V3_INSTRUCTIONS.replace("materials-ner-compact/5",WIRE_VERSION).replace(
    "Prefer non_detection\n  plus detection window and conditional_existence to a plain Tc upper bound.",
    "Use non_detection with conditional_existence; preserve the conditional Tc bound\n  separately. Include a detection window only when the source actually reports it.")
INSTRUCTIONS += """

V4 CONDITIONAL ASSERTIONS AND WINDOW MISSINGNESS:
Every non_detection qualifier has window_status. Choose reported ONLY if the
source actually supplies measurement coverage and the corresponding state
contains that temperature detection_window. Otherwise choose
not_reported_in_supplied_source, not_accessible, or unresolved. Missing scan
limits do not justify omitting the source assertion or inventing a temperature
condition. A device name, its usual operating range, and a conditional Tc bound
are not source-reported scan limits. Do not use outside knowledge of instruments.

ConditionalExistence carries an optional tc_bound Quantity for a bound explicitly
stated by the authors under 'if superconducting'. Preserve the literal expression
and its numeric bound (lt/le/interval), not a point Tc. This bound is NOT a state
condition, observation window, or confirmed negative-training label. The main
non_detection quantity remains not_applicable. Use null tc_bound if absent.
Bind the qualifier's raw conditional wording at /qualifiers/N and any reported
tc_bound separately at /qualifiers/N/tc_bound. The latter raw expression includes
the original inequality wording, for example 'below 2.7 K', without replacing it
with an invented printed '<'. The numeric upper value is 2.7, relation=lt.
The example is synthetic guidance, never a source result.

When window_status is not reported, do not add a reported detection_window from
the same conditional bound. Keep all actually supplied preparation, geometry,
substrate and measurement-method facts. Missing a measurement window prevents
window-dependent ML use; it is not a structural extraction failure by itself.
For a table cell, quantity.raw is its literal numeric lexeme. Its unit can come
from a separately bound header; do not concatenate a unit to the raw cell text.
"""


def output_schema(bundle=None):
    schema=shared_schema(bundle,model=CompactExtractionV4,
        negative_def="NonDetectionV4",conditional_def="ConditionalExistenceV4")
    allowed=[]
    for branch in schema["$defs"]["Quantity"]["anyOf"]:
        relation=branch["properties"]["relation"].get("enum",[])
        if branch["properties"]["relation"].get("type")=="null" or any(r in {"lt","le","interval"} for r in relation):
            allowed.append(branch)
    schema["$defs"]["ConditionalExistenceV4"]["properties"]["tc_bound"]={"anyOf":[*allowed,{"type":"null"}]}
    return schema


def inventory_render(bundle):
    return "\n".join([INVENTORY_INSTRUCTIONS,CONTEXT_INVENTORY_INSTRUCTIONS,
        "A conditional Tc threshold is a result qualifier, not automatically a measured scan limit. Preserve both its conditionality and any explicitly reported measurement coverage separately.",
        source_text(bundle),"Return the complete source inventory JSON."])


def inventory_render_repair(bundle,inventory,validation):
    return "\n".join([inventory_render(bundle),REPAIR_INSTRUCTIONS,
        "PREVIOUS_INVENTORY: "+canonical(inventory.model_dump()),
        "DETERMINISTIC_DIAGNOSTICS: "+canonical(validation),"Return the corrected inventory JSON."])


def render(bundle,inventory):
    return "\n".join([SCIENTIFIC_INSTRUCTIONS,REGISTRY_INSTRUCTIONS,INSTRUCTIONS,
        "FIRST_READ_INVENTORY (fallible proposals, not source truth): "+canonical(inventory.model_dump()),
        source_text(bundle),"Return actual observations and their result/context dispositions."])


PROMPT_HASH=digest({"version":PROMPT_VERSION,"science":SCIENTIFIC_INSTRUCTIONS,
    "registry":REGISTRY_INSTRUCTIONS,"wire":INSTRUCTIONS,"inventory":INVENTORY_INSTRUCTIONS,
    "context_inventory":CONTEXT_INVENTORY_INSTRUCTIONS,"inventory_repair":REPAIR_INSTRUCTIONS,
    "evidence_patch":PATCH_INSTRUCTIONS})
