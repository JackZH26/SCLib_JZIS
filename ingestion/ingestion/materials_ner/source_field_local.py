"""v2 source-field revisions isolate unlocatable quotes without guessing them.

The v1 verifier remains atomic. No old receipt or failed graph is rewritten.
"""
from typing import Literal

from . import source_field_revision as fields
from . import relational_revision as base
from .contract import digest

VERSION = "materials-source-field-edits/2"
PROMPT_VERSION = "materials-source-field-local-prompt/1.0.0"
INSTRUCTIONS = """Each field's source location is checked independently. An
unlocatable or ambiguous quote will leave that field AND its evidence unchanged,
with an explicit rejection in the audit. The system never picks another occurrence
or repairs your text. Other source-valid selections may be retained for review.
Every original issue and every rejected field remain pending. Global identity,
coverage and unauthorized-edit failures still reject the complete response.
"""
PROMPT_HASH = digest({"version": PROMPT_VERSION, "instructions": INSTRUCTIONS, "field_prompt": fields.PROMPT_HASH})


class NativeEdits(fields.NativeEdits):
    schema_version: Literal["materials-source-field-edits/2"]


validate_request = fields.validate_request
verify_parent = base.verify_parent


def configuration(parent, *, review_request, **kwargs):
    config = fields.configuration(parent, review_request=review_request, **kwargs)
    config.update(workflow="source_field_revision_v2", output_format=VERSION,
                  schema_sha256=digest(output_schema()), prompt_version=PROMPT_VERSION, prompt_sha256=PROMPT_HASH)
    return config


def output_schema(bundle=None, inventory=None, parent=None, *, review_request=None):
    schema = fields.output_schema(bundle, inventory, parent, review_request=review_request)
    schema["properties"]["schema_version"]["const"] = VERSION
    schema["title"] = "LocalFieldEdits"
    return schema


def render(bundle, inventory, parent, *, review_request):
    return fields.render(bundle, inventory, parent, review_request=review_request).replace(
        "Return materials-source-field-edits/1.", INSTRUCTIONS + "\nReturn " + VERSION + ".")


def _apply(graph, parent_run_id, edits, request, bundle):
    return fields._apply_graph(graph, parent_run_id, edits, request, bundle, reject_invalid_fields=True)


def apply_edits(parent, bundle, edits, *, review_request):
    graph, _ = base.resolve_parent(parent, bundle)
    request = fields._check_request(review_request, parent, bundle, graph)
    return _apply(graph, parent["run_id"], edits, request, bundle)


def _audit(graph, parent_run_id, revision, bundle):
    proof = fields._audit_graph(graph, parent_run_id, revision, bundle)
    rejected = [row for row in revision.field_audit if row.get("selection_error")]
    proof["issues"].extend({"code": "source_field_selection_rejected", "path": "/field_targets/" + row["target_id"]}
                           for row in rejected)
    return dict(proof, schema="materials-source-field-audit/2", valid=not proof["issues"],
                rejected_field_count=len(rejected), invalid_fields_and_evidence_preserved=True,
                occurrence_fallback_or_text_correction_used=False)


def audit_revision(parent, revision, bundle):
    graph, _ = base.resolve_parent(parent, bundle)
    request = fields._check_request(revision.request, parent, bundle, graph)
    rebuilt = _apply(graph, parent["run_id"], NativeEdits(schema_version=VERSION, work_id=graph.work_id,
        parent_run_id=parent["run_id"], base_graph_sha256=digest(graph.model_dump()),
        request_sha256=digest(request.model_dump()), selections=revision.selections), request, bundle)
    if rebuilt.model_dump() != revision.model_dump(): raise ValueError("source_field_undeclared_change")
    return _audit(graph, parent["run_id"], revision, bundle)


def verify_receipt(receipt, bundle, raw_output, *, depth=0):
    parent = receipt["revision_parent"]
    graph, inventory = base.resolve_parent(parent, bundle, depth=depth)
    request = fields.FieldRequest.model_validate(receipt["config"]["review_request"])
    if (receipt["config"]["parent_run_id"] != parent["run_id"] or receipt["inventory"] != inventory.model_dump()
            or receipt.get("review_request") != request.model_dump()
            or receipt["config"]["review_request_sha256"] != digest(request.model_dump())):
        raise ValueError("source_field_receipt_request_mismatch")
    if "extraction" not in receipt: return graph, inventory
    request = fields._check_request(request, parent, bundle, graph)
    revision = _apply(graph, parent["run_id"], NativeEdits.model_validate_json(raw_output), request, bundle)
    proof = _audit(graph, parent["run_id"], revision, bundle)
    if proof != receipt.get("revision_audit") or revision.revised_graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("source_field_receipt_reconstruction_mismatch")
    if not {(i["code"], i["path"]) for i in proof["issues"]} <= {(i["code"], i["path"]) for i in receipt["validation"]["issues"]}:
        raise ValueError("source_field_receipt_omits_review_holds")
    return revision.revised_graph, inventory
