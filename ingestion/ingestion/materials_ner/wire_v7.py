"""Native result definitions; no synthetic per-result procedure variants."""
from collections import Counter
import re
from typing import Literal

from pydantic import model_validator

from .contract import canonical, digest
from .contract_v5 import ExtractionV5, ProcedureV5
from .evidence import source_catalog, selected_quotes, equivalent_location_spans
from .inventory import source_text
from .wire import nested_model
from .wire_v2 import output_schema as common_schema, validate_coverage as result_coverage
from .wire_v3 import field_value
from .wire_v4 import output_schema as v4_schema
from .wire_v5 import SharedExtraction
from .wire_v6 import (DefinedObservation, CarriedDefinitionContext, ExcludedDefinitionContext,
    DefinedExtraction, SCIENTIFIC_V6, REGISTRY_INSTRUCTIONS, SEMANTICS_V6,
    CONDITIONAL_INSTRUCTIONS, INSTRUCTIONS as V6_INSTRUCTIONS, INVENTORY_COMPLETENESS,
    inventory_render, inventory_render_repair)

WIRE_VERSION = "materials-ner-shared/3"
PROMPT_VERSION = "materials-ner-prompt/7.0.0"
NativeProcedure = nested_model("NativeProcedure", ProcedureV5, set())


class NativeExtraction(SharedExtraction):
    schema_version: Literal["materials-ner-shared/3"]
    protocols: list[NativeProcedure]
    observations: list[DefinedObservation]
    context_dispositions: list[CarriedDefinitionContext | ExcludedDefinitionContext]

    @model_validator(mode="after")
    def references(self):
        maps = self.entity_maps()
        for name, rows in (("sample", self.samples), ("state", self.states),
                           ("protocol", self.protocols), ("result", self.observations)):
            if len(maps[name]) != len(rows) or any(not row.id.strip() for row in rows):
                raise ValueError("duplicate_or_empty_native_" + name + "_id")
        for state in self.states:
            if state.sample_id not in maps["sample"]:
                raise ValueError("native_state_sample_reference_invalid")
        for observation in self.observations:
            if observation.state_id not in maps["state"] or observation.protocol_id not in maps["protocol"]:
                raise ValueError("native_observation_reference_invalid")
            if observation.sample_id != maps["state"][observation.state_id].sample_id:
                raise ValueError("native_observation_state_sample_mismatch")
        for disposition in self.context_dispositions:
            for binding in disposition.bindings:
                if binding.entity_id not in maps[binding.entity]:
                    raise ValueError("native_context_target_invalid")
        # Retain an unassigned procedure. Validation flags its scope for review;
        # it is neither dropped nor assigned a fabricated result/criterion.
        return self

    def entity_maps(self):
        maps = super().entity_maps()
        maps["definition"] = {o.id: o.definition for o in self.observations}
        return maps

    scientific_payload = DefinedExtraction.scientific_payload

    def expand(self, bundle):
        catalog = source_catalog(bundle)
        if self.work_id != bundle.work_id: raise ValueError("work_binding_mismatch")
        def evidence(entity, prefix=""):
            return [{"block_id": q["block_id"], "quote": q["quote"], "field": prefix + field}
                for ref in entity.evidence for q in selected_quotes(catalog, ref.span_ids) for field in ref.fields]
        data = {"schema_version": "materials-ner/5", "work_id": self.work_id,
                **self.completion.model_dump(), "limitations": self.limitations}
        for name in ("processed_block_ids", "unread_block_ids"):
            data[name] = [catalog["blocks"][alias]["block_id"] for alias in getattr(self, name)]
        for name in ("samples", "states", "protocols"):
            data[name] = [dict(entity.model_dump(exclude={"evidence"}), evidence=evidence(entity))
                          for entity in getattr(self, name)]
        data["results"] = []
        for observation in self.observations:
            result = observation.result.model_dump(exclude={"evidence"})
            result.update(id=observation.id, sample_id=observation.sample_id, state_id=observation.state_id,
                protocol_id=observation.protocol_id, definition=observation.definition.model_dump(exclude={"evidence"}),
                evidence=evidence(observation.result) + evidence(observation.definition, "/definition"))
            data["results"].append(result)
        return ExtractionV5.model_validate(data)

    def validation_entity_ids(self):
        return {"samples": [s.id for s in self.samples], "states": [s.id for s in self.states],
                "protocols": [p.id for p in self.protocols], "results": [o.id for o in self.observations]}


def validate_coverage(compact, inventory, bundle):
    report = result_coverage(compact, inventory, bundle)
    issues = report["issues"]
    maps = compact.entity_maps()
    indexes = {kind: {identifier: index for index, identifier in enumerate(mapping)}
               for kind, mapping in maps.items()}
    contexts = {c.id: c for c in inventory.context_assertions}
    if Counter(d.context_id for d in compact.context_dispositions) != Counter(contexts.keys()):
        issues.append({"code": "context_disposition_not_closed", "path": "/"})
    catalog = source_catalog(bundle)
    compact_text = lambda value: re.sub(r"\s+", "", value or "")
    labels = {compact_text(s.label) for s in compact.samples if s.label}
    simple_formula = re.compile(r"(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?){2,}")
    items = {i.id: i for i in inventory.items + compact.additional_items}
    disagreements = []
    for obs in compact.observations:
        sample = maps["sample"][obs.sample_id]
        formula, label = compact_text(sample.formula_raw), compact_text(sample.label)
        for identifier in obs.inventory_item_ids:
            item = items.get(identifier)
            if item is None: continue
            subject = compact_text(item.sample_raw)
            if subject in {formula, label}: continue
            field = "/label" if subject in labels else (
                "/formula_raw" if simple_formula.fullmatch(subject) and simple_formula.fullmatch(formula) else None)
            if field:
                issues.append({"code": "inventory_subject_disagreement",
                               "path": f"/samples/{indexes['sample'][sample.id]}{field}"})
                disagreements.append({"observation_id": obs.id, "inventory_item_id": identifier,
                    "inventory_subject": item.sample_raw, "proposed_label": sample.label,
                    "proposed_formula": sample.formula_raw, "source_review_required": True})
    exclusions = []
    for disposition in compact.context_dispositions:
        context = contexts.get(disposition.context_id)
        if disposition.resolution != "carried":
            exclusions.append(disposition.model_dump())
            if disposition.resolution == "unresolved":
                issues.append({"code": "source_context_unresolved", "path": "/"})
            continue
        for binding in disposition.bindings:
            if context is None:
                issues.append({"code": "context_binding_target_invalid", "path": "/"}); continue
            entity = maps[binding.entity][binding.entity_id]
            if binding.entity == "result": entity = entity.result
            path = (f"/results/{indexes['result'][binding.entity_id]}/definition{binding.field}"
                if binding.entity == "definition" else
                f"/{binding.entity}s/{indexes[binding.entity][binding.entity_id]}{binding.field}")
            try: value = field_value(entity.model_dump(), binding.field)
            except (ValueError, KeyError, IndexError, TypeError): value = None
            if value is None or value == [] or value == {} or value == "":
                issues.append({"code": "context_binding_field_empty", "path": path})
            spans = {s for ref in entity.evidence if binding.field in ref.fields for s in ref.span_ids}
            if not equivalent_location_spans(catalog, spans).intersection(context.span_ids):
                issues.append({"code": "context_field_evidence_disconnected", "path": path})
    issues[:] = [dict(item) for item in { (i["code"], i["path"]): i for i in issues }.values()]
    report.update(schema="materials-inventory-closure/3", valid=not issues,
        context_assertions=len(contexts), context_dispositions=[d.model_dump() for d in compact.context_dispositions],
        context_exclusions=exclusions, context_exclusions_independently_reviewed=False,
        subject_disagreements=disagreements,
        shared_entity_counts={"samples": len(compact.samples), "states": len(compact.states), "procedures": len(compact.protocols)},
        explicit_result_definitions=len(compact.observations),
        context_binding_scope="native_shared_procedures_and_result_owned_definitions")
    return report


def output_schema(bundle=None, inventory=None):
    schema = common_schema(bundle, model=NativeExtraction,
        negative_def="NonDetectionV4", conditional_def="ConditionalExistenceV4")
    schema["$defs"]["ConditionalExistenceV4"] = v4_schema()["$defs"]["ConditionalExistenceV4"]
    if inventory is not None:
        ids = [c.id for c in inventory.context_assertions]
        schema["properties"]["context_dispositions"].update(minItems=len(ids), maxItems=len(ids))
        if ids:
            for name in ("CarriedDefinitionContext", "ExcludedDefinitionContext"):
                schema["$defs"][name]["properties"]["context_id"]["enum"] = ids
    return schema


INSTRUCTIONS = V6_INSTRUCTIONS.replace("materials-ner-shared/2", WIRE_VERSION).replace(
    "All declared entities must be referenced. Preserve unresolved context honestly.",
    "Retain declarations with unresolved applicability for review; do not invent a result to reference them.") + """

NATIVE PROCEDURE AND CONDITION OWNERSHIP:
Definitions are stored directly on results. Procedures have no criterion; do
not attach criterion/threshold evidence to a shared procedure. Each definition's
parameters need their own /parameters/N evidence, including the threshold and
reference. A procedure's parameters=[] means /parameters/0 does not exist.
Invalid pointers remain invalid; the program never transfers their evidence to
another field. Every known definition criterion needs /criterion evidence.

An auxiliary procedure can support a sample condition (for example a structural
measurement of specimen geometry). Its context_uses names the actual state_id
and condition_index, with /context_uses/N source evidence for that association.
Keep its method evidence separately. Reference only conditions already present
in that state. Do not attach the method to all films or conditions by analogy.
Use context_uses=[] when there is no explicitly supported condition association.
An unreferenced procedure is retained but requires scope review. Do not invent
a target result, criterion, measurement or applicability to avoid that review.
Do not confuse these method-use links with context_dispositions: the latter
account for source inventory assertions, not physical measurement identity.

A source merely saying 'transitions around' a temperature supplies no onset
definition by itself. Preserve unspecified unless the actual passage supplies
a criterion for that result. A later, separately defined onset does not silently
redefine the earlier approximate assertion.
"""


def render(bundle, inventory):
    return "\n".join([SCIENTIFIC_V6, REGISTRY_INSTRUCTIONS, SEMANTICS_V6,
        CONDITIONAL_INSTRUCTIONS, INSTRUCTIONS,
        "FIRST_READ_INVENTORY (fallible proposals, not source truth): " + canonical(inventory.model_dump()),
        source_text(bundle), "Return native shared procedures and individually defined results."])


PROMPT_HASH = digest({"version": PROMPT_VERSION, "scientific": SCIENTIFIC_V6,
    "registry": REGISTRY_INSTRUCTIONS, "semantics": SEMANTICS_V6,
    "conditional": CONDITIONAL_INSTRUCTIONS, "wire": INSTRUCTIONS,
    "inventory_accounting": INVENTORY_COMPLETENESS})
