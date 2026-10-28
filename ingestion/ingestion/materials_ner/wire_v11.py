"""Keyed inventory dispositions; project bookkeeping, never scientific claims.

The model chooses each disposition and every scientific field. Deterministic
code allocates additional-item IDs, inverts the chosen links and derives an
operational completion state. Held items remain held, including not_a_result.
"""
from copy import deepcopy
import json
from typing import Literal

from pydantic import Field, create_model

from .contract import StrictModel, canonical, digest
from .evidence import source_catalog
from .inventory import Inventory, InventoryItem, source_text, strict_schema, targets
from .wire_v10 import (DetectionExtraction, DetectionObservation,
    output_schema as previous_schema, validate_coverage, inventory_render,
    inventory_render_repair, SCIENTIFIC_V6, REGISTRY_INSTRUCTIONS, SEMANTICS,
    CONDITIONAL_INSTRUCTIONS, INSTRUCTIONS as PREVIOUS_INSTRUCTIONS,
    INVENTORY_COMPLETENESS, PROMPT_HASH as PREVIOUS_PROMPT_HASH)

WIRE_VERSION = "materials-ner-shared/7"
PROMPT_VERSION = "materials-ner-prompt/11.0.1"
PROJECTION_VERSION = "materials-result-accounting/1"


class EmittedItem(StrictModel):
    kind: Literal["emitted"]
    result_id: str = Field(min_length=1)


class HeldItem(StrictModel):
    kind: Literal["held"]
    reason: Literal["not_a_result", "insufficient_context", "unresolved"]
    explanation: str = Field(min_length=1)


def copied_fields(model, excluded):
    return {name: (field.annotation, deepcopy(field))
            for name, field in model.model_fields.items() if name not in excluded}


AccountedObservation = create_model("AccountedObservation", __base__=StrictModel,
    **copied_fields(DetectionObservation, {"inventory_item_ids"}))
AdditionalSourceItem = create_model("AdditionalSourceItem", __base__=StrictModel,
    **copied_fields(InventoryItem, {"id"}), disposition=(EmittedItem | HeldItem, ...))
AccountedBase = create_model("AccountedBase", __base__=StrictModel,
    **copied_fields(DetectionExtraction, {"schema_version", "completion", "observations",
                                        "additional_items", "unextracted_items"}))


class AccountingError(ValueError):
    """A fixed diagnostic, with no source prose or arbitrary model text."""


def scientific_graph(data):
    selected = deepcopy({key: data[key] for key in (
        "work_id", "processed_block_ids", "unread_block_ids", "limitations",
        "samples", "states", "protocols", "sample_relations", "condition_supports",
        "observations", "context_dispositions")})
    for observation in selected["observations"]:
        observation.pop("inventory_item_ids", None)
    return selected


class AccountedExtraction(AccountedBase):
    schema_version: Literal["materials-ner-shared/7"]
    inventory_dispositions: dict[str, EmittedItem | HeldItem]
    observations: list[AccountedObservation]
    additional_items: list[AdditionalSourceItem]
    no_result_reason: str | None = Field(min_length=1)

    @classmethod
    def parse_response(cls, raw):
        # JSON objects must not silently discard duplicate keys before closure.
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise AccountingError("accounting_duplicate_json_key")
                result[key] = value
            return result
        try:
            parsed = json.loads(raw, object_pairs_hook=unique)
        except json.JSONDecodeError as error:
            raise AccountingError("accounting_invalid_json") from error
        return cls.model_validate(parsed)

    def project(self, inventory, bundle, *, projected_model=DetectionExtraction,
                projected_version="materials-ner-shared/6", projection_version=PROJECTION_VERSION,
                coverage_validator=validate_coverage):
        if self.work_id != inventory.work_id or self.work_id != bundle.work_id:
            raise AccountingError("accounting_work_binding_mismatch")
        ids = [item.id for item in inventory.items]
        if len(ids) != len(set(ids)) or set(ids) != set(self.inventory_dispositions):
            raise AccountingError("accounting_inventory_keys_not_closed")
        if self.observations and self.no_result_reason is not None:
            raise AccountingError("accounting_reason_with_observations")
        mapping = {observation.id: [] for observation in self.observations}
        if len(mapping) != len(self.observations):
            raise AccountingError("accounting_duplicate_result_id")
        held, additional, assignments = [], [], []

        def apply(identifier, disposition):
            if disposition.kind == "emitted":
                if disposition.result_id not in mapping:
                    raise AccountingError("accounting_result_reference_missing")
                mapping[disposition.result_id].append(identifier)
            else:
                held.append(dict(item_id=identifier, reason=disposition.reason,
                                 explanation=disposition.explanation))

        for identifier in ids:
            apply(identifier, self.inventory_dispositions[identifier])
        used = set(ids)
        for index, item in enumerate(self.additional_items):
            identifier = f"additional:{index+1}"
            while identifier in used:
                identifier = "additional:" + identifier
            used.add(identifier)
            additional.append(dict(id=identifier, **item.model_dump(exclude={"disposition"})))
            assignments.append(dict(index=index, id=identifier))
            apply(identifier, item.disposition)
        if any(not links for links in mapping.values()):
            raise AccountingError("accounting_result_without_source_item")
        data = self.model_dump(exclude={"inventory_dispositions", "no_result_reason"})
        data.update(schema_version=projected_version, additional_items=additional,
            unextracted_items=held, completion={"outcome": "incomplete", "empty_reason": None})
        for observation in data["observations"]:
            observation["inventory_item_ids"] = mapping[observation["id"]]
        projected = projected_model.model_validate(data)
        coverage = coverage_validator(projected, inventory, bundle)
        aliases = projected.processed_block_ids + projected.unread_block_ids
        all_blocks = set(source_catalog(bundle)["blocks"])
        reasons = []
        if held: reasons.append("held_source_items")
        if projected.unread_block_ids or inventory.unread_block_ids: reasons.append("unread_source_blocks")
        if len(aliases) != len(set(aliases)) or set(aliases) != all_blocks:
            reasons.append("source_block_accounting_not_closed")
        if not coverage["valid"]: reasons.append("inventory_or_context_validation_failed")
        if reasons:
            completion = {"outcome": "incomplete", "empty_reason": None}
        elif projected.observations:
            completion = {"outcome": "results", "empty_reason": None}
        elif not self.no_result_reason or not self.no_result_reason.strip():
            raise AccountingError("accounting_empty_reason_missing")
        else:
            completion = {"outcome": "empty", "empty_reason": self.no_result_reason}
        data["completion"] = completion
        projected = projected_model.model_validate(data)
        if scientific_graph(self.model_dump()) != scientific_graph(projected.model_dump()):
            raise AccountingError("accounting_changed_scientific_graph")
        proof = {"schema": projection_version, "transport_sha256": digest(self.model_dump()),
            "inventory_sha256": digest(inventory.model_dump()), "bundle_sha256": digest(bundle.model_dump()),
            "projected_wire_sha256": digest(projected.model_dump()),
            "scientific_graph_sha256": digest(scientific_graph(self.model_dump())),
            "additional_id_assignments": assignments, "completion": completion,
            "incomplete_reasons": reasons, "no_result_reason": self.no_result_reason,
            "scientific_assertions_unchanged": True, "scientific_acceptance": False}
        return projected, proof


def output_schema(bundle=None, inventory=None, *, model=AccountedExtraction):
    schema = strict_schema(model)
    previous = previous_schema(bundle, inventory)
    # Reuse the scientific generation restrictions verbatim. No new physical
    # fields or relaxed numeric branches are introduced by this transport.
    for name in ("Quantity", "ObservationResult", "ConditionalExistenceV4"):
        schema["$defs"][name] = deepcopy(previous["$defs"][name])
    for name in ("work_id", "processed_block_ids", "unread_block_ids", "context_dispositions"):
        schema["properties"][name] = deepcopy(previous["properties"][name])
    for name in ("EvidenceReference", "CarriedRelationContext", "ExcludedRelationContext"):
        schema["$defs"][name] = deepcopy(previous["$defs"][name])
    ids = [item.id for item in inventory.items] if inventory is not None else []
    if len(ids) != len(set(ids)):
        raise AccountingError("accounting_inventory_keys_not_closed")
    disposition = {"anyOf": [{"$ref": "#/$defs/EmittedItem"}, {"$ref": "#/$defs/HeldItem"}]}
    schema["properties"]["inventory_dispositions"] = {"type": "object", "additionalProperties": False,
        "properties": {identifier: deepcopy(disposition) for identifier in ids}, "required": ids}
    if bundle is not None:
        catalog = source_catalog(bundle)
        for key in ("source_span_ids", "context_span_ids"):
            schema["$defs"]["AdditionalSourceItem"]["properties"][key]["items"]["enum"] = (
                sorted(targets(catalog)) if key == "source_span_ids" else list(catalog["spans"]))
    return schema


ACCOUNTING_INSTRUCTIONS = """KEYED RESULT ACCOUNTING V11:
inventory_dispositions has exactly the supplied inventory item IDs as keys.
For each, choose emitted with the actual observation result_id, or held with
not_a_result, insufficient_context or unresolved and a specific explanation.
The model makes these scientific disposition choices; they remain reviewable.
Several items can refer to one observation ONLY for repeated mentions of that
same sample/state/protocol/result. Do not attach unrelated items to close a list.
Each observation must have at least one emitted source item. Observation objects
do not contain reverse inventory links. Code constructs those from your choices.

Registry membership is NOT a result-admission rule. A source-reported relevant
physical quantity absent from the registry must be emitted as unmapped with its
literal name, full numeric shape, unit and evidence. Do not hold it as
not_a_result merely because its name, dimension or unit is unregistered. This
includes fitted physical parameters and explicitly reported geometric results.
A named effective decay parameter is not automatically a bulk coherence length;
Josephson penetration depth is not automatically London penetration depth.
Preserve the exact physical meaning as unmapped when the registry lacks it.
Use held for a real source/scope/representation obstacle and explain that
obstacle. Registration alone is not such an obstacle. Retain source-supported
fit quantities with model_derived origin rather than calling them observed.

Before returning, check every context binding against the FINAL declared graph.
Its entity_id must exist in the matching entity array. Never reference an
observation that you held or did not emit. An unresolved context has no bindings
and an explanation; do not invent an ID to make it look carried. A result's
criterion binds entity=definition, entity_id=the observation ID, field=/criterion
(or /criterion_raw or /parameters/N); it is not a nested field on entity=result.
Every carried field must actually contain the asserted fact and its own evidence.
Keep a single-device geometry separate from a statement about a series; shared
method does not establish shared sample or condition ownership.

additional_items retains genuine TARGET assertions missed by the first read.
Each has sample_raw, quantity_name_raw, value_raw, source_span_ids,
context_span_ids and its own emitted/held disposition. Do not supply an item ID;
code allocates one without collisions. Do not add a second copy merely to hold
an existing inventory item; use its keyed disposition. Do not discard a genuine
additional result to make the list agree with the first read.

Report inspected/unread blocks faithfully and retain limitations. Completion is
derived from the actual graph and source accounting, not selected by the model.
Set no_result_reason to null when observations exist. If there are no results,
explain the source-specific reason; held items remain incomplete and under
review even if their reason is not_a_result. Empty output is never evidence of
absence of superconductivity. Do not emit a measured non-detection for a purely
theoretical statement about a model phase lacking superconductivity.

For every reported numeric quantity, including unmapped, copy its numeric shape:
an approximate point is exact with approximate=true, never an invented interval.
A central value with +/- uncertainty stays exact with an uncertainty object,
not an interval made from the central value plus/minus its error. Only printed
range endpoints form an interval. Source words may establish approximation when
the contiguous numeric raw is a bare number. Preserve signed values and units.
"""

# Remove obsolete operational instructions while retaining the scientific rules.
SCIENTIFIC = SCIENTIFIC_V6.replace(
    "If any block was not inspected, use outcome=incomplete. Empty results require a\n"
    "specific reason; a provider error or missing full text is never an empty result.",
    "Report uninspected blocks as unread. Explain any empty output; a provider error\n"
    "or missing full text is never a successful empty result.").replace(
    "Return outcome=results only if results contains at least one actual result.\n"
    "If you cannot finish, return outcome=incomplete and retain the completed objects\n"
    "with a concrete limitation.",
    "If you cannot finish, retain the completed objects, unread blocks and a concrete limitation.")
SEMANTIC_RULES = SEMANTICS.replace(
    "in an\nobservation or an explicit unextracted entry.",
    "through its\nkeyed emitted or held disposition.")
INSTRUCTIONS = PREVIOUS_INSTRUCTIONS.replace("materials-ner-shared/6", WIRE_VERSION) + "\n" + ACCOUNTING_INSTRUCTIONS
PROMPT_HASH = digest({"version": PROMPT_VERSION, "previous_prompt": PREVIOUS_PROMPT_HASH,
    "scientific": SCIENTIFIC, "semantics": SEMANTIC_RULES, "instructions": INSTRUCTIONS})


def render(bundle, inventory):
    return "\n".join([SCIENTIFIC, REGISTRY_INSTRUCTIONS, SEMANTIC_RULES, CONDITIONAL_INSTRUCTIONS,
        INSTRUCTIONS, INVENTORY_COMPLETENESS, "FIRST_READ_INVENTORY (fallible model proposals):",
        canonical(inventory.model_dump()), source_text(bundle), "END_SOURCE. Return the complete accounted graph."])


def verify_extraction(receipt, bundle, raw_output, *, model=AccountedExtraction):
    if "extraction" not in receipt:
        return
    if receipt.get("evidence_patch"):
        raise ValueError("accounted_graph_evidence_patch_not_supported")
    inventory = Inventory.model_validate(receipt["inventory"])
    projected, proof = model.parse_response(raw_output).project(inventory, bundle)
    if proof != receipt.get("inventory_accounting_projection"):
        raise ValueError("inventory_accounting_proof_mismatch")
    if projected.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("accounted_extraction_reconstruction_mismatch")
