"""Account for every condition mutation in a source-backed graph revision.

The ledger belongs to an extraction attempt, not to the scientific schema.
Untouched conditions are preserved exactly, including their order. Supported
deletion is possible, but cannot occur as an incidental whole-state replacement.
"""
from typing import Literal

from pydantic import Field

from . import scoped_review as scoped, relational_review as review
from .contract import StrictModel, canonical, digest
from .evidence import selected_quotes, source_catalog
from .wire_v9 import output_schema as graph_schema, render as graph_render
from .validation import validate_extraction

VERSION = "materials-scoped-review/2"
PROMPT_VERSION = "materials-condition-review-prompt/1.0.0"


class ConditionChange(StrictModel):
    state_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    action: Literal["add", "replace", "remove"]
    before_sha256: str | None = Field(pattern="^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=3000)
    span_ids: list[str] = Field(min_length=1, max_length=32)


class NativeEdits(scoped.NativeEdits):
    schema_version: Literal["materials-scoped-review/2"]
    condition_changes: list[ConditionChange]


class AppliedReview(scoped.AppliedReview):
    condition_changes: list[ConditionChange]


verify_parent = scoped.verify_parent
validate_request = scoped.validate_request


def conditions(graph):
    out = {}
    for state in graph.states:
        for condition in state.conditions:
            key = (state.id, condition.id)
            if key in out: raise ValueError("condition_revision_ambiguous_identity")
            out[key] = condition.model_dump()
    return out


def _condition_audit(before, after, ledger, bundle):
    old, new = conditions(before), conditions(after)
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    declared = {(entry.state_id, entry.condition_id): entry for entry in ledger}
    if len(declared) != len(ledger) or set(declared) != changed:
        raise ValueError("condition_revision_unaccounted_change")
    # Positional evidence references must not be silently permuted. A removal
    # still requires the response to update any affected pointers and links;
    # the complete graph is subsequently checked by the ordinary validators.
    states = {state.id: state for state in after.states}
    for state in before.states:
        if state.id not in states: raise ValueError("condition_revision_state_removed")
        previous = [c.id for c in state.conditions]
        current = [c.id for c in states[state.id].conditions]
        expected = [identifier for identifier in previous if identifier in current]
        expected += [identifier for identifier in current if identifier not in previous]
        if current != expected: raise ValueError("condition_revision_reorders_existing_conditions")
    catalog, changes = source_catalog(bundle), []
    for key in sorted(changed):
        entry, left, right = declared[key], old.get(key), new.get(key)
        action = "add" if left is None else "remove" if right is None else "replace"
        if entry.action != action or entry.before_sha256 != (digest(left) if left is not None else None):
            raise ValueError("condition_revision_action_or_precondition_mismatch")
        quotes = selected_quotes(catalog, entry.span_ids)
        changes.append(dict(entry.model_dump(), before=left, after=right,
                            after_sha256=digest(right) if right is not None else None,
                            source_quotes=quotes))
    return changes


INSTRUCTIONS = """Every condition mutation needs a separate condition_changes entry.
Existing state edits still contain the complete state. Copy every unaffected
condition exactly, including ID, quantity, role, basis and order. List each
added/replaced/removed condition by state_id and condition_id, with an explicit
reason and original span_ids. Copy before_sha256 from CONDITION_PRECONDITIONS;
only add uses null. A condition_changes entry must match a real graph change.
Do not remove a valid detection floor while correcting an unrelated pressure
range. Removal requires an explicit source-grounded reason, not omission from
the replacement state. Keep retained conditions in their original order and
append new conditions. Update positional evidence/context bindings and stable
condition links if removal changes indexes. Check the complete resulting graph.
This ledger accounts for a change; it does not prove the scientific interpretation
or authorize training use. Leave unresolved source relationships unresolved.
"""
PROMPT_HASH = digest({"version": PROMPT_VERSION, "scoped_prompt": scoped.PROMPT_HASH,
                      "instructions": INSTRUCTIONS})


def configuration(parent, *, review_request, **kwargs):
    config = scoped._configuration(parent, review_request=review_request, **kwargs)
    config.update(workflow="scoped_review_v2", output_format=VERSION,
                  schema_sha256=digest(output_schema()), prompt_version=PROMPT_VERSION,
                  prompt_sha256=PROMPT_HASH)
    return config


def output_schema(bundle=None, inventory=None, parent=None, *, review_request=None):
    schema = NativeEdits.model_json_schema()
    schema["$defs"].update(graph_schema(bundle, inventory)["$defs"])
    original = scoped.output_schema(bundle, inventory, parent, review_request=review_request)
    for key in ("work_id", "parent_run_id", "base_graph_sha256", "request_sha256", "dispositions"):
        schema["properties"][key] = original["properties"][key]
    if parent is not None:
        schema["$defs"]["Disposition"] = original["$defs"]["Disposition"]
    if bundle is not None:
        catalog = source_catalog(bundle)
        for definition in schema["$defs"].values():
            if "span_ids" in definition.get("properties", {}):
                definition["properties"]["span_ids"]["items"]["enum"] = list(catalog["spans"])
        schema["$defs"]["RelationDocumentEdit"] = original["$defs"]["RelationDocumentEdit"]
    return schema


def render(bundle, inventory, parent, *, review_request):
    graph, _ = scoped.resolve_parent(parent, bundle)
    request = review._check_request(review_request, parent, bundle, graph)
    preconditions = [{"state_id": state, "condition_id": condition, "before_sha256": digest(value)}
                     for (state, condition), value in sorted(conditions(graph).items())]
    return "\n".join([graph_render(bundle, inventory), scoped.base.INSTRUCTIONS,
        review.INSTRUCTIONS, scoped.INSTRUCTIONS, INSTRUCTIONS,
        "PARENT_RUN_ID: " + parent["run_id"], "BASE_GRAPH_SHA256: " + digest(graph.model_dump()),
        "BASE_GRAPH: " + canonical(graph.model_dump()),
        "CONDITION_PRECONDITIONS: " + canonical(preconditions),
        "CURRENT_TECHNICAL_DIAGNOSTICS: " + canonical(validate_extraction(graph.expand(bundle), bundle)["issues"]),
        "SOURCE_REVIEW_REQUEST: " + canonical(request.model_dump()),
        "REQUEST_SHA256: " + digest(request.model_dump()), "Return " + VERSION + "."])


def _apply(graph, parent_run_id, edits, request, bundle):
    # Reuse the closed v1 edit semantics, then require exact nested accounting.
    old_edits = scoped.NativeEdits.model_validate(dict(edits.model_dump(exclude={"condition_changes"}),
                                                     schema_version=scoped.VERSION))
    revision = scoped._apply_graph(graph, parent_run_id, old_edits, request)
    _condition_audit(graph, revision.revised_graph, edits.condition_changes, bundle)
    return AppliedReview(**revision.model_dump(), condition_changes=edits.condition_changes)


def apply_edits(parent, bundle, edits, *, review_request):
    graph, _ = scoped.resolve_parent(parent, bundle)
    request = review._check_request(review_request, parent, bundle, graph)
    return _apply(graph, parent["run_id"], edits, request, bundle)


def _audit(graph, parent_run_id, revision, bundle):
    changes = _condition_audit(graph, revision.revised_graph, revision.condition_changes, bundle)
    return dict(review._audit_graph(graph, parent_run_id, revision, bundle),
                schema="materials-condition-review-audit/1", condition_changes=changes,
                unlisted_conditions_unchanged=True)


def audit_revision(parent, revision, bundle):
    graph, _ = scoped.resolve_parent(parent, bundle)
    return _audit(graph, parent["run_id"], revision, bundle)


def verify_receipt(receipt, bundle, raw_output, *, depth=0):
    parent = receipt["revision_parent"]
    graph, inventory = scoped.resolve_parent(parent, bundle, depth=depth)
    request = review._check_request(receipt["config"]["review_request"], parent, bundle, graph)
    if (receipt["config"]["parent_run_id"] != parent["run_id"] or receipt["inventory"] != inventory.model_dump()
            or receipt["config"]["review_request_sha256"] != digest(request.model_dump())
            or receipt.get("review_request") != request.model_dump()):
        raise ValueError("condition_receipt_request_binding_mismatch")
    if "extraction" not in receipt: return graph, inventory
    revision = _apply(graph, parent["run_id"], NativeEdits.model_validate_json(raw_output), request, bundle)
    proof = _audit(graph, parent["run_id"], revision, bundle)
    if proof != receipt.get("revision_audit") or revision.revised_graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("condition_receipt_reconstruction_mismatch")
    if not {(i["code"], i["path"]) for i in proof["issues"]} <= {(i["code"], i["path"]) for i in receipt["validation"]["issues"]}:
        raise ValueError("condition_receipt_omits_review_holds")
    return revision.revised_graph, inventory
