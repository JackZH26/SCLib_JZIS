"""Copy model-selected source slices into declared raw fields of a frozen graph.

This contract cannot modify values, owners, categories, or resolve scientific
review issues. It retains those issues for a separate source-owned review.
"""
from copy import deepcopy
import re
from typing import Literal

from pydantic import Field

from . import relational_revision as base
from . import relational_review as review
from .contract import StrictModel, canonical, digest
from .evidence import selected_quotes, source_catalog
from .wire_v8 import RelationalExtraction

VERSION = "materials-source-field-edits/1"
PROMPT_VERSION = "materials-source-field-prompt/1.1.0"


class FieldTarget(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    issue_id: str
    entity: Literal["sample", "state", "procedure", "result"]
    entity_id: str
    field: str = Field(min_length=2, max_length=300)
    expected_value_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    kind: Literal["raw_literal", "null_evidence"]
    allow_absent: bool = False


class FieldRequest(review.ReviewRequest):
    schema_version: Literal["materials-source-field-request/1"]
    fields: list[FieldTarget] = Field(min_length=1, max_length=80)


class Selection(StrictModel):
    target_id: str
    action: Literal["copy", "absent", "drop_null_binding", "unresolved"]
    span_ids: list[str] = Field(min_length=1, max_length=4)
    exact_text: str | None = Field(max_length=3000)
    occurrence: int | None = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=1500)


class NativeEdits(StrictModel):
    schema_version: Literal["materials-source-field-edits/1"]
    work_id: str
    parent_run_id: str = Field(pattern="^[a-f0-9]{64}$")
    base_graph_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    request_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    selections: list[Selection] = Field(min_length=1, max_length=80)


class AppliedFields(base.AppliedRevision):
    request: FieldRequest
    selections: list[Selection]
    field_audit: list[dict]


def issue_request(request):
    return dict(request.model_dump(exclude={"fields"}), schema_version="materials-source-review-request/1")


def parse_request(request, parent):
    request = FieldRequest.model_validate(request)
    review.parse_request(issue_request(request), parent)
    if len(canonical(request.model_dump()).encode()) > 65536:
        raise ValueError("source_field_request_byte_limit")
    return request


def location(entity, field):
    # Deliberately narrow pointer grammar: no implicit creation or JSON escape
    # aliases, negative indices, evidence editing or arbitrary key traversal.
    if not re.fullmatch(r"/(?:[A-Za-z_][A-Za-z_0-9]*|0|[1-9][0-9]*)(?:/(?:[A-Za-z_][A-Za-z_0-9]*|0|[1-9][0-9]*))*", field):
        raise ValueError("source_field_pointer_invalid")
    tokens = field[1:].split("/")
    if "evidence" in tokens:
        raise ValueError("source_field_direct_evidence_edit_forbidden")
    current = entity
    for token in tokens[:-1]:
        current = current[int(token)] if isinstance(current, list) else current[token]
    key = int(tokens[-1]) if isinstance(current, list) else tokens[-1]
    value = current[key]
    return current, key, value


def evidence_owner(entity, target):
    field = target.field
    if target.entity == "result":
        for prefix in ("/result", "/definition"):
            if field.startswith(prefix + "/"):
                return entity[prefix[1:]], field[len(prefix):]
        raise ValueError("source_field_result_namespace_required")
    return entity, field


def _check_request(request, parent, bundle, graph, *, graph_model=RelationalExtraction):
    request = parse_request(request, parent)
    review._check_request(issue_request(request), parent, bundle, graph)
    entities = base.grouped(graph.model_dump())
    issues = {i.id: i for i in request.issues}
    seen_ids, seen_fields = set(), set()
    for target in request.fields:
        identity = (target.entity, target.entity_id)
        address = (*identity, target.field)
        if target.id in seen_ids or address in seen_fields:
            raise ValueError("source_field_duplicate_target")
        seen_ids.add(target.id); seen_fields.add(address)
        if target.issue_id not in issues or identity not in {review.key(r) for r in issues[target.issue_id].targets}:
            raise ValueError("source_field_issue_target_mismatch")
        entity = entities[identity]
        _, _, value = location(entity, target.field)
        evidence_owner(entity, target)
        if digest(value) != target.expected_value_sha256:
            raise ValueError("source_field_stale_value")
        if target.kind == "raw_literal":
            if not target.field.split("/")[-1].endswith("_raw") or not isinstance(value, str):
                raise ValueError("source_field_only_existing_raw_text")
            if target.allow_absent:
                trial = deepcopy(graph.model_dump())
                node, key, _ = location(base.grouped(trial)[identity], target.field)
                node[key] = None
                graph_model.model_validate(trial)
        elif not (target.entity == "procedure" and target.field == "/method" and value is None and not target.allow_absent):
            raise ValueError("source_field_null_binding_target_invalid")
    return request


def validate_request(request, parent, bundle):
    graph, _ = base.resolve_parent(parent, bundle)
    return _check_request(request, parent, bundle, graph)


def _select(selection, catalog):
    quotes = selected_quotes(catalog, selection.span_ids)
    if selection.action != "copy":
        if selection.exact_text is not None or selection.occurrence is not None:
            raise ValueError("source_field_noncopy_has_text")
        return None, quotes
    if len(quotes) != 1 or not selection.exact_text or not selection.exact_text.strip():
        raise ValueError("source_field_copy_requires_contiguous_quote")
    # Match whitespace layout only, then copy the actual immutable source bytes.
    pattern = r"\s+".join(re.escape(word) for word in selection.exact_text.split())
    matches = list(re.finditer(pattern, quotes[0]["quote"]))
    if not matches:
        raise ValueError("source_field_quote_not_found")
    if len(matches) != 1 and selection.occurrence is None:
        raise ValueError("source_field_quote_occurrence_required")
    ordinal = selection.occurrence if selection.occurrence is not None else 0
    if ordinal >= len(matches):
        raise ValueError("source_field_occurrence_out_of_range")
    match = matches[ordinal]
    quote = quotes[0]
    return {"text": match.group(), "block_id": quote["block_id"],
            "start_char": quote["start_char"] + match.start(),
            "end_char": quote["start_char"] + match.end(), "occurrence": ordinal}, quotes


def _bind(owner, field, span_ids):
    refs = []
    for ref in owner["evidence"]:
        fields = [value for value in ref["fields"] if value != field]
        if fields:
            refs.append(dict(ref, fields=fields))
    if span_ids is not None:
        refs.append({"fields": [field], "span_ids": span_ids})
    owner["evidence"] = refs


def _apply_graph(graph, parent_run_id, edits, request, bundle, *, reject_invalid_fields=False,
                 graph_model=RelationalExtraction, applied_model=AppliedFields):
    original = graph.model_dump()
    if (edits.work_id != graph.work_id or edits.parent_run_id != parent_run_id
            or edits.base_graph_sha256 != digest(original) or edits.request_sha256 != digest(request.model_dump())):
        raise ValueError("source_field_parent_or_request_mismatch")
    targets = {t.id: t for t in request.fields}
    if len(edits.selections) != len(targets) or {s.target_id for s in edits.selections} != set(targets):
        raise ValueError("source_field_selection_coverage_invalid")
    data = deepcopy(original); entities = base.grouped(data); catalog = source_catalog(bundle)
    issues = {i.id: i for i in request.issues}; audit = []; notes = {}
    for selection in edits.selections:
        target = targets[selection.target_id]
        if not set(selection.span_ids) <= set(issues[target.issue_id].span_ids):
            raise ValueError("source_field_selection_outside_issue_source")
        entity = entities[target.entity, target.entity_id]
        before = deepcopy(entity)
        node, key, value = location(entity, target.field)
        if digest(value) != target.expected_value_sha256:
            raise ValueError("source_field_precondition_changed")
        if selection.action == "copy" and target.kind != "raw_literal":
            raise ValueError("source_field_copy_to_nonraw")
        try:
            selected, quotes = _select(selection, catalog)
        except ValueError as error:
            # v1 remains atomic. v2 retains this exact field and its old
            # evidence when a source occurrence cannot be located. Identity,
            # coverage, action, and ownership failures still reject the run.
            if not reject_invalid_fields or str(error) not in {
                    "source_field_quote_not_found", "source_field_quote_occurrence_required",
                    "source_field_occurrence_out_of_range", "source_field_copy_requires_contiguous_quote"}:
                raise
            audit.append({**selection.model_dump(), "entity": target.entity, "entity_id": target.entity_id,
                          "field": target.field, "before": value, "after": value, "changed": False,
                          "selected_source": None, "source_quotes": selected_quotes(catalog, selection.span_ids),
                          "selection_error": str(error)})
            continue
        owner, field = evidence_owner(entity, target)
        if selection.action == "copy":
            if target.kind != "raw_literal": raise ValueError("source_field_copy_to_nonraw")
            node[key] = selected["text"]
            _bind(owner, field, selection.span_ids)
        elif selection.action == "absent":
            if target.kind != "raw_literal" or not target.allow_absent:
                raise ValueError("source_field_absence_not_allowed")
            node[key] = None
            _bind(owner, field, None)
        elif selection.action == "drop_null_binding":
            if target.kind != "null_evidence" or value is not None:
                raise ValueError("source_field_cannot_drop_present_evidence")
            _bind(owner, field, None)
        changed = entity != before
        audit.append({**selection.model_dump(), "entity": target.entity, "entity_id": target.entity_id,
                      "field": target.field, "before": value, "after": node[key],
                      "changed": changed, "selected_source": selected, "source_quotes": quotes})
        if changed:
            note = notes.setdefault((target.entity, target.entity_id), {"reasons": [], "span_ids": []})
            note["reasons"].append(target.field + ": " + selection.reason)
            note["span_ids"] = list(dict.fromkeys(note["span_ids"] + selection.span_ids))
    return applied_model(parent_run_id=parent_run_id, base_graph_sha256=digest(original),
        revised_graph=graph_model.model_validate(data), request=request, selections=edits.selections,
        field_audit=audit, notes=[base.RevisionNote(entity=entity, entity_id=identifier,
            reason="\n".join(note["reasons"]), span_ids=note["span_ids"])
            for (entity, identifier), note in sorted(notes.items())])


def apply_edits(parent, bundle, edits, *, review_request):
    graph, _ = base.resolve_parent(parent, bundle)
    request = _check_request(review_request, parent, bundle, graph)
    return _apply_graph(graph, parent["run_id"], edits, request, bundle)


def _audit_graph(graph, parent_run_id, revision, bundle):
    proof = base.audit_graph(graph.model_dump(), parent_run_id, revision, bundle)
    # Field-level changes do not close broader scientific questions, even when
    # every selected literal now passes a deterministic evidence check.
    issues = list(proof["issues"])
    issues.extend({"code": "source_field_review_requires_semantic_review", "path": "/review_issues/" + i.id}
                  for i in revision.request.issues)
    issues.extend({"code": "source_field_selection_unresolved", "path": "/field_targets/" + row["target_id"]}
                  for row in revision.field_audit if row["action"] == "unresolved")
    return dict(proof, schema="materials-source-field-audit/1", issues=issues, valid=not issues,
                request_sha256=digest(revision.request.model_dump()), field_changes=revision.field_audit,
                pending_review_issues=[i.model_dump() for i in revision.request.issues],
                repair_correctness_independently_verified=False, selected_quotes_are_not_semantic_approval=True)


def audit_revision(parent, revision, bundle):
    graph, _ = base.resolve_parent(parent, bundle)
    request = _check_request(revision.request, parent, bundle, graph)
    reconstructed = _apply_graph(graph, parent["run_id"], NativeEdits(
        schema_version=VERSION, work_id=graph.work_id, parent_run_id=parent["run_id"],
        base_graph_sha256=digest(graph.model_dump()), request_sha256=digest(request.model_dump()),
        selections=revision.selections), request, bundle)
    if reconstructed.model_dump() != revision.model_dump():
        raise ValueError("source_field_undeclared_change")
    return _audit_graph(graph, parent["run_id"], revision, bundle)


INSTRUCTIONS = """Repair only REQUEST.fields using original SOURCE_CATALOG spans.
Return one selection for every target ID, including unresolved targets. Do not
return a graph or edits to numerical values, IDs, owners, categories or relations.
copy: choose an exact source excerpt for this raw field. Whitespace layout may
differ, but words, case and hyphenation may not. The program copies the actual
source slice and binds its evidence. Use occurrence=null for a unique match;
for repeated matches give the explicit zero-based occurrence in the joined spans.
Count repeated short strings before returning. A percentage appearing once in
a criterion sentence and again in multiple formulas is NOT a unique match.
Choose its actual occurrence deliberately, or quote a longer unique literal
clause. Never leave occurrence=null for those repeated strings. If a word is
split by a line-end hyphen, retain that hyphen and source whitespace or choose
a shorter intact source phrase; never silently dehyphenate. Do not stitch an
instrument name onto a quantity phrase when intervening words separate them.
Use adjacent spans if a quote crosses their boundary; never join unrelated text.
Select only spans listed for the target's issue. Check sample, result, criterion,
method and physical context, not just matching words. Preserve source conflicts.
absent: allowed only when the request explicitly allows it and the optional raw
assertion cannot be justified here; give the source-scoped reason. This is not a
claim that the full paper reports no such property. drop_null_binding: remove
only evidence attached to the declared null procedure method. unresolved: keep
the field and evidence exactly as they are if no faithful choice is possible.
For every non-copy action exact_text and occurrence are null. Give source spans
and a short English reason for every action. No scientific issue is closed by
this response. Retain full value semantics and never erase a distinction simply
to satisfy a literal matcher. GRAPH_CONTEXT and REQUEST are fallible proposals;
only original source text supplies scientific assertions.
"""
PROMPT_HASH = digest({"version": PROMPT_VERSION, "instructions": INSTRUCTIONS})


def configuration(parent, *, review_request, **kwargs):
    request = parse_request(review_request, parent)
    config = base.configuration(parent, **kwargs)
    config.update(workflow="source_field_revision_v1", output_format=VERSION,
        schema_sha256=digest(output_schema()), prompt_version=PROMPT_VERSION, prompt_sha256=PROMPT_HASH,
        review_request=request.model_dump(), review_request_sha256=digest(request.model_dump()))
    return config


def output_schema(bundle=None, inventory=None, parent=None, *, review_request=None,
                  resolver=base.resolve_parent, graph_model=RelationalExtraction):
    schema = NativeEdits.model_json_schema()
    if parent is not None:
        graph, _ = resolver(parent, bundle)
        request = _check_request(review_request, parent, bundle, graph, graph_model=graph_model)
        for key, value in {"work_id": bundle.work_id, "parent_run_id": parent["run_id"],
                           "base_graph_sha256": digest(graph.model_dump()), "request_sha256": digest(request.model_dump())}.items():
            schema["properties"][key]["enum"] = [value]
        schema["properties"]["selections"].update(minItems=len(request.fields), maxItems=len(request.fields))
        schema["$defs"]["Selection"]["properties"]["target_id"]["enum"] = [t.id for t in request.fields]
        schema["$defs"]["Selection"]["properties"]["span_ids"]["items"]["enum"] = list(source_catalog(bundle)["spans"])
    return schema


def render(bundle, inventory, parent, *, review_request, resolver=base.resolve_parent,
           graph_model=RelationalExtraction):
    graph, _ = resolver(parent, bundle)
    request = _check_request(review_request, parent, bundle, graph, graph_model=graph_model)
    def without_evidence(value):
        if isinstance(value, dict): return {k: without_evidence(v) for k, v in value.items() if k != "evidence"}
        if isinstance(value, list): return [without_evidence(v) for v in value]
        return value
    entities = base.grouped(graph.model_dump())
    values = [{"target_id": t.id, "current_value": location(entities[t.entity, t.entity_id], t.field)[2]}
              for t in request.fields]
    return "\n".join([INSTRUCTIONS, "REQUEST: " + canonical(request.model_dump()),
        "REQUEST_SHA256: " + digest(request.model_dump()), "BASE_GRAPH_SHA256: " + digest(graph.model_dump()),
        "TARGET_VALUES: " + canonical(values), "GRAPH_CONTEXT: " + canonical(without_evidence(graph.model_dump())),
        "SOURCE_CATALOG: " + canonical(source_catalog(bundle)), "Return materials-source-field-edits/1."])


verify_parent = base.verify_parent


def verify_receipt(receipt, bundle, raw_output, *, depth=0):
    parent = receipt["revision_parent"]
    graph, inventory = base.resolve_parent(parent, bundle, depth=depth)
    request = FieldRequest.model_validate(receipt["config"]["review_request"])
    if (receipt["config"]["parent_run_id"] != parent["run_id"] or receipt["inventory"] != inventory.model_dump()
            or receipt.get("review_request") != request.model_dump()
            or receipt["config"]["review_request_sha256"] != digest(request.model_dump())):
        raise ValueError("source_field_receipt_request_mismatch")
    if "extraction" not in receipt: return graph, inventory
    request = _check_request(request, parent, bundle, graph)
    revision = _apply_graph(graph, parent["run_id"], NativeEdits.model_validate_json(raw_output), request, bundle)
    proof = _audit_graph(graph, parent["run_id"], revision, bundle)
    if proof != receipt.get("revision_audit") or revision.revised_graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("source_field_receipt_reconstruction_mismatch")
    if not {(i["code"], i["path"]) for i in proof["issues"]} <= {(i["code"], i["path"]) for i in receipt["validation"]["issues"]}:
        raise ValueError("source_field_receipt_omits_review_holds")
    return revision.revised_graph, inventory
