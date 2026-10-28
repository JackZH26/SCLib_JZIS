"""Exact source selections for scoped graphs, retaining all semantic review holds."""
from typing import Literal

from . import source_field_revision as fields, source_field_local as local, scoped_review as scoped
from .contract import digest
from .wire_v9 import ScopedExtraction

VERSION = "materials-source-field-edits/3"
PROMPT_VERSION = "materials-source-field-scoped-prompt/1.0.0"
PROMPT_HASH = digest({"version": PROMPT_VERSION, "field_prompt": fields.PROMPT_HASH,
                      "local_prompt": local.PROMPT_HASH, "scoped_graph": "materials-ner-shared/5"})


class NativeEdits(fields.NativeEdits):
    schema_version: Literal["materials-source-field-edits/3"]


class AppliedFields(fields.AppliedFields):
    revised_graph: ScopedExtraction


verify_parent = scoped.verify_parent


def _request(request, parent, bundle, graph):
    return fields._check_request(request, parent, bundle, graph, graph_model=ScopedExtraction)


def validate_request(request, parent, bundle):
    graph, _ = scoped.resolve_parent(parent, bundle)
    return _request(request, parent, bundle, graph)


def configuration(parent, *, review_request, **kwargs):
    request = fields.parse_request(review_request, parent)
    config = scoped._configuration(parent, review_request=fields.issue_request(request), **kwargs)
    config.update(workflow="source_field_revision_v3", output_format=VERSION,
        schema_sha256=digest(output_schema()), prompt_version=PROMPT_VERSION, prompt_sha256=PROMPT_HASH,
        review_request=request.model_dump(), review_request_sha256=digest(request.model_dump()))
    return config


def output_schema(bundle=None, inventory=None, parent=None, *, review_request=None):
    schema = fields.output_schema(bundle, inventory, parent, review_request=review_request,
                                  resolver=scoped.resolve_parent, graph_model=ScopedExtraction)
    schema["properties"]["schema_version"]["const"] = VERSION
    schema["title"] = "ScopedFieldEdits"
    return schema


def render(bundle, inventory, parent, *, review_request):
    return fields.render(bundle, inventory, parent, review_request=review_request,
        resolver=scoped.resolve_parent, graph_model=ScopedExtraction).replace(
            "Return materials-source-field-edits/1.", local.INSTRUCTIONS + "\nReturn " + VERSION + ".")


def _apply(graph, parent_run_id, edits, request, bundle):
    return fields._apply_graph(graph, parent_run_id, edits, request, bundle, reject_invalid_fields=True,
                               graph_model=ScopedExtraction, applied_model=AppliedFields)


def apply_edits(parent, bundle, edits, *, review_request):
    graph, _ = scoped.resolve_parent(parent, bundle)
    return _apply(graph, parent["run_id"], edits, _request(review_request, parent, bundle, graph), bundle)


def _audit(graph, parent_run_id, revision, bundle):
    return dict(local._audit(graph, parent_run_id, revision, bundle), schema="materials-source-field-audit/3")


def audit_revision(parent, revision, bundle):
    graph, _ = scoped.resolve_parent(parent, bundle)
    request = _request(revision.request, parent, bundle, graph)
    rebuilt = _apply(graph, parent["run_id"], NativeEdits(schema_version=VERSION, work_id=graph.work_id,
        parent_run_id=parent["run_id"], base_graph_sha256=digest(graph.model_dump()),
        request_sha256=digest(request.model_dump()), selections=revision.selections), request, bundle)
    if rebuilt.model_dump() != revision.model_dump(): raise ValueError("source_field_undeclared_change")
    return _audit(graph, parent["run_id"], revision, bundle)


def verify_receipt(receipt, bundle, raw_output, *, depth=0):
    parent = receipt["revision_parent"]
    graph, inventory = scoped.resolve_parent(parent, bundle, depth=depth)
    request = fields.FieldRequest.model_validate(receipt["config"]["review_request"])
    if (receipt["config"]["parent_run_id"] != parent["run_id"] or receipt["inventory"] != inventory.model_dump()
            or receipt.get("review_request") != request.model_dump()
            or receipt["config"]["review_request_sha256"] != digest(request.model_dump())):
        raise ValueError("source_field_receipt_request_mismatch")
    if "extraction" not in receipt: return graph, inventory
    request = _request(request, parent, bundle, graph)
    revision = _apply(graph, parent["run_id"], NativeEdits.model_validate_json(raw_output), request, bundle)
    proof = _audit(graph, parent["run_id"], revision, bundle)
    if proof != receipt.get("revision_audit") or revision.revised_graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("source_field_receipt_reconstruction_mismatch")
    if not {(i["code"], i["path"]) for i in proof["issues"]} <= {(i["code"], i["path"]) for i in receipt["validation"]["issues"]}:
        raise ValueError("source_field_receipt_omits_review_holds")
    return revision.revised_graph, inventory
