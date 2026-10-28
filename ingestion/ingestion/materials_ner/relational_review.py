"""Source-pinned review requests over an immutable relational NER draft.

The request and model dispositions are run artifacts, not Materials fields or
independent scientific adjudication. A disposition never proves a repair right.
"""
from typing import Literal

from pydantic import Field, model_validator

from . import relational_revision as base
from .contract import StrictModel, canonical, digest
from .evidence import selected_quotes, source_catalog

VERSION = "materials-relational-edits/2"
PROMPT_VERSION = "materials-relational-review-prompt/1.1.0"


class EntityRef(StrictModel):
    entity: Literal["sample", "state", "procedure", "result", "context", "additional_item",
                    "unextracted_item", "sample_relation", "condition_support", "document"]
    entity_id: str = Field(min_length=1, max_length=200)


class ReviewIssue(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    concern: str = Field(min_length=1, max_length=3000)
    targets: list[EntityRef] = Field(min_length=1, max_length=40)
    span_ids: list[str] = Field(min_length=1, max_length=32)


class ReviewRequest(StrictModel):
    schema_version: Literal["materials-source-review-request/1"]
    work_id: str
    parent_run_id: str = Field(pattern="^[a-f0-9]{64}$")
    bundle_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    author_kind: Literal["assistant", "human"]
    issues: list[ReviewIssue] = Field(min_length=1, max_length=12)


class Disposition(StrictModel):
    issue_id: str
    status: Literal["revised", "unchanged_supported", "unresolved"]
    reason: str = Field(min_length=1, max_length=3000)
    span_ids: list[str] = Field(min_length=1, max_length=32)
    entities: list[EntityRef] = Field(min_length=1, max_length=80)


class NativeEdits(base.NativeEdits):
    schema_version: Literal["materials-relational-edits/2"]
    request_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    dispositions: list[Disposition] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def has_change(self):
        # A complete, explicitly unresolved reread is a valid retained response.
        # It must not manufacture an edit just to pass the old nonempty rule.
        return self


class AppliedReview(base.AppliedRevision):
    request: ReviewRequest
    dispositions: list[Disposition]


def key(ref):
    return ref.entity, ref.entity_id


def pending_review_issues(parent):
    receipt = parent["receipt"]
    if receipt["config"].get("output_format") in {"materials-source-field-edits/1", "materials-source-field-edits/2", "materials-source-field-edits/3", "materials-source-field-edits/4"}:
        return receipt["review_request"]["issues"]
    if receipt["config"].get("output_format") in {"materials-scoped-review/1", "materials-scoped-review/2", "materials-scoped-review/3"} and not receipt.get("revision_audit", {}).get("valid"):
        # A failed scoped accounting audit cannot make its omitted, contradictory
        # or otherwise invalid dispositions disappear in a later request.
        return receipt["review_request"]["issues"]
    if receipt["config"].get("output_format") not in {VERSION, "materials-scoped-review/1", "materials-scoped-review/2", "materials-scoped-review/3"}:
        return []
    pending = {d["issue_id"] for d in receipt.get("revision_audit", {}).get("dispositions", [])
               if d["status"] == "unresolved"}
    original = {i["id"]: i for i in receipt["review_request"]["issues"]}
    if not pending <= original.keys():
        raise ValueError("review_pending_issue_has_no_request")
    return [original[identifier] for identifier in sorted(pending)]


def parse_request(request, parent):
    request = ReviewRequest.model_validate(request)
    if (request.work_id != parent["receipt"]["work_id"] or request.parent_run_id != parent["run_id"]
            or request.bundle_sha256 != parent["receipt"]["bundle_sha256"]):
        raise ValueError("review_request_parent_binding_mismatch")
    if len(canonical(request.model_dump()).encode()) > 32768:
        raise ValueError("review_request_byte_limit")
    if len({i.id for i in request.issues}) != len(request.issues):
        raise ValueError("review_request_duplicate_issue")
    current = {i.id: i.model_dump() for i in request.issues}
    for pending in pending_review_issues(parent):
        if current.get(pending["id"]) != pending:
            raise ValueError("review_request_drops_or_rewrites_unresolved_issue")
    return request


def _check_request(request, parent, bundle, graph):
    request = parse_request(request, parent)
    entities, catalog = base.grouped(graph.model_dump()), source_catalog(bundle)
    for issue in request.issues:
        targets = [key(ref) for ref in issue.targets]
        if len(targets) != len(set(targets)) or any(ref not in entities for ref in targets):
            raise ValueError("review_request_target_invalid")
        selected_quotes(catalog, issue.span_ids)
    return request


def validate_request(request, parent, bundle):
    graph, _ = base.resolve_parent(parent, bundle)
    return _check_request(request, parent, bundle, graph)


INSTRUCTIONS = """Perform one focused source reread for SOURCE_REVIEW_REQUEST.
The request is a disclosed review concern, not a new scientific source or a Gold
answer. Check it against the original spans. Preserve the existing native graph
and use typed edits only where the source warrants them. Concentrate on the
listed issues; retain unrelated declarations and their scientific uncertainty.

Return exactly one disposition for EVERY request issue, including issues you
cannot resolve. status=revised requires actual edits, with the affected entity
IDs and literal source spans. status=unchanged_supported requires an unchanged
target and an explanation grounded in the source. status=unresolved records the
remaining uncertainty, even when a partial edit was possible. Disposition
entities must include an original request target and all edits it accounts for.
Every changed or added entity must be accounted for by a disposition. No issue
may disappear merely because another issue was easier to fix.

Do not silently correct source stoichiometry, merge inconsistent literal
spellings, invent a method for an unknown procedure, borrow another sample's
method, or change numerical precision to satisfy a relation check. A spelling
conflict can be faithfully represented while the true composition remains
unresolved. A statement of total geometry is not proof of a separate measured
result or of its measurement method. A component's formula remains its own.

All raw fields remain source-literal, including hyphenated line breaks. Keep
criterion categories separate from their literal wording. Retain earlier and
later reported geometry with their own evidence and numeric semantics. Use an
unresolved disposition if the current representation cannot preserve the source.
An unknown null field is not a quoted assertion: omit evidence bindings to null
fields and explain the missing attribution in the disposition. Object evidence
can support its nested raw fields; evidence on a sibling field cannot. When a
state condition is added or reordered, recheck every context pointer against
its actual source subject and occurrence, not only its numerical value.
Do not declare human approval, scientific acceptance or ML qualification.
"""
PROMPT_HASH = digest({"version": PROMPT_VERSION, "instructions": INSTRUCTIONS,
                      "base_prompt": base.PROMPT_HASH})


def configuration(parent, *, review_request, **kwargs):
    request = parse_request(review_request, parent)
    config = base.configuration(parent, **kwargs)
    config.update(workflow="relational_review_v1", output_format=VERSION,
                  schema_sha256=digest(output_schema()), prompt_version=PROMPT_VERSION,
                  prompt_sha256=PROMPT_HASH, review_request=request.model_dump(),
                  review_request_sha256=digest(request.model_dump()))
    return config


def output_schema(bundle=None, inventory=None, parent=None, *, review_request=None):
    schema = NativeEdits.model_json_schema()
    original = base.output_schema(bundle, inventory, parent)
    schema["$defs"].update(original["$defs"])
    for name in ("work_id", "parent_run_id", "base_graph_sha256"):
        schema["properties"][name] = original["properties"][name]
    if review_request is not None:
        request = validate_request(review_request, parent, bundle)
        schema["properties"]["request_sha256"]["enum"] = [digest(request.model_dump())]
        schema["properties"]["dispositions"].update(minItems=len(request.issues), maxItems=len(request.issues))
        schema["$defs"]["Disposition"]["properties"]["issue_id"]["enum"] = [i.id for i in request.issues]
    if bundle is not None:
        schema["$defs"]["Disposition"]["properties"]["span_ids"]["items"]["enum"] = list(source_catalog(bundle)["spans"])
    return schema


def render(bundle, inventory, parent, *, review_request):
    request = validate_request(review_request, parent, bundle)
    return "\n".join([base.render(bundle, inventory, parent), INSTRUCTIONS,
        "SOURCE_REVIEW_REQUEST: " + canonical(request.model_dump()),
        "REQUEST_SHA256: " + digest(request.model_dump()),
        "Return materials-relational-edits/2 with every issue disposition. No independent approval."])


verify_parent = base.verify_parent


def apply_edits(parent, bundle, edits, *, review_request):
    graph, _ = base.resolve_parent(parent, bundle)
    request = _check_request(review_request, parent, bundle, graph)
    return _apply_graph(graph, parent["run_id"], edits, request)


def _apply_graph(graph, parent_run_id, edits, request):
    if digest(request.model_dump()) != edits.request_sha256:
        raise ValueError("review_response_request_hash_mismatch")
    revision = base.apply_to_graph(graph.model_dump(), parent_run_id, edits)
    return AppliedReview(**revision.model_dump(), request=request, dispositions=edits.dispositions)


def audit_revision(parent, revision, bundle):
    graph, _ = base.resolve_parent(parent, bundle)
    return _audit_graph(graph, parent["run_id"], revision, bundle)


def _audit_graph(graph, parent_run_id, revision, bundle):
    proof = base.audit_graph(graph.model_dump(), parent_run_id, revision, bundle)
    catalog = source_catalog(bundle)
    entities = base.grouped(revision.revised_graph.model_dump())
    changed = {(c["entity"], c["entity_id"]) for c in proof["changes"]}
    requested = {i.id: i for i in revision.request.issues}
    actual = {d.issue_id: d for d in revision.dispositions}
    issues = list(proof["issues"])
    def issue(code): issues.append({"code": code, "path": "/"})
    if set(actual) != set(requested) or len(actual) != len(revision.dispositions):
        issue("source_review_disposition_coverage_invalid")
    covered, dispositions = set(), []
    for disposition in revision.dispositions:
        refs = [key(r) for r in disposition.entities]
        allowed = set(entities) | {k for k in changed if k[0] == "unextracted_item"}
        if len(refs) != len(set(refs)) or any(ref not in allowed for ref in refs):
            issue("source_review_disposition_target_invalid")
        request = requested.get(disposition.issue_id)
        if request is not None and not set(refs) & {key(r) for r in request.targets}:
            issue("source_review_disposition_lost_request_target")
        quotes = []
        try:
            quotes = selected_quotes(catalog, disposition.span_ids)
        except ValueError:
            issue("source_review_disposition_source_invalid")
        if request is not None and not set(disposition.span_ids) & set(request.span_ids):
            issue("source_review_disposition_request_source_missing")
        touched = changed & set(refs)
        if disposition.status == "revised" and not touched:
            issue("source_review_revised_without_change")
        if disposition.status == "unchanged_supported" and touched:
            issue("source_review_unchanged_with_edits")
        if disposition.status == "unresolved":
            issue("source_review_issue_unresolved")
        covered.update(touched)
        dispositions.append(dict(disposition.model_dump(), source_quotes=quotes,
                                 changed_entities=[{"entity":e,"entity_id":i} for e,i in sorted(touched)]))
    if covered != changed:
        issue("source_review_unaccounted_edit")
    return dict(proof, schema="materials-source-review-audit/1", issues=issues, valid=not issues,
                request_sha256=digest(revision.request.model_dump()), dispositions=dispositions,
                issue_dispositions_are_model_claims=True, repair_correctness_independently_verified=False)


def verify_receipt(receipt, bundle, raw_output, *, depth=0):
    parent = receipt["revision_parent"]
    # Resolve each ancestor once. Calling the public apply/audit helpers here
    # would recursively verify the same parent multiple times at every level.
    graph, inventory = base.resolve_parent(parent, bundle, depth=depth)
    request = _check_request(receipt["config"]["review_request"], parent, bundle, graph)
    if (receipt["config"]["parent_run_id"] != parent["run_id"]
            or receipt["inventory"] != inventory.model_dump()
            or receipt["config"]["review_request_sha256"] != digest(request.model_dump())
            or receipt.get("review_request") != request.model_dump()):
        raise ValueError("review_receipt_request_binding_mismatch")
    if "extraction" not in receipt:
        return graph, inventory
    revision = _apply_graph(graph, parent["run_id"], NativeEdits.model_validate_json(raw_output), request)
    proof = _audit_graph(graph, parent["run_id"], revision, bundle)
    if proof != receipt.get("revision_audit"):
        raise ValueError("review_receipt_audit_reconstruction_mismatch")
    if revision.revised_graph.expand(bundle).model_dump() != receipt["extraction"]:
        raise ValueError("review_receipt_extraction_reconstruction_mismatch")
    if not {(i["code"],i["path"]) for i in proof["issues"]} <= {(i["code"],i["path"]) for i in receipt["validation"]["issues"]}:
        raise ValueError("review_receipt_audit_issues_omitted")
    return revision.revised_graph, inventory
