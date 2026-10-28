"""Typed entity edits: untouched declarations are retained by construction."""
from copy import deepcopy
from typing import Literal, Union, get_args

from pydantic import Field, create_model

from .contract import StrictModel, canonical, digest
from .evidence import source_catalog
from .native_revision import NativeRevision, RevisionNote, GROUPS, VERSION as REVISION_VERSION
from .sources import sha
from .wire_v7 import NativeExtraction, output_schema as native_schema, render as native_render, PROMPT_HASH as NATIVE_PROMPT_HASH

VERSION = "materials-native-edits/1"
PROMPT_VERSION = "materials-native-edit-prompt/1.0.0"


class EditBase(StrictModel):
    action: Literal["add", "replace"]
    reason: str = Field(min_length=1)
    span_ids: list[str] = Field(min_length=1)


KINDS = ("sample", "state", "procedure", "result", "context", "additional_item")
EDIT_MODELS = []
for _kind in KINDS:
    _name, _id = GROUPS[_kind]
    _type = get_args(NativeExtraction.model_fields[_name].annotation)[0]
    EDIT_MODELS.append(create_model("Edit"+_kind.title().replace("_", ""), __base__=EditBase,
        entity=(Literal[_kind], ...), value=(_type, ...)))


class ResolveExcludedItem(StrictModel):
    item_id: str = Field(min_length=1)
    observation_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    span_ids: list[str] = Field(min_length=1)


class NativeEdits(StrictModel):
    schema_version: Literal["materials-native-edits/1"]
    work_id: str
    base_raw_output_sha256: str
    edits: list[Union[tuple(EDIT_MODELS)]] = Field(min_length=1)
    resolved_unextracted_items: list[ResolveExcludedItem]


INSTRUCTIONS = """Repair this failed native extraction with typed entity edits only.
The program starts from an exact copy of BASE_GRAPH and retains every untouched
entity. Do not return a rewritten graph. Return only add or replace operations
for entities requiring a source-backed change. No entity can be deleted or
renamed: replace must retain its existing ID, add must use a new ID.

Read the original source, not the model's assumptions. Add a missing result only
if it is reported by the source. Fitted superconducting-layer thickness is a
registered result, distinct from actual specimen thickness. Preserve conditional
statements and literal formula disagreements. Formula labels alone do not prove
nominal/measured composition. Keep every old result unless an explicit replacement
corrects its fields, with source spans and a reason. Evidence pointer strings
are relative to their own result/definition/procedure; source raw fields are
literal excerpts, not an explanatory paraphrase. Use details/reason for prose.

When an excluded inventory item is now represented as a result, list its item_id
and actual observation_ids in resolved_unextracted_items; the program verifies
those observations explicitly contain that inventory ID before removing the
exclusion. A context binding to an absent result is not evidence that the result
exists. If the source reports it, add the result and resolve its exclusion.
Recheck unresolved context dispositions and bind them to actual entity fields
with their own evidence. Each changed/added entity needs an English reason and
source span IDs. All replacements must include the full one entity, not the full
graph. The program retains processed scope and completion as originally recorded.
Do not grant scientific acceptance or pretend that this model revision is human
review. Read the complete source window before choosing any edit.
"""
PROMPT_HASH = digest({"version": PROMPT_VERSION, "instructions": INSTRUCTIONS, "native": NATIVE_PROMPT_HASH})


def output_schema(bundle=None, inventory=None, parent=None):
    schema = NativeEdits.model_json_schema()
    native = native_schema(bundle, inventory)
    schema["$defs"].update(native["$defs"])
    if bundle is not None:
        schema["properties"]["work_id"]["enum"] = [bundle.work_id]
        spans = list(source_catalog(bundle)["spans"])
        for definition in schema["$defs"].values():
            if "span_ids" in definition.get("properties", {}):
                definition["properties"]["span_ids"]["items"]["enum"] = spans
    if parent is not None:
        schema["properties"]["base_raw_output_sha256"]["enum"] = [sha(parent["raw_output"].encode())]
    return schema


def apply_edits(base_raw, edits):
    import json
    original = json.loads(base_raw)
    if sha(base_raw.encode()) != edits.base_raw_output_sha256 or original["work_id"] != edits.work_id:
        raise ValueError("edit_parent_or_work_mismatch")
    data = deepcopy(original); changed = set(); notes = []
    for edit in edits.edits:
        name, key = GROUPS[edit.entity]; value = edit.value.model_dump(); identifier = value[key]
        target = (edit.entity, identifier)
        if target in changed: raise ValueError("duplicate_entity_edit")
        changed.add(target)
        indexes = [i for i, row in enumerate(data[name]) if row[key] == identifier]
        if edit.action == "replace":
            if len(indexes) != 1: raise ValueError("edit_replace_target_missing_or_ambiguous")
            if data[name][indexes[0]] == value: raise ValueError("edit_does_not_change_entity")
            data[name][indexes[0]] = value
        else:
            if indexes: raise ValueError("edit_add_target_already_exists")
            data[name].append(value)
        notes.append(RevisionNote(entity=edit.entity, entity_id=identifier, reason=edit.reason, span_ids=edit.span_ids))
    resolved = set()
    for resolution in edits.resolved_unextracted_items:
        if resolution.item_id in resolved: raise ValueError("duplicate_exclusion_resolution")
        resolved.add(resolution.item_id)
        indexes = [i for i, row in enumerate(data["unextracted_items"]) if row["item_id"] == resolution.item_id]
        if len(indexes) != 1: raise ValueError("resolved_exclusion_not_present")
        observations = {o["id"]: o for o in data["observations"]}
        if (len(set(resolution.observation_ids)) != len(resolution.observation_ids)
                or any(identifier not in observations or resolution.item_id not in observations[identifier]["inventory_item_ids"]
                       for identifier in resolution.observation_ids)):
            raise ValueError("resolved_exclusion_has_no_explicit_result")
        data["unextracted_items"].pop(indexes[0])
        notes.append(RevisionNote(entity="unextracted_item", entity_id=resolution.item_id,
                                  reason=resolution.reason, span_ids=resolution.span_ids))
    # Strict expansion still rejects any unresolved FK. No target is inferred.
    revision = NativeRevision(schema_version=REVISION_VERSION, work_id=edits.work_id,
        base_raw_output_sha256=edits.base_raw_output_sha256, revised_graph=NativeExtraction.model_validate(data), notes=notes)
    return revision


def render(bundle, inventory, parent):
    from .native_revision import graph_diagnostics
    import json
    return "\n".join([native_render(bundle, inventory), INSTRUCTIONS,
        "BASE_RAW_OUTPUT_SHA256: " + sha(parent["raw_output"].encode()),
        "BASE_GRAPH (read only): " + parent["raw_output"],
        "GRAPH_DIAGNOSTICS: " + canonical(graph_diagnostics(json.loads(parent["raw_output"]))),
        "Return materials-native-edits/1. Untouched declarations are automatically retained."])


def verify_receipt(receipt, bundle, raw_output):
    from .native_revision import audit_revision, verify_parent
    parent = receipt["revision_parent"]; inventory = verify_parent(parent, bundle)
    if receipt["config"]["parent_run_id"] != parent["run_id"] or receipt.get("inventory") != inventory.model_dump():
        raise ValueError("revision_parent_inventory_mismatch")
    if "extraction" not in receipt: return
    edits = NativeEdits.model_validate_json(raw_output)
    revision = apply_edits(parent["raw_output"], edits)
    if audit_revision(parent["raw_output"], revision, bundle) != receipt.get("revision_audit"):
        raise ValueError("revision_audit_reconstruction_mismatch")
    if revision.revised_graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("revision_extraction_reconstruction_mismatch")
    required = {(i["code"], i["path"]) for i in receipt["revision_audit"]["issues"]}
    actual = {(i["code"], i["path"]) for i in receipt["validation"]["issues"]}
    if not required <= actual: raise ValueError("revision_audit_issues_omitted")
