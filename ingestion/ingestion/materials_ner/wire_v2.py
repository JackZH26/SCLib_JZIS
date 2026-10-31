"""Second-generation extraction transport with audited inventory dispositions."""
from collections import Counter
from copy import deepcopy
from typing import Literal

from pydantic import Field

from .contract import StrictModel, State, canonical, digest, output_schema as canonical_schema
from .contract_v2 import ExtractionV2, ProtocolV2, ResultV2, SampleV2
from .evidence import selected_quotes, source_catalog
from .inventory import (INSTRUCTIONS as INVENTORY_INSTRUCTIONS, REPAIR_INSTRUCTIONS, Inventory, InventoryItem,
                        source_text, strict_schema, targets, validate_inventory)
from .prompt import INSTRUCTIONS as SCIENTIFIC_INSTRUCTIONS
from .quantities import REGISTRY_INSTRUCTIONS
from .wire import (EmptyCompletion, ResultsCompletion, IncompleteCompletion,
                   nested_model, INSTRUCTIONS as LEGACY_WIRE_INSTRUCTIONS)

WIRE_VERSION="materials-ner-compact/4"
PROMPT_VERSION="materials-ner-prompt/2.3.0"

ObservationSample=nested_model("ObservationSample",SampleV2,{"id"})
ObservationState=nested_model("ObservationState",State,{"id","sample_id"})
ObservationProtocol=nested_model("ObservationProtocol",ProtocolV2,{"id"})
ObservationResult=nested_model("ObservationResult",ResultV2,{"id","sample_id","state_id","protocol_id"})


class Observation(StrictModel):
    id: str
    inventory_item_ids: list[str]=Field(min_length=1)
    sample: ObservationSample
    state: ObservationState
    protocol: ObservationProtocol
    result: ObservationResult


class UnextractedItem(StrictModel):
    item_id: str
    reason: Literal["not_a_result", "insufficient_context", "unresolved"]
    explanation: str=Field(min_length=1)


class CompactExtractionV2(StrictModel):
    schema_version: Literal["materials-ner-compact/4"]
    work_id: str
    completion: EmptyCompletion | ResultsCompletion | IncompleteCompletion
    processed_block_ids: list[str]
    unread_block_ids: list[str]
    limitations: list[str]
    observations: list[Observation]
    # The first pass may miss a result. New source-bound items are permitted;
    # the model must not omit a genuine result to agree with its first read.
    additional_items: list[InventoryItem]
    unextracted_items: list[UnextractedItem]

    def expanded_payload(self,bundle):
        catalog=source_catalog(bundle)
        if self.work_id!=bundle.work_id: raise ValueError("work_binding_mismatch")
        if any(a not in catalog["blocks"] for a in self.processed_block_ids+self.unread_block_ids):
            raise ValueError("unknown_source_block_alias")
        data={"schema_version":"materials-ner/2","work_id":self.work_id,**self.completion.model_dump(),
              "limitations":self.limitations,"samples":[],"states":[],"protocols":[],"results":[]}
        for name in ("processed_block_ids","unread_block_ids"):
            data[name]=[catalog["blocks"][a]["block_id"] for a in getattr(self,name)]
        for obs in self.observations:
            sid,stid,pid=f"s:{obs.id}",f"st:{obs.id}",f"p:{obs.id}"
            for name,entity,ids in (("samples",obs.sample,{"id":sid}),
                                   ("states",obs.state,{"id":stid,"sample_id":sid}),
                                   ("protocols",obs.protocol,{"id":pid}),
                                   ("results",obs.result,{"id":obs.id,"sample_id":sid,"state_id":stid,"protocol_id":pid})):
                body=entity.model_dump(exclude={"evidence"});body.update(ids)
                body["evidence"]=[{"block_id":q["block_id"],"quote":q["quote"],"field":field}
                                  for ref in entity.evidence for q in selected_quotes(catalog,ref.span_ids) for field in ref.fields]
                data[name].append(body)
        return data

    def expand(self,bundle):
        return ExtractionV2.model_validate(self.expanded_payload(bundle))


def output_schema(bundle=None,model=CompactExtractionV2,negative_def="NonDetection",conditional_def="ConditionalExistence"):
    schema=strict_schema(model)
    schema["$defs"]["Quantity"]=canonical_schema()["$defs"]["Quantity"]
    result=schema["$defs"]["ObservationResult"]
    numeric,transition,negative=deepcopy(result),deepcopy(result),deepcopy(result)
    numeric["properties"]["quantity_kind"]["enum"]=[k for k in numeric["properties"]["quantity_kind"]["enum"] if k not in {"non_detection","tc"}]
    transition["properties"]["quantity_kind"]["enum"]=["tc"]
    # A conditional superconducting existence is not an established Tc label.
    # This narrows the generation schema, while historical v4 receipts remain
    # parseable and subject to post-generation validation.
    transition["properties"]["qualifiers"]["items"]={"anyOf":[
        {"$ref":"#/$defs/TransitionStage"},{"$ref":"#/$defs/TemperatureRole"}]}
    negative["properties"]["quantity_kind"]["enum"]=["non_detection"]
    unresolved=deepcopy(schema["$defs"]["Quantity"]["anyOf"][-1])
    unresolved["properties"]["status"]["enum"]=["not_applicable"]
    negative["properties"]["quantity"]=unresolved
    negative["properties"]["qualifiers"]["minItems"]=1
    negative["properties"]["qualifiers"]["items"]={"anyOf":[
        {"$ref":"#/$defs/"+negative_def},{"$ref":"#/$defs/"+conditional_def}]}
    schema["$defs"]["ObservationResult"]={"anyOf":[numeric,transition,negative]}
    if bundle:
        catalog=source_catalog(bundle)
        schema["properties"]["work_id"]["enum"]=[bundle.work_id]
        for key in ("processed_block_ids","unread_block_ids"):
            schema["properties"][key]["items"]["enum"]=list(catalog["blocks"])
        schema["$defs"]["EvidenceReference"]["properties"]["span_ids"]["items"]["enum"]=list(catalog["spans"])
        for key in ("source_span_ids","context_span_ids"):
            schema["$defs"]["InventoryItem"]["properties"][key]["items"]["enum"]=sorted(targets(catalog)) if key=="source_span_ids" else list(catalog["spans"])
    return schema


INSTRUCTIONS=LEGACY_WIRE_INSTRUCTIONS.replace("materials-ner-compact/3",WIRE_VERSION)+"""

ADDITIONAL V2 CONTRACT:
The source inventory below is a fallible first model read, not authoritative
evidence. Re-read the actual source. Every observation references its
inventory_item_ids. Account for EVERY inventory item: emit it, or explicitly
record an unextracted_items entry with a reason. Unextracted entries require
review. If another genuine result was missed by the first read, create a new ID
in additional_items with its literal source value/spans and emit its observation.
Only an actual TARGET result may be added. Do not add numerical results found
only in CONTEXT, and never attach an unrelated target span to such a value.
The result's /quantity (or non_detection /quantity_kind) evidence and its
inventory item must identify the SAME target assertion. An inventory ID belongs
to exactly one emitted result or one unextracted entry; never reuse it for a
different property, sample or value. Several IDs on one result are allowed only
for repeated mentions of that exact result, not for all properties of a sample.
Do not silently omit rows. Repeated mentions can point to ONE observation with
several inventory IDs only when they describe the same sample/state/protocol/result.
Keep numerically equal values from different methods separate.

Set protocol.method_class from source-supported method/observable context, using
resistivity for four-probe electrical resistance and magnetization for magnetic
susceptibility. Keep method as the exact descriptive name and bind /method_class
as well as /method. A table's method can be defined elsewhere in the paper.
Use protocol.parameters for probe frequency, magnetic-field amplitude/convention,
or a reported Coulomb pseudopotential. Frequency in Hz is NOT a delay. Each
parameter needs /parameters/N evidence including the unit header if separate.
Do not add a parameter when it is not supplied by this source.

Use result.qualifiers only when applicable, with /qualifiers/N evidence:
* transition_stage preserves explicit primary/secondary/other stage separately
  from onset or zero_resistance. Secondary onset still has criterion=onset.
* non_detection states the absent superconducting observable, target and
  existence=not_established; the state retains the actual detection window.
  Every non_detection result must carry this qualifier. Absence of magnetism or
  phonon instability does not imply absence of superconductivity.
* conditional_existence preserves 'if superconducting' explicitly. Such a paper
  does not establish a superconducting Tc below the floor. Prefer non_detection
  plus detection window and conditional_existence to a plain Tc upper bound.
  Retain one non_detection per named sample even if the first inventory missed
  these: add source-bound items with value_raw=null. Do not omit a non-detection
  simply because its superconducting existence is unestablished. The quantity
  is not_applicable, not a numeric Tc=0 or an asserted Tc below the floor.
* temperature_role distinguishes a system_transition from a
  component_model_parameter. Supply it for any fitted Tc/model temperature.
  Fitting a theoretical transition from Eliashberg solutions can estimate system
  Tc; a surface/band curve parameter is not automatically the bulk Tc. A
  component_model_parameter uses model_temperature_scale, not tc.
Each qualifier's raw string is a literal contiguous source expression, not an
invented summary. Do not supply a stage just because one temperature is larger.

Keep additional_formula_assertions only for genuinely additional source formulas
or composition bases. Bind /additional_formula_assertions/N; preserve stated
nominal, measured, refined or calculation-input bases. The sample's formula_raw
is a literal display assertion, not canonical composition. Source disagreement
requires identity_resolution=conflicted and evidence for the disagreement;
never repair an apparent typo silently. Carry relevant sample/protocol context
consistently to each result, but do not invent relations between samples.
Empty lists mean no such proposal was supplied, not that all literature is silent.
Use English descriptions; preserve literal source formulas, numbers and notation.
"""
EXTRACTION_REPAIR_INSTRUCTIONS="""The previous extraction failed evidence checks.
Re-read the original TARGET and CONTEXT spans and return ONE complete extraction
with EVIDENCE-ONLY corrections. Keep every non-evidence field EXACTLY unchanged,
including values, raw expressions, qualifiers, methods, composition, inventory
IDs and dispositions. These fields are proposals, not authoritative scientific
facts, but changes to them require a separate scientific revision and review.
For field_evidence_missing, supply the indexed field's actual supporting spans;
never point to unrelated text. Remove evidence pointers for fields that are null.
Preserve all unaffected evidence references. If no span supports a proposed
field, do not invent support or rewrite the field to clear the check. Keep the
failure and describe it in limitations. Unregistered quantities remain unmapped;
this read cannot relabel or scientifically approve them. The program rejects any
repair that changes a scientific payload or introduces a new validation issue.
This is a single bounded evidence correction attempt, not scientific adjudication.
"""

REPAIRABLE_CODES=frozenset({"field_evidence_missing","evidence_field_not_present",
    "qualifier_raw_not_in_field_evidence","quantity_raw_not_in_field_evidence",
    "inventory_result_evidence_disconnected"})

PROMPT_HASH=digest({"version":PROMPT_VERSION,"science":SCIENTIFIC_INSTRUCTIONS,
                    "registry":REGISTRY_INSTRUCTIONS,"wire":INSTRUCTIONS,"inventory":INVENTORY_INSTRUCTIONS,
                    "inventory_repair":REPAIR_INSTRUCTIONS,"extraction_repair":EXTRACTION_REPAIR_INSTRUCTIONS})


def render(bundle,inventory):
    return "\n".join([SCIENTIFIC_INSTRUCTIONS,REGISTRY_INSTRUCTIONS,INSTRUCTIONS,
                      "FIRST_READ_INVENTORY (model proposals; verify against source):",
                      canonical(inventory.model_dump()),source_text(bundle),
                      "END_SOURCE. Return complete extraction JSON with inventory dispositions."])


def render_repair(bundle,inventory,previous,validation):
    return "\n".join([SCIENTIFIC_INSTRUCTIONS,REGISTRY_INSTRUCTIONS,INSTRUCTIONS,
        EXTRACTION_REPAIR_INSTRUCTIONS,"FIRST_READ_INVENTORY: "+canonical(inventory.model_dump()),
        "PREVIOUS_EXTRACTION: "+canonical(previous.model_dump()),
        "DETERMINISTIC_DIAGNOSTICS: "+canonical(validation["issues"]),source_text(bundle),
        "Return the complete corrected extraction JSON with inventory dispositions."])


def validate_coverage(compact,inventory,bundle):
    catalog=source_catalog(bundle);target=targets(catalog)
    checks=validate_inventory(inventory,bundle)
    issues=[{"code":"first_read_"+i["code"],"path":"/"} for i in checks["issues"]]
    all_items=inventory.items+compact.additional_items
    ids=[i.id for i in all_items]
    if len(ids)!=len(set(ids)):issues.append({"code":"inventory_additional_id_collision","path":"/"})
    for item in compact.additional_items:
        try:
            if not set(item.source_span_ids)<=target:raise ValueError("target")
            quotes=selected_quotes(catalog,item.source_span_ids)
            if item.context_span_ids:selected_quotes(catalog,item.context_span_ids)
            if item.value_raw is not None and (not item.value_raw.strip() or not any(
                " ".join(item.value_raw.split()) in " ".join(q["quote"].split()) for q in quotes)):
                raise ValueError("raw")
        except ValueError:
            issues.append({"code":"additional_inventory_source_invalid","path":"/"})
    emitted=Counter(i for o in compact.observations for i in o.inventory_item_ids)
    withheld=Counter(i.item_id for i in compact.unextracted_items)
    if emitted+withheld!=Counter(ids):issues.append({"code":"inventory_disposition_not_closed","path":"/"})
    if compact.unextracted_items:issues.append({"code":"inventory_unextracted_results_require_review","path":"/"})
    items={i.id:i for i in all_items}
    for n,obs in enumerate(compact.observations):
        # Scope binding is necessary, but cannot prove a semantic pairing.
        spans={s for ref in obs.result.evidence if any(f in ref.fields for f in ("/quantity","/quantity_kind")) for s in ref.span_ids}
        if any(identifier in items and not spans.intersection(items[identifier].source_span_ids) for identifier in obs.inventory_item_ids):
            issues.append({"code":"inventory_result_evidence_disconnected","path":f"/results/{n}"})
    return {"schema":"materials-inventory-closure/1","valid":not issues,"issues":issues,
            "first_read_inventory_sha256":digest(inventory.model_dump()),
            "first_read_items":len(inventory.items),"additional_items":len(compact.additional_items),
            "emitted_items":len(emitted),"unextracted_items":[i.model_dump() for i in compact.unextracted_items],
            "result_mapping":{o.id:o.inventory_item_ids for o in compact.observations},
            "source_semantic_coverage_verified":False,"independent_gold":False,"scientific_acceptance":False}
