"""Versioned source review for scoped-role graphs; historical edits stay closed."""
from typing import Literal, Union, get_args

from pydantic import create_model

from . import relational_revision as base, relational_review as review
from .contract import canonical, digest
from .evidence import source_catalog
from .inventory import Inventory
from .inventory_links import verify_inventory_projection
from .sources import sha
from .wire_v9 import ScopedExtraction, output_schema as graph_schema, render as graph_render, PROMPT_HASH as GRAPH_HASH
from .validation import validate_extraction

VERSION = "materials-scoped-review/1"
PROMPT_VERSION = "materials-scoped-review-prompt/1.0.0"
state_type = get_args(ScopedExtraction.model_fields["states"].annotation)[0]
StateEdit = create_model("ScopedStateEdit", __base__=base.EditBase,
    entity=(Literal["state"], ...), value=(state_type, ...))
edit_types = tuple(StateEdit if get_args(model.model_fields["entity"].annotation) == ("state",) else model
                   for model in base.EDIT_MODELS)


class NativeEdits(review.NativeEdits):
    schema_version: Literal["materials-scoped-review/1"]
    edits: list[Union[edit_types]]


class AppliedScoped(base.AppliedRevision):
    revised_graph: ScopedExtraction


class AppliedReview(review.AppliedReview):
    revised_graph: ScopedExtraction


def resolve_parent(parent, bundle, *, depth=0):
    if depth > base.MAX_REVISION_DEPTH: raise ValueError("scoped_revision_ancestry_limit")
    receipt, raw = parent["receipt"], parent["raw_output"]
    if (digest(receipt) != parent["run_id"] or not isinstance(raw, str)
            or receipt.get("raw_output_sha256") != sha(raw.encode())):
        raise ValueError("scoped_parent_receipt_hash_mismatch")
    if (receipt["work_id"] != bundle.work_id or receipt["bundle_sha256"] != digest(bundle.model_dump())
            or receipt["state"] not in {"succeeded", "quarantined"} or "extraction" not in receipt):
        raise ValueError("scoped_revision_requires_structured_terminal_parent")
    format_ = receipt["config"].get("output_format")
    if format_ == "materials-ner-shared/5":
        if receipt.get("evidence_patch"): raise ValueError("scoped_parent_patch_not_supported")
        verify_inventory_projection(receipt, bundle)
        graph = ScopedExtraction.model_validate_json(raw)
        inventory = Inventory.model_validate(receipt["inventory"])
    elif format_ == VERSION:
        graph, inventory = verify_receipt(receipt, bundle, raw, depth=depth + 1)
    elif format_ == "materials-scoped-review/2":
        from .condition_review import verify_receipt as verify_conditions
        graph, inventory = verify_conditions(receipt, bundle, raw, depth=depth + 1)
    elif format_ == "materials-scoped-review/3":
        from .coverage_revision import verify_receipt as verify_coverage
        graph, inventory = verify_coverage(receipt, bundle, raw, depth=depth + 1)
    elif format_ == "materials-source-field-edits/3":
        from .source_field_scoped import verify_receipt as verify_fields
        graph, inventory = verify_fields(receipt, bundle, raw, depth=depth + 1)
    elif format_ == "materials-source-field-edits/4":
        from .source_field_focus import verify_receipt as verify_focused_fields
        graph, inventory = verify_focused_fields(receipt, bundle, raw, depth=depth + 1)
    else:
        raise ValueError("unsupported_scoped_revision_parent")
    if graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("scoped_parent_graph_reconstruction_mismatch")
    return graph, inventory


def verify_parent(parent, bundle): return resolve_parent(parent, bundle)[1]


def validate_request(request, parent, bundle):
    graph, _ = resolve_parent(parent, bundle)
    return review._check_request(request, parent, bundle, graph)


INSTRUCTIONS = """Review the scoped graph without changing its version or condition roles.
A phase number, structural transition, run number or pressure region does not
establish a primary/secondary superconducting transition stage. Keep a stage
only when the source explicitly supports that meaning for this observation;
otherwise omit the unsupported qualifier with a source-backed change note.
Preserve each applicable phase range as study_extent, without turning it into
the exact pressure of one Tc. Distinct ranges from structural and transport
studies keep their own source scope. Do not bind a context to unrelated values
merely because both occur in one paper or refer to the same phase label.
A false or unrepresented inventory context stays explicitly unresolved with
empty bindings. An identity_conflict label from the first read is not proof of
a conflict. Bind only actually emitted fields and their own source occurrences.
Keep literal source fields exact. Treat the source-review request as fallible
concerns, not prescribed answers. Review dispositions account for changed
entities: use revised or unresolved for an entity that this response changes,
even if another field on that entity was already correct. No scientific approval.
"""
PROMPT_HASH = digest({"version": PROMPT_VERSION, "instructions": INSTRUCTIONS,
    "graph": GRAPH_HASH, "edits": base.PROMPT_HASH, "review": review.PROMPT_HASH})


def requires_condition_accounting(parent):
    for _ in range(base.MAX_REVISION_DEPTH + 1):
        receipt = parent["receipt"]
        if receipt["config"].get("output_format") in {"materials-scoped-review/2", "materials-scoped-review/3"}: return True
        parent = receipt.get("revision_parent")
        if parent is None: return False
    raise ValueError("scoped_revision_ancestry_limit")


def configuration(parent, *, review_request, **kwargs):
    if requires_condition_accounting(parent): raise ValueError("condition_revision_downgrade_forbidden")
    return _configuration(parent, review_request=review_request, **kwargs)


def _configuration(parent, *, review_request, **kwargs):
    from .worker import configuration as worker_config
    request = review.parse_request(review_request, parent)
    config = worker_config(workflow="inventory_v9", **kwargs)
    if config["provider"] != "codex": raise ValueError("scoped_revision_provider_not_evaluated")
    config.update(workflow="scoped_review_v1", output_format=VERSION, inventory_link_projection_version=None,
        max_inventory_repairs=0, max_extraction_repairs=0, max_evidence_patches=0, max_source_revisions=1,
        parent_run_id=parent["run_id"], schema_sha256=digest(output_schema()),
        prompt_version=PROMPT_VERSION, prompt_sha256=PROMPT_HASH,
        review_request=request.model_dump(), review_request_sha256=digest(request.model_dump()))
    return config


def output_schema(bundle=None, inventory=None, parent=None, *, review_request=None):
    schema = NativeEdits.model_json_schema()
    schema["$defs"].update(graph_schema(bundle, inventory)["$defs"])
    if bundle is not None:
        catalog = source_catalog(bundle)
        schema["properties"]["work_id"]["enum"] = [bundle.work_id]
        for definition in schema["$defs"].values():
            if "span_ids" in definition.get("properties", {}):
                definition["properties"]["span_ids"]["items"]["enum"] = list(catalog["spans"])
        for key in ("processed_block_ids", "unread_block_ids"):
            schema["$defs"]["RelationDocumentEdit"]["properties"][key]["items"]["enum"] = list(catalog["blocks"])
    if parent is not None:
        graph, _ = resolve_parent(parent, bundle)
        request = validate_request(review_request, parent, bundle)
        for key, value in {"parent_run_id": parent["run_id"], "base_graph_sha256": digest(graph.model_dump()),
                           "request_sha256": digest(request.model_dump())}.items():
            schema["properties"][key]["enum"] = [value]
        schema["properties"]["dispositions"].update(minItems=len(request.issues), maxItems=len(request.issues))
        schema["$defs"]["Disposition"]["properties"]["issue_id"]["enum"] = [i.id for i in request.issues]
    return schema


def render(bundle, inventory, parent, *, review_request):
    graph, _ = resolve_parent(parent, bundle)
    request = review._check_request(review_request, parent, bundle, graph)
    return "\n".join([graph_render(bundle, inventory), base.INSTRUCTIONS, review.INSTRUCTIONS, INSTRUCTIONS,
        "PARENT_RUN_ID: " + parent["run_id"], "BASE_GRAPH_SHA256: " + digest(graph.model_dump()),
        "BASE_GRAPH: " + canonical(graph.model_dump()),
        "CURRENT_TECHNICAL_DIAGNOSTICS: " + canonical(validate_extraction(graph.expand(bundle), bundle)["issues"]),
        "SOURCE_REVIEW_REQUEST: " + canonical(request.model_dump()), "REQUEST_SHA256: " + digest(request.model_dump()),
        "Return " + VERSION + " with all requested dispositions."])


def _apply_graph(graph, parent_run_id, edits, request):
    if edits.request_sha256 != digest(request.model_dump()): raise ValueError("review_response_request_hash_mismatch")
    revision = base.apply_to_graph(graph.model_dump(), parent_run_id, edits,
        graph_model=ScopedExtraction, applied_model=AppliedScoped)
    return AppliedReview(**revision.model_dump(), request=request, dispositions=edits.dispositions)


def apply_edits(parent, bundle, edits, *, review_request):
    if requires_condition_accounting(parent): raise ValueError("condition_revision_downgrade_forbidden")
    graph, _ = resolve_parent(parent, bundle)
    request = review._check_request(review_request, parent, bundle, graph)
    return _apply_graph(graph, parent["run_id"], edits, request)


def audit_revision(parent, revision, bundle):
    graph, _ = resolve_parent(parent, bundle)
    return review._audit_graph(graph, parent["run_id"], revision, bundle)


def verify_receipt(receipt, bundle, raw_output, *, depth=0):
    parent = receipt["revision_parent"]
    if requires_condition_accounting(parent): raise ValueError("condition_revision_downgrade_forbidden")
    graph, inventory = resolve_parent(parent, bundle, depth=depth)
    request = review._check_request(receipt["config"]["review_request"], parent, bundle, graph)
    if (receipt["config"]["parent_run_id"] != parent["run_id"] or receipt["inventory"] != inventory.model_dump()
            or receipt["config"]["review_request_sha256"] != digest(request.model_dump())
            or receipt.get("review_request") != request.model_dump()):
        raise ValueError("scoped_receipt_request_binding_mismatch")
    if "extraction" not in receipt: return graph, inventory
    revision = _apply_graph(graph, parent["run_id"], NativeEdits.model_validate_json(raw_output), request)
    proof = review._audit_graph(graph, parent["run_id"], revision, bundle)
    if proof != receipt.get("revision_audit") or revision.revised_graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("scoped_receipt_reconstruction_mismatch")
    if not {(i["code"], i["path"]) for i in proof["issues"]} <= {(i["code"], i["path"]) for i in receipt["validation"]["issues"]}:
        raise ValueError("scoped_receipt_omits_review_holds")
    return revision.revised_graph, inventory
