"""Bounded typed revisions of native relation graphs, with immutable ancestry.

This is model-assisted correction, not an independent scientific read. A parent
must already have a reconstructable graph; failed structural responses remain
archived rather than being converted into invented source declarations.
"""
from copy import deepcopy
import json
from typing import Literal, Union, get_args

from pydantic import Field, create_model, model_validator

from .contract import StrictModel, canonical, digest
from .evidence import selected_quotes, source_catalog
from .inventory import Inventory
from .inventory_links import verify_inventory_projection
from .native_revision_edits import EditBase, ResolveExcludedItem
from .sources import sha
from .validation import validate_extraction
from .wire_v8 import RelationalExtraction, output_schema as graph_schema, render as graph_render, validate_coverage, PROMPT_HASH as GRAPH_PROMPT_HASH

VERSION = "materials-relational-edits/1"
PROMPT_VERSION = "materials-relational-edit-prompt/1.0.0"
MAX_REVISION_DEPTH = 8
GROUPS = {"sample": ("samples", "id"), "state": ("states", "id"),
    "procedure": ("protocols", "id"), "result": ("observations", "id"),
    "context": ("context_dispositions", "context_id"),
    "additional_item": ("additional_items", "id"),
    "unextracted_item": ("unextracted_items", "item_id"),
    "sample_relation": ("sample_relations", "id"), "condition_support": ("condition_supports", "id")}

EDIT_MODELS = []
for _kind, (_name, _id) in GROUPS.items():
    if _kind == "unextracted_item": continue
    _type = get_args(RelationalExtraction.model_fields[_name].annotation)[0]
    EDIT_MODELS.append(create_model("RelationEdit"+_kind.title().replace("_", ""), __base__=EditBase,
        entity=(Literal[_kind], ...), value=(_type, ...)))

DOCUMENT_FIELDS = ("processed_block_ids", "unread_block_ids", "completion", "limitations")
DocumentEdit = create_model("RelationDocumentEdit", __base__=StrictModel,
    **{k:(RelationalExtraction.model_fields[k].annotation, ...) for k in DOCUMENT_FIELDS},
    reason=(str, Field(min_length=1)), span_ids=(list[str], Field(min_length=1)))


class NativeEdits(StrictModel):
    schema_version: Literal["materials-relational-edits/1"]
    work_id: str
    parent_run_id: str = Field(pattern="^[a-f0-9]{64}$")
    base_graph_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    edits: list[Union[tuple(EDIT_MODELS)]]
    resolved_unextracted_items: list[ResolveExcludedItem]
    document_edit: DocumentEdit | None

    @model_validator(mode="after")
    def has_change(self):
        if not self.edits and not self.resolved_unextracted_items and self.document_edit is None:
            raise ValueError("empty_relation_revision")
        return self


class RevisionNote(StrictModel):
    entity: str
    entity_id: str
    reason: str
    span_ids: list[str]


class AppliedRevision(StrictModel):
    parent_run_id: str
    base_graph_sha256: str
    revised_graph: RelationalExtraction
    notes: list[RevisionNote]


def grouped(raw):
    out={}
    for kind,(name,key) in GROUPS.items():
        for row in raw[name]:
            identity=(kind,row[key])
            if identity in out or not row[key].strip(): raise ValueError("ambiguous_relation_revision_identity")
            out[identity]=row
    out["document",raw["work_id"]]={k:raw[k] for k in DOCUMENT_FIELDS}
    return out


def resolve_parent(parent, bundle, *, depth=0):
    if depth > MAX_REVISION_DEPTH: raise ValueError("relation_revision_ancestry_limit")
    receipt,raw=parent["receipt"],parent["raw_output"]
    if (digest(receipt)!=parent["run_id"] or not isinstance(raw,str)
            or receipt.get("raw_output_sha256")!=sha(raw.encode())):
        raise ValueError("relation_parent_receipt_hash_mismatch")
    if (receipt["work_id"]!=bundle.work_id or receipt["bundle_sha256"]!=digest(bundle.model_dump())
            or receipt["state"] not in {"succeeded","quarantined"} or "extraction" not in receipt):
        raise ValueError("relation_revision_requires_structured_terminal_parent")
    format_=receipt["config"].get("output_format")
    if format_=="materials-ner-shared/4":
        if receipt.get("evidence_patch"): raise ValueError("relation_parent_patch_not_supported")
        verify_inventory_projection(receipt,bundle)
        wire=RelationalExtraction.model_validate_json(raw)
        inventory=Inventory.model_validate(receipt["inventory"])
    elif format_==VERSION:
        wire,inventory=verify_receipt(receipt,bundle,raw,depth=depth+1)
    elif format_=="materials-relational-edits/2":
        from .relational_review import verify_receipt as verify_review
        wire,inventory=verify_review(receipt,bundle,raw,depth=depth+1)
    elif format_=="materials-source-field-edits/1":
        from .source_field_revision import verify_receipt as verify_fields
        wire,inventory=verify_fields(receipt,bundle,raw,depth=depth+1)
    elif format_=="materials-source-field-edits/2":
        from .source_field_local import verify_receipt as verify_fields_local
        wire,inventory=verify_fields_local(receipt,bundle,raw,depth=depth+1)
    else: raise ValueError("unsupported_relation_revision_parent")
    if wire.expand(bundle).model_dump()!=receipt["extraction"]:
        raise ValueError("relation_parent_graph_reconstruction_mismatch")
    return wire,inventory


def verify_parent(parent,bundle):
    return resolve_parent(parent,bundle)[1]


def apply_to_graph(original, parent_run_id, edits, *, graph_model=RelationalExtraction, applied_model=AppliedRevision):
    if (edits.parent_run_id!=parent_run_id or digest(original)!=edits.base_graph_sha256
            or original["work_id"]!=edits.work_id):
        raise ValueError("relation_edit_parent_or_graph_mismatch")
    data=deepcopy(original); changed=set(); notes=[]
    for edit in edits.edits:
        name,key=GROUPS[edit.entity];value=edit.value.model_dump();identifier=value[key];target=(edit.entity,identifier)
        if target in changed: raise ValueError("duplicate_relation_entity_edit")
        changed.add(target)
        indexes=[i for i,row in enumerate(data[name]) if row[key]==identifier]
        if edit.action=="replace":
            if len(indexes)!=1: raise ValueError("relation_replace_target_missing")
            if data[name][indexes[0]]==value: raise ValueError("relation_edit_does_not_change_entity")
            data[name][indexes[0]]=value
        else:
            if indexes: raise ValueError("relation_add_target_already_exists")
            data[name].append(value)
        notes.append(RevisionNote(entity=edit.entity,entity_id=identifier,reason=edit.reason,span_ids=edit.span_ids))
    resolved=set()
    for resolution in edits.resolved_unextracted_items:
        if resolution.item_id in resolved: raise ValueError("duplicate_relation_exclusion_resolution")
        resolved.add(resolution.item_id)
        indexes=[i for i,row in enumerate(data["unextracted_items"]) if row["item_id"]==resolution.item_id]
        observations={o["id"]:o for o in data["observations"]}
        if (len(indexes)!=1 or len(set(resolution.observation_ids))!=len(resolution.observation_ids)
                or any(identifier not in observations or resolution.item_id not in observations[identifier]["inventory_item_ids"]
                       for identifier in resolution.observation_ids)):
            raise ValueError("relation_exclusion_has_no_explicit_result")
        data["unextracted_items"].pop(indexes[0])
        notes.append(RevisionNote(entity="unextracted_item",entity_id=resolution.item_id,reason=resolution.reason,span_ids=resolution.span_ids))
    if edits.document_edit is not None:
        doc=edits.document_edit.model_dump()
        if all(original[k]==doc[k] for k in DOCUMENT_FIELDS): raise ValueError("relation_document_edit_has_no_change")
        data.update({k:doc[k] for k in DOCUMENT_FIELDS})
        notes.append(RevisionNote(entity="document",entity_id=edits.work_id,reason=doc["reason"],span_ids=doc["span_ids"]))
    return applied_model(parent_run_id=parent_run_id,base_graph_sha256=edits.base_graph_sha256,
        revised_graph=graph_model.model_validate(data),notes=notes)


def apply_edits(parent,bundle,edits):
    base,_=resolve_parent(parent,bundle)
    return apply_to_graph(base.model_dump(),parent["run_id"],edits)


def audit_graph(original,parent_run_id,revision,bundle):
    if (revision.parent_run_id!=parent_run_id or revision.base_graph_sha256!=digest(original)
            or revision.revised_graph.work_id!=bundle.work_id):
        raise ValueError("relation_revision_audit_parent_mismatch")
    after_raw=revision.revised_graph.model_dump(); before,after=grouped(original),grouped(after_raw)
    changed={k for k in before.keys()|after.keys() if before.get(k)!=after.get(k)}
    notes={(n.entity,n.entity_id):n for n in revision.notes};issues=[];changes=[]
    if len(notes)!=len(revision.notes) or set(notes)!=changed:
        issues.append({"code":"relation_revision_note_coverage_mismatch","path":"/"})
    catalog=source_catalog(bundle)
    for key in sorted(changed):
        old,new=before.get(key),after.get(key);note=notes.get(key);quotes=[]
        if new is None and key[0]!="unextracted_item":
            issues.append({"code":"relation_revision_declaration_removed","path":"/"})
        if note:
            try: quotes=selected_quotes(catalog,note.span_ids)
            except ValueError: issues.append({"code":"relation_revision_note_source_invalid","path":"/"})
        changes.append({"entity":key[0],"entity_id":key[1],"operation":"added" if old is None else "removed" if new is None else "revised",
            "before":old,"after":new,"before_sha256":digest(old),"after_sha256":digest(new),
            "reason":note.reason if note else None,"source_quotes":quotes})
    return {"schema":"materials-relational-revision-audit/1","parent_run_id":parent_run_id,
        "base_graph_sha256":digest(original),"revised_graph_sha256":digest(after_raw),"changes":changes,
        "issues":issues,"valid":not issues,"reviewer_kind":"model","independent_review":False,
        "scientific_acceptance":False,"ml_training_eligible":False}


def audit_revision(parent,revision,bundle):
    base,_=resolve_parent(parent,bundle)
    return audit_graph(base.model_dump(),parent["run_id"],revision,bundle)


INSTRUCTIONS = """Perform ONE source-backed local revision of BASE_GRAPH.
The graph and inventory are fallible proposals. Return typed add/replace edits
only; the program retains every untouched declaration byte-for-byte in its
canonical graph. Do not rewrite the graph or delete/rename any existing ID.
Do not invent results, conditions or relations to hide an unresolved context.
Each replacement contains the complete one entity, a reason and source spans.

Read all source spans. Recheck literal formula disagreements on the correct
subject, component membership, method attribution and all explicit property-to-
geometry relationships. A method stated for one sample cannot be assigned to
another because the assertions share a paragraph. An unreported method uses an
explicit unknown procedure (method=null, method_class=unspecified); it must not
borrow an existing instrument to satisfy a nonempty reference. Geometry results
and conditions must preserve their own exact/approximate meanings. Use a support
edge only when the source warrants the relationship and numeric semantics agree.
Where they do not agree, retain the unresolved relationship for review.

Every raw string must be a source-literal excerpt, not a paraphrase. Bind each
required field with the correct source spans and correct entity-relative pointer.
In context_dispositions, definition fields use entity=definition, the observation
ID and /criterion or /parameters/N. Do not put /definition/... under entity=result.
A numeric raw expression can stop at its unit; trailing descriptive words are
not a unit. Copy the original token without repairing the paper's notation.
Do not turn unresolved identity into a corrected stoichiometry. A component's
formula is not an alternate formula of its parent. Retain unrelated unassigned
context with its uncertainty; do not invent an A/B identity or a result for it.

Resolve an unextracted item only by explicitly named observations which carry
that same inventory ID. A document_edit may explicitly revise read coverage,
completion and limitations; otherwise they are retained. It needs source spans
and a reason, and it cannot change the work or source version. Model revision
does not grant human scientific acceptance or training eligibility.
"""
PROMPT_HASH=digest({"version":PROMPT_VERSION,"instructions":INSTRUCTIONS,"graph_prompt":GRAPH_PROMPT_HASH})


def output_schema(bundle=None,inventory=None,parent=None):
    schema=NativeEdits.model_json_schema();schema["$defs"].update(graph_schema(bundle,inventory)["$defs"])
    if bundle is not None:
        schema["properties"]["work_id"]["enum"]=[bundle.work_id]
        for definition in schema["$defs"].values():
            if "span_ids" in definition.get("properties",{}):
                definition["properties"]["span_ids"]["items"]["enum"]=list(source_catalog(bundle)["spans"])
        for k in ("processed_block_ids","unread_block_ids"):
            schema["$defs"]["RelationDocumentEdit"]["properties"][k]["items"]["enum"]=list(source_catalog(bundle)["blocks"])
    if parent is not None:
        base,_=resolve_parent(parent,bundle)
        schema["properties"]["parent_run_id"]["enum"]=[parent["run_id"]]
        schema["properties"]["base_graph_sha256"]["enum"]=[digest(base.model_dump())]
    return schema


def configuration(parent,**kwargs):
    from .worker import configuration as worker_config
    config=worker_config(workflow="inventory_v8",**kwargs)
    if config["provider"]!="codex": raise ValueError("relation_revision_provider_not_evaluated")
    config.update(workflow="relational_revision_v1",output_format=VERSION,inventory_link_projection_version=None,
        max_inventory_repairs=0,max_extraction_repairs=0,max_evidence_patches=0,max_source_revisions=1,
        parent_run_id=parent["run_id"],schema_sha256=digest(output_schema()),prompt_version=PROMPT_VERSION,prompt_sha256=PROMPT_HASH)
    return config


def render(bundle,inventory,parent):
    base,_=resolve_parent(parent,bundle)
    validation=validate_extraction(base.expand(bundle),bundle)
    coverage=validate_coverage(base,inventory,bundle)
    return "\n".join([graph_render(bundle,inventory),INSTRUCTIONS,
        "PARENT_RUN_ID: "+parent["run_id"],"BASE_GRAPH_SHA256: "+digest(base.model_dump()),
        "BASE_GRAPH: "+canonical(base.model_dump()),
        "CURRENT_TECHNICAL_DIAGNOSTICS: "+canonical(validation["issues"]+coverage["issues"]),
        "Return materials-relational-edits/1. No unchanged entities, deletion or scientific approval."])


def verify_receipt(receipt,bundle,raw_output,*,depth=0):
    parent=receipt["revision_parent"];base,inventory=resolve_parent(parent,bundle,depth=depth)
    from .relational_review import pending_review_issues
    if pending_review_issues(parent):
        raise ValueError("unresolved_review_requires_accounted_revision")
    if receipt["config"]["parent_run_id"]!=parent["run_id"] or receipt["inventory"]!=inventory.model_dump():
        raise ValueError("relation_revision_parent_inventory_mismatch")
    if "extraction" not in receipt: return base,inventory
    edits=NativeEdits.model_validate_json(raw_output)
    revision=apply_to_graph(base.model_dump(),parent["run_id"],edits)
    proof=audit_graph(base.model_dump(),parent["run_id"],revision,bundle)
    if proof!=receipt.get("revision_audit"): raise ValueError("relation_revision_audit_reconstruction_mismatch")
    if revision.revised_graph.expand(bundle).model_dump()!=receipt["extraction"]:
        raise ValueError("relation_revision_extraction_reconstruction_mismatch")
    required={(i["code"],i["path"]) for i in proof["issues"]}
    actual={(i["code"],i["path"]) for i in receipt["validation"]["issues"]}
    if not required<=actual: raise ValueError("relation_revision_audit_issues_omitted")
    return revision.revised_graph,inventory
