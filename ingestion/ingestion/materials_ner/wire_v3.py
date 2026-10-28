"""Context accounting and sparse scientific semantics for empirical v3 runs."""
from collections import Counter
import re
from typing import Literal

from pydantic import Field

from .contract import StrictModel,canonical,digest
from .contract_v2 import SampleV2
from .contract_v3 import ExtractionV3,StateV3,ProtocolV3,ResultV3
from .evidence import source_catalog,equivalent_location_spans
from .inventory import INSTRUCTIONS as INVENTORY_INSTRUCTIONS,source_text,render_repair as inventory_repair
from .prompt import INSTRUCTIONS as SCIENTIFIC_INSTRUCTIONS
from .quantities import REGISTRY_INSTRUCTIONS
from .wire import nested_model
from .wire_v2 import CompactExtractionV2,INSTRUCTIONS as V2_INSTRUCTIONS,output_schema as shared_schema,validate_coverage as result_coverage

WIRE_VERSION="materials-ner-compact/5"
PROMPT_VERSION="materials-ner-prompt/3.1.0"

ObservationSample=nested_model("ObservationSample",SampleV2,{"id"})
ObservationState=nested_model("ObservationState",StateV3,{"id","sample_id"})
ObservationProtocol=nested_model("ObservationProtocol",ProtocolV3,{"id"})
ObservationResult=nested_model("ObservationResult",ResultV3,{"id","sample_id","state_id","protocol_id"})


class Observation(StrictModel):
    id: str
    inventory_item_ids: list[str]=Field(min_length=1)
    sample: ObservationSample
    state: ObservationState
    protocol: ObservationProtocol
    result: ObservationResult


class ContextBinding(StrictModel):
    observation_id: str
    entity: Literal["sample","state","protocol","result"]
    field: str=Field(pattern=r"^/")


class ContextDisposition(StrictModel):
    context_id: str
    resolution: Literal["carried","not_applicable","unresolved"]
    bindings: list[ContextBinding]
    explanation: str | None


class CompactExtractionV3(CompactExtractionV2):
    schema_version: Literal["materials-ner-compact/5"]
    observations: list[Observation]
    context_dispositions: list[ContextDisposition]

    def expand(self,bundle):
        payload=self.expanded_payload(bundle)
        payload["schema_version"]="materials-ner/3"
        return ExtractionV3.model_validate(payload)


CONTEXT_INVENTORY_INSTRUCTIONS="""
V3 CONTEXT INVENTORY:
Make separate context_assertions for each relevant source fact, sample and role,
rather than combining several conditions in one vague description. Include the
sample name and literal expression in the description. Include supplied sample
thickness, substrate, preparation, detection limits, measurement/calculation
settings and experimental/theoretical input provenance relevant to TARGET results.
Structural thickness is sample/state context even when it is not itself a
superconducting result; do not silently discard it. Keep measured total-film
thickness distinct from fitted superconducting-layer thickness. Avoid inventorying
unrelated context-only literature results as conditions for the target samples.
A calculation or fit using measured inputs remains an experimental derivation.
Do not identify its origin merely from the words 'calculated' or 'fitted'.
"""

INSTRUCTIONS=V2_INSTRUCTIONS.replace("materials-ner-compact/4",WIRE_VERSION)+"""

V3 CONTEXT AND MEASUREMENT SEMANTICS:
Every first-read context_assertion must have exactly one context_dispositions
entry. For carried context, list every applicable observation/entity/field to
which it is transferred and bind that field to the actual source evidence.
Use indexed fields, e.g. /conditions/0 or /parameters/0. An empty array, null,
or limitations text cannot count as carrying context. One context fact may
apply to several observations, but never copy conditions between unrelated
samples. not_applicable needs a concrete reason; unresolved remains for review.
Keep the actual sample thickness, form and substrate in the corresponding
existing fields when supplied. Keep preparation conditions under synthesis,
not measurement. Do not omit them merely because they are not result rows.
Use state.preparation_raw for a source-reported preparation description and
sample.substrate_raw for its substrate. Use a thickness condition for the
actual sample geometry with its stated role (unknown if unstated). A synthesis
condition is valid context for a measurement result; it is not a measurement
condition and not an extra result. A fitted analysis belongs in protocol.method
or details_raw even when no separate equation parameter is appropriate.
Do not reject sample geometry or preparation as 'not needed for transition
observations'. Exclude context only for a source-supported applicability reason.

For detection_window conditions set window_position to lower_limit, upper_limit,
interval or unspecified from the source. A lowest measured temperature is a
lower_limit of measurement access, even if the paper constrains a hypothetical
Tc to be BELOW it. The experiment did not observe that lower-temperature region.
Keep the printed threshold as its literal quantity; do not manufacture the
unknown other boundary or claim a Tc point. Outside detection_window,
window_position is null. A radius uses condition.kind=radius, not thickness.
The quantity describes the printed threshold, not an invented temperature
range: a bare '4.2 K' floor uses value=4.2, relation=exact, lower=upper=null,
with window_position=lower_limit. Use a bound relation only when the raw source
itself prints that bound. Do not add >= to a bare threshold.

Classify origin by the inputs and analysis, not by verbs: a value obtained by
algebra from measured critical fields or by fitting/extrapolating measured curves
is model_derived, even if the paper says 'calculated'. Direct readings are
observed. A prediction based on theoretical electronic/phonon structure is
computed, including a system Tc fitted to theoretical gap solutions. Preserve
the analysis in protocol.method/details_raw and relevant input context. Do not
invent dependency IDs when the inputs lie outside this window. Select /origin
evidence that supports the actual provenance. Derived is not a synonym for cited.

For a stated threshold relative to normal resistance, use criterion=resistance_fraction
and a resistance_fraction protocol parameter, keeping the printed percent and
its reference in name_raw/criterion_raw. Do not rename a 90% threshold onset
unless the source itself makes that definition. Explicitly named onset,
secondary onset and zero resistance keep their own criteria/stages.

Use the existing coherence_length kind for GL/in-plane coherence lengths;
qualify direction in component_raw or source-supported context. Newly registered
gl_parameter is the dimensionless penetration-depth/coherence-length ratio,
not an electron-phonon coupling. superconducting_layer_thickness is a RESULT
when estimated by a fit; measured total film thickness remains sample/state
context. electronic_dos_per_atom requires an explicitly reported per-atom DOS
in states/(eV atom); never infer spin, cell, or formula-unit basis. These kinds
remain source-scoped proposals and do not automatically become ML features.

Before returning, check every emitted inventory ID against its own subject,
value and method. In a 'respectively' series, keep the source ordering; formulas
that differ by a subscript are different assertions. Do not move a value between
similar formulas. The first inventory may be wrong: keep any disagreement visible
for review rather than silently changing its meaning. Construct the actual
observations array before listing their context bindings. Descriptions that
claim a result was emitted do not substitute for a JSON observation. Every
context binding must name an observation that is actually present.
"""


def output_schema(bundle=None):
    return shared_schema(bundle,model=CompactExtractionV3)


def inventory_render(bundle):
    return "\n".join([INVENTORY_INSTRUCTIONS,CONTEXT_INVENTORY_INSTRUCTIONS,source_text(bundle),
                      "Return the complete source inventory JSON."])


def inventory_render_repair(bundle,inventory,validation):
    return inventory_repair(bundle,inventory,validation)+"\n"+CONTEXT_INVENTORY_INSTRUCTIONS


def render(bundle,inventory):
    return "\n".join([SCIENTIFIC_INSTRUCTIONS,REGISTRY_INSTRUCTIONS,INSTRUCTIONS,
        "FIRST_READ_INVENTORY (untrusted proposals; verify against source):",
        canonical(inventory.model_dump()),source_text(bundle),
        "Return extraction JSON with result and context dispositions."])


def field_value(value,pointer):
    for part in pointer.lstrip("/").split("/"):
        part=part.replace("~1","/").replace("~0","~")
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value


def validate_coverage(compact,inventory,bundle):
    report=result_coverage(compact,inventory,bundle)
    issues=report["issues"]
    contexts={c.id:c for c in inventory.context_assertions}
    if Counter(d.context_id for d in compact.context_dispositions)!=Counter(list(contexts)):
        issues.append({"code":"context_disposition_not_closed","path":"/"})
    observations={o.id:(i,o) for i,o in enumerate(compact.observations)}
    catalog=source_catalog(bundle)
    items={i.id:i for i in inventory.items+compact.additional_items}
    subject_disagreements=[]
    compact_text=lambda value:re.sub(r"\s+","",value or "")
    labels={compact_text(o.sample.label) for o in compact.observations if o.sample.label}
    simple_formula=re.compile(r"(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?){2,}")
    for index,obs in enumerate(compact.observations):
        formula,label=compact_text(obs.sample.formula_raw),compact_text(obs.sample.label)
        for identifier in obs.inventory_item_ids:
            item=items.get(identifier)
            if item is None:continue
            subject=compact_text(item.sample_raw)
            # A disagreement is a review signal, never an automatic formula
            # correction or a claim that the first model read is authoritative.
            if subject in {formula,label}:continue
            field=None
            if subject in labels:field="/label"
            elif simple_formula.fullmatch(subject) and simple_formula.fullmatch(formula):field="/formula_raw"
            if field:
                issues.append({"code":"inventory_subject_disagreement","path":f"/samples/{index}{field}"})
                subject_disagreements.append({"observation_id":obs.id,"inventory_item_id":identifier,
                    "inventory_subject":item.sample_raw,"proposed_label":obs.sample.label,
                    "proposed_formula":obs.sample.formula_raw,"source_review_required":True})
    exclusions=[]
    for disposition in compact.context_dispositions:
        context=contexts.get(disposition.context_id)
        if disposition.resolution!="carried":
            if disposition.bindings or not disposition.explanation:
                issues.append({"code":"context_disposition_shape_invalid","path":"/"})
            exclusions.append(disposition.model_dump())
            if disposition.resolution=="unresolved":
                issues.append({"code":"source_context_unresolved","path":"/"})
            continue
        if not disposition.bindings:
            issues.append({"code":"carried_context_has_no_field","path":"/"})
        for binding in disposition.bindings:
            found=observations.get(binding.observation_id)
            if found is None or context is None:
                issues.append({"code":"context_binding_target_invalid","path":"/"});continue
            index,obs=found
            entity=getattr(obs,binding.entity)
            path=f"/{binding.entity}s/{index}{binding.field}"
            try:value=field_value(entity.model_dump(),binding.field)
            except (ValueError,KeyError,IndexError,TypeError):value=None
            if value is None or value==[] or value=={} or value=="":
                issues.append({"code":"context_binding_field_empty","path":path})
            spans={s for ref in entity.evidence if binding.field in ref.fields for s in ref.span_ids}
            if not equivalent_location_spans(catalog,spans).intersection(context.span_ids):
                issues.append({"code":"context_field_evidence_disconnected","path":path})
    report.update(schema="materials-inventory-closure/2",valid=not issues,
        context_assertions=len(contexts),context_dispositions=[d.model_dump() for d in compact.context_dispositions],
        context_exclusions=exclusions,context_exclusions_independently_reviewed=False,
        subject_disagreements=subject_disagreements)
    return report


# Source, extraction and repair instructions all participate in the run hash.
from .evidence_patch import INSTRUCTIONS as EVIDENCE_PATCH_INSTRUCTIONS
PROMPT_HASH=digest({"version":PROMPT_VERSION,"science":SCIENTIFIC_INSTRUCTIONS,
    "registry":REGISTRY_INSTRUCTIONS,"wire":INSTRUCTIONS,"inventory":INVENTORY_INSTRUCTIONS,
    "context_inventory":CONTEXT_INVENTORY_INSTRUCTIONS,"evidence_patch":EVIDENCE_PATCH_INSTRUCTIONS})
