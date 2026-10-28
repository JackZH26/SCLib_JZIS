"""Scoped ranges align NER with existing canonical condition-role semantics."""
from typing import Literal

from .contract import canonical, digest
from .contract_v7 import ExtractionV7, StateV7
from .evidence import source_catalog, selected_quotes
from .inventory import source_text, REPAIR_INSTRUCTIONS
from .wire import nested_model
from .wire_v2 import output_schema as common_schema
from .wire_v4 import output_schema as conditional_schema
from .wire_v8 import (RelationalExtraction, validate_coverage, BASE_INVENTORY,
    SCIENTIFIC_V6, REGISTRY_INSTRUCTIONS, SEMANTICS, CONDITIONAL_INSTRUCTIONS,
    INVENTORY_COMPLETENESS, INVENTORY_RULES, INSTRUCTIONS as V8_INSTRUCTIONS,
    PROMPT_HASH as V8_PROMPT_HASH)

WIRE_VERSION = "materials-ner-shared/5"
PROMPT_VERSION = "materials-ner-prompt/9.0.0"
ScopedState = nested_model("ScopedState", StateV7, set())


class ScopedExtraction(RelationalExtraction):
    schema_version: Literal["materials-ner-shared/5"]
    states: list[ScopedState]

    def expand(self, bundle):
        catalog = source_catalog(bundle)
        if self.work_id != bundle.work_id: raise ValueError("work_binding_mismatch")
        def evidence(entity, prefix=""):
            return [{"block_id": q["block_id"], "quote": q["quote"], "field": prefix + field}
                for ref in entity.evidence for q in selected_quotes(catalog, ref.span_ids) for field in ref.fields]
        data = {"schema_version": "materials-ner/7", "work_id": self.work_id,
                **self.completion.model_dump(), "limitations": self.limitations}
        for name in ("processed_block_ids", "unread_block_ids"):
            data[name] = [catalog["blocks"][alias]["block_id"] for alias in getattr(self, name)]
        for name in ("samples", "states", "protocols", "sample_relations", "condition_supports"):
            data[name] = [dict(entity.model_dump(exclude={"evidence"}), evidence=evidence(entity))
                          for entity in getattr(self, name)]
        data["results"] = []
        for observation in self.observations:
            result = observation.result.model_dump(exclude={"evidence"})
            result.update(id=observation.id, sample_id=observation.sample_id, state_id=observation.state_id,
                protocol_id=observation.protocol_id, definition=observation.definition.model_dump(exclude={"evidence"}),
                evidence=evidence(observation.result) + evidence(observation.definition, "/definition"))
            data["results"].append(result)
        return ExtractionV7.model_validate(data)


def output_schema(bundle=None, inventory=None):
    schema = common_schema(bundle, model=ScopedExtraction, negative_def="NonDetectionV4", conditional_def="ConditionalExistenceV4")
    schema["$defs"]["ConditionalExistenceV4"] = conditional_schema()["$defs"]["ConditionalExistenceV4"]
    if inventory is not None:
        ids = [c.id for c in inventory.context_assertions]
        schema["properties"]["context_dispositions"].update(minItems=len(ids), maxItems=len(ids))
        if ids:
            for definition in schema["$defs"].values():
                if "context_id" in definition.get("properties", {}):
                    definition["properties"]["context_id"]["enum"] = ids
    return schema


ROLE_INSTRUCTIONS = """SOURCE EXTENTS V9:
The condition roles now include study_extent and fit_window. They do not change
the meaning of measurement, synthesis, simulation or detection_window.
study_extent records a source-scoped phase interval, sweep extent or aggregate
study domain. It is not the exact condition of every result in that domain. A
reported phase-pressure range must not be assigned to a single Tc as if that Tc
were measured throughout the range. Retain the range with its phase/state scope;
the actual result-specific measurement pressure can remain unknown.
fit_window records an explicitly numeric domain used in a fit. It never supplies
an observed detection limit, measurement temperature or a Tc bound. When a bound
is symbolic, retain the complete source description in applicable procedure
details and unresolved context; do not substitute the result's Tc into the bound.
window_position stays null for these two roles. It is reserved for a reported
detection_window condition. Never add missing endpoints or choose a midpoint.
Bind every retained condition and its raw basis to the actual original span.

An explicit statement that a transition was not observed down to a temperature
must retain that temperature as the associated state's detection lower limit,
not solely in a qualifier sentence. A conditional superconductivity claim is
different and cannot imply an unstated scan limit. Keep result names literal,
keep phase names on their states, and do not infer a primary/secondary transition
stage from a generic transition mention. Every *_raw field and method class needs
its own field evidence; inventory descriptions are not literal source quotations.
"""
INSTRUCTIONS = V8_INSTRUCTIONS.replace("materials-ner-shared/4", WIRE_VERSION) + "\n" + ROLE_INSTRUCTIONS
PROMPT_HASH = digest({"version": PROMPT_VERSION, "v8_prompt": V8_PROMPT_HASH,
                      "instructions": INSTRUCTIONS, "role_instructions": ROLE_INSTRUCTIONS})


def inventory_render(bundle):
    return "\n".join([BASE_INVENTORY, INVENTORY_COMPLETENESS, INVENTORY_RULES, ROLE_INSTRUCTIONS,
                      source_text(bundle), "Return the source inventory with all reported result items."])


def inventory_render_repair(bundle, inventory, validation):
    return "\n".join([inventory_render(bundle), REPAIR_INSTRUCTIONS,
        "PREVIOUS_INVENTORY: " + canonical(inventory.model_dump()),
        "DETERMINISTIC_DIAGNOSTICS: " + canonical(validation), "Return the corrected inventory JSON."])


def render(bundle, inventory):
    return "\n".join([SCIENTIFIC_V6, REGISTRY_INSTRUCTIONS, SEMANTICS, CONDITIONAL_INSTRUCTIONS,
        INSTRUCTIONS, INVENTORY_COMPLETENESS, "FIRST_READ_INVENTORY (fallible model proposals):",
        canonical(inventory.model_dump()), source_text(bundle), "END_SOURCE. Return the complete scoped relation graph."])
