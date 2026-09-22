"""Provider-free, generation-scoped exact extraction lookup with live holds.

Original chunks can carry all paper-level material extractions. They must never
be mistaken for original support of an arbitrary record in that list. This
lookup only reports records whose full input hash equals their verified 0060
derived-Fact parent, with an explicit non-approval association scope.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import UUID

import sqlalchemy as sa

from models.scientific_lookup import (
    LinkedScientificResult,
    ScientificLookupStatus,
    ScientificResultBinding,
)
from services import index_generations, index_retrieval, retrieval_currentness
from services.rag_evidence_contract import input_record_sha256
from services.retrieval_groups import resolve_grouping_bindings
from services.scientific_query_results import select_record_results
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import (
    occurrence_visibility,
    project_source_occurrences,
    source_visibility,
)

MAX_RESULTS = 20
MAX_RECORDS = 5000
MAX_PREPARED_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class LookupResult:
    results: list[LinkedScientificResult]
    status: ScientificLookupStatus


def _json(value):
    """Detach private JSON, retaining every raw field without ORM aliases."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_PREPARED_BYTES:
        raise ValueError("Scientific lookup preparation exceeds its byte bound")
    return encoded


@dataclass(frozen=True, slots=True)
class PreparedScientificParent:
    """One exact retained extraction, not an original-passage association.

    JSON properties return fresh copies. No mutable ORM object or vector bytes
    escape preparation; the complete retained text/attribution and raw record
    remain available to the private mixed coordinator.
    """
    result_id: str
    record_index: int
    parent_result_revision_id: str
    paper_id: str
    vector_id: str
    source_snapshot_sha256: str
    input_record_sha256: str
    selection_pin: retrieval_currentness.SelectionPin
    _raw_record_json: str = field(repr=False)
    _member_json: str = field(repr=False)

    @property
    def raw_record(self):
        return json.loads(self._raw_record_json)

    @property
    def member(self):
        return json.loads(self._member_json)


@dataclass(frozen=True, slots=True)
class ScientificLookupInputs:
    """Immutable private inputs; consumption is not a fresh-read approval.

    The coordinator must check the entire final numeric/original selection in
    one fresh snapshot and discard *all* outputs on failure. Reusing these
    historical bytes is never evidence that they remain currently admissible.
    """
    parents: tuple[PreparedScientificParent, ...]
    _outcome_json: str = field(repr=False)
    _generation_pin_json: str = field(repr=False)

    def __post_init__(self):
        outcome, generation = self.outcome, self.generation_pin
        if (type(self.parents) is not tuple or len(self.parents) > MAX_RESULTS
                or len(outcome.results) != len(self.parents)
                or outcome.status.returned_count != len(self.parents)
                or (outcome.status.status != "completed" and self.parents)
                or len({parent.parent_result_revision_id for parent in self.parents}) != len(self.parents)
                or len({parent.vector_id for parent in self.parents}) != len(self.parents)):
            raise ValueError("Scientific preparation requires an exact one-to-one parent inventory")
        size = len(self._outcome_json.encode("utf-8")) + len(self._generation_pin_json.encode("utf-8"))
        for row, parent in zip(outcome.results, self.parents, strict=True):
            if type(parent) is not PreparedScientificParent:
                raise ValueError("Scientific preparation requires immutable parents")
            member, raw, binding = parent.member, parent.raw_record, row.binding
            if (generation is None or parent.result_id != row.result.result_id
                    or parent.record_index != row.result.record_index
                    or parent.parent_result_revision_id != binding.parent_result_revision_id
                    or parent.paper_id != binding.paper_id or parent.vector_id != binding.vector_id
                    or parent.selection_pin.chunk_id != parent.vector_id
                    or parent.selection_pin.paper_id != parent.paper_id
                    or parent.selection_pin.generation_pin_sha256 != index_retrieval.pin_sha256(generation)
                    or not parent.selection_pin.has_evidence_pin or parent.selection_pin.grouping_sha256 is None
                    or any(getattr(binding, key) != generation[key] for key in
                           ("generation_id", "activation_event_id", "manifest_sha256"))
                    or any(member[key] != getattr(binding, key) for key in
                           ("paper_id", "vector_id", "generation_id", "content_sha256", "evidence_revision_id", "evidence_record_sha256"))
                    or member["source_snapshot_sha256"] != parent.source_snapshot_sha256
                    or input_record_sha256(raw) != parent.input_record_sha256
                    or input_record_sha256(member["snapshot_json"]["materials_mentioned"][parent.record_index])
                       != parent.input_record_sha256):
                raise ValueError("Scientific preparation parent/result/pin binding mismatch")
            size += len(parent._raw_record_json.encode("utf-8")) + len(parent._member_json.encode("utf-8"))
        if size > MAX_PREPARED_BYTES:
            raise ValueError("Scientific lookup preparation exceeds its byte bound")

    @property
    def outcome(self):
        value = json.loads(self._outcome_json)
        return LookupResult([LinkedScientificResult.model_validate(row) for row in value["results"]],
                            ScientificLookupStatus.model_validate(value["status"]))

    @property
    def selection_pins(self):
        return tuple(parent.selection_pin for parent in self.parents)

    @property
    def generation_pin(self):
        return json.loads(self._generation_pin_json)


class PreparedScientificLookup:
    """Single-consumption coordinator handle, not an authorization capability.

    Copying/serializing this handle is refused. Once consumed, including when
    the ensuing fresh check fails, this handle cannot supply another outcome.
    Its input value contains detached snapshots, never live mutable aliases.
    """
    __slots__ = ("_inputs",)

    def __init__(self, inputs: ScientificLookupInputs):
        if type(inputs) is not ScientificLookupInputs:
            raise ValueError("Validated scientific preparation inputs are required")
        self._inputs = inputs

    def _available(self):
        if self._inputs is None:
            raise ValueError("Scientific lookup preparation has already been consumed")
        return self._inputs

    @property
    def outcome(self):
        return self._available().outcome

    @property
    def selection_pins(self):
        return self._available().selection_pins

    @property
    def parents(self):
        return self._available().parents

    def consume(self) -> ScientificLookupInputs:
        inputs = self._available()
        self._inputs = None
        return inputs

    def __copy__(self):
        raise TypeError("Scientific lookup preparation is a single-consumption handle")

    def __deepcopy__(self, memo):
        return self.__copy__()

    def __reduce_ex__(self, protocol):
        return self.__copy__()


def _prepared(outcome, pin, parents=()):
    return PreparedScientificLookup(ScientificLookupInputs(tuple(parents), _json({
        "results": [row.model_dump(mode="json") for row in outcome.results],
        "status": outcome.status.model_dump(mode="json"),
    }), _json(pin)))


def result_query(interpretation):
    return (bool(interpretation.evidence_constraints) or interpretation.intent == "numerical"
            or interpretation.intent in {"mixed", "comparison"} and bool(interpretation.requested_fields
                or interpretation.constraints or interpretation.evidence_constraints))


def unavailable(reason):
    return LookupResult([], ScientificLookupStatus(status="unavailable", reason_codes=[reason]))


async def prepare_scientific_lookup(db, pin, interpretation, *, limit=20, filters=None,
                                    year_min=None, year_max=None, sort="relevance") -> PreparedScientificLookup:
    """Prepare exact complete-parent matches in the caller's read transaction.

    No commit, rollback, provider call or independent fresh check occurs here,
    on success *or failure*. Exceptions propagate; the caller owns transaction
    cleanup. Before publishing, consume once, end this read transaction and
    check the complete final selected inventory in a NEW read snapshot. A
    clean ORM session is required but cannot detect caller-owned Core writes.
    """
    if (db.new or db.dirty or db.deleted or type(limit) is not int or not 1 <= limit <= MAX_RESULTS
            or sort not in {"relevance", "date", "tc"}):
        raise ValueError("A clean session and bounded result count are required")
    if interpretation.status != "resolved":
        return _prepared(LookupResult([], ScientificLookupStatus(status="clarification_required",
            reason_codes=["unresolved_query_constraints"])), None)
    if pin is None:
        return _prepared(unavailable("active_generation_required"), None)
    # The caller may retain its mutable pin object across awaits. Bind this
    # operation to a private exact copy, including the activation event (ABA).
    pin = json.loads(_json(pin))
    from services.index_corpus import is_corpus
    if await is_corpus(db, pin["generation_id"]):
        # This corpus format admits retained legacy windows only. Its SQL
        # membership guard forbids derived extraction parents; do not fabricate
        # such parents by interpreting old material metadata as reviewed input.
        return _prepared(LookupResult([], ScientificLookupStatus(status="completed",
            reason_codes=["retained_legacy_no_extraction_parents"])), pin)
    members = await index_generations.load_generation_members(db, generation_id=pin["generation_id"])
    if index_generations.manifest_sha256(members) != pin["manifest_sha256"]:
        raise ValueError("Scientific lookup generation inventory is incomplete")
    keyword_ids = None
    if interpretation.intent == "general" and filters is not None and filters.active:
        # UI predicates do not authorize discarding the user's opaque keyword
        # query. Formula notation is checked per record below; remaining words
        # keep the established English PostgreSQL fulltext semantics. Scan the
        # whole already-bounded generation, never an invisible top-300 prefix.
        remaining = list(interpretation.raw_query)
        for span in [*interpretation.formulas, *interpretation.constraints, *interpretation.evidence_constraints]:
            remaining[span.start:span.end] = [" "] * (span.end - span.start)
        keywords = "".join(remaining).strip()
        if keywords:
            keyword_ids = set((await db.execute(sa.text("""
                SELECT vector_id FROM index_generation_members
                WHERE generation_id=:generation AND
                  (numnode(websearch_to_tsquery('english'::regconfig,:query))=0 OR
                   to_tsvector('english'::regconfig,coalesce(snapshot_json->>'title','')||' '||
                     (snapshot_json->>'text')) @@ websearch_to_tsquery('english'::regconfig,:query))
                """), {"generation": UUID(pin["generation_id"]), "query": keywords})).scalars().all())
    ids = [UUID(member["evidence_revision_id"]) for member in members]
    statement = sa.text("""SELECT e.id,e.paper_id,e.parent_extraction_revision_id,
        e.record_sha256 AS evidence_hash, p.input_record_sha256,p.record_sha256 AS parent_hash,
        e.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(e)) AS evidence_intact,
        p.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(p)) AS parent_intact
        FROM rag_evidence_revisions e JOIN rag_extraction_revisions p ON p.id=e.parent_extraction_revision_id
        WHERE e.id IN :ids AND e.chunk_kind='derived_fact' AND e.paper_id=p.paper_id
          AND e.source_snapshot_sha256=p.source_snapshot_sha256""").bindparams(sa.bindparam("ids", expanding=True, type_=sa.Uuid()))
    parents = {str(row["id"]): row for row in (await db.execute(statement, {"ids": ids})).mappings().all()}
    candidates = []
    record_count = 0
    for member in members:
        if keyword_ids is not None and member["vector_id"] not in keyword_ids:
            continue
        year = member["snapshot_json"].get("year")
        if ((year_min is not None or year_max is not None) and (type(year) is not int
                or year_min is not None and year < year_min or year_max is not None and year > year_max)):
            continue
        parent = parents.get(member["evidence_revision_id"])
        if parent is None:
            continue
        if (parent["evidence_intact"] is not True or parent["parent_intact"] is not True
                or parent["paper_id"] != member["paper_id"] or parent["evidence_hash"] != member["evidence_record_sha256"]):
            raise ValueError("Scientific extraction identity cannot be verified")
        records = member["snapshot_json"].get("materials_mentioned")
        if type(records) is not list:
            raise ValueError("Scientific extraction record inventory is malformed")
        record_count += len(records)
        if record_count > MAX_RECORDS:
            raise ValueError("Scientific extraction record inventory exceeds its bound")
        for result in select_record_results(records, interpretation, scope_id=member["paper_id"], filters=filters):
            record = records[result.record_index]
            if input_record_sha256(record) != parent["input_record_sha256"]:
                continue  # associated with this paper, but not this exact parent
            candidates.append((member, parent, result))
    if sort == "date":
        candidates.sort(key=lambda item: (item[0]["paper_snapshot_json"].get("date_submitted")
            or item[0]["paper_snapshot_json"].get("date_published") or ""), reverse=True)
    elif sort == "tc":
        # Only exact, non-approximate points have a point sort key. Censored,
        # interval and missing quantities remain unsorted at the end, not maxima.
        candidates.sort(key=lambda item: (item[2].tc.value if item[2].tc.status == "parsed"
            and item[2].tc.relation == "exact" and not item[2].tc.approximate
            and item[2].tc.uncertainty is None else -1), reverse=True)
    chunks = await index_retrieval.hydrate(db, pin, [item[0]["vector_id"] for item in candidates])
    rows = list(chunks.values())
    evidence = await index_retrieval.resolve_evidence(db, rows)
    # Reuse the exact post-generation material budget before hydrating any
    # linked catalogue payload, not just an IN-clause limit on its IDs.
    linked = await retrieval_currentness._bounded_materials(db, [chunk.materials_mentioned for chunk in rows])
    statuses = await resolve_paper_lifecycle(db, {chunk.paper_id for chunk in rows})
    results, selected = [], []
    eligible_count = 0
    seen_parents = set()
    for member, parent, result in candidates:
        chunk = chunks.get(member["vector_id"])
        descriptor = evidence.get(member["vector_id"])
        if chunk is None or descriptor is None:
            raise ValueError("Scientific lookup selected input is unavailable")
        status = statuses.get(chunk.paper_id)
        if (descriptor["permission_status"] == "restricted" or descriptor["currentness"] == "stale"
                or not source_visibility(status)["reported_claim_filter_eligible"]):
            continue
        if (descriptor["parent_result_revision_id"] != str(parent["parent_extraction_revision_id"])
                or descriptor["parent_result_sha256"] != parent["parent_hash"]):
            raise ValueError("Scientific extraction parent binding changed")
        occurrences, summary = project_source_occurrences(chunk.materials_mentioned,
            paper_status=status, linked_materials=linked, container_paper_id=chunk.paper_id)
        record = chunk.materials_mentioned[result.record_index]
        if input_record_sha256(record) != parent["input_record_sha256"]:
            raise ValueError("Scientific extraction raw parent changed during preparation")
        result_visibility = occurrence_visibility(record, paper_status=status, container_paper_id=chunk.paper_id,
            linked_visibility=linked.get(record.get("material_id")) if type(record.get("material_id")) is str else None)
        if not result_visibility["reported_claim_filter_eligible"]:
            continue
        key = str(parent["parent_extraction_revision_id"])
        if key in seen_parents:
            continue
        # An ineligible rendering must not consume a valid alternative's
        # parent identity. Count only unique, individually admitted parents.
        seen_parents.add(key)
        eligible_count += 1
        if len(results) >= limit:
            continue
        visibility = source_visibility(status)
        visibility["warning_codes"] = sorted(set(visibility["warning_codes"] + summary["warning_codes"]))
        selected.append((member, parent, result, chunk, descriptor, occurrences, visibility, record))
        results.append(LinkedScientificResult(result=result, binding=ScientificResultBinding(
            paper_id=chunk.paper_id, vector_id=chunk.id, generation_id=pin["generation_id"],
            activation_event_id=pin["activation_event_id"], manifest_sha256=pin["manifest_sha256"],
            content_sha256=member["content_sha256"], evidence_revision_id=descriptor["evidence_revision_id"],
            evidence_record_sha256=descriptor["evidence_record_sha256"],
            parent_result_revision_id=descriptor["parent_result_revision_id"],
            parent_result_sha256=descriptor["parent_result_sha256"])))
    grouping = await resolve_grouping_bindings(db, {chunk.paper_id for _, _, _, chunk, *_ in selected})
    prepared_parents = []
    for member, parent, result, chunk, descriptor, occurrences, visibility, record in selected:
        selected_pin = retrieval_currentness.selection_pin(chunk, material_evidence=occurrences,
            source_review=visibility, evidence=descriptor, grouping_binding=grouping[chunk.paper_id])
        prepared_parents.append(PreparedScientificParent(
            result_id=result.result_id, record_index=result.record_index,
            parent_result_revision_id=str(parent["parent_extraction_revision_id"]), paper_id=chunk.paper_id,
            vector_id=chunk.id, source_snapshot_sha256=member["source_snapshot_sha256"],
            input_record_sha256=parent["input_record_sha256"], selection_pin=selected_pin,
            _raw_record_json=_json(record), _member_json=_json({key: value for key, value in member.items()
                                                           if key != "vector_bytes"})))
    reasons = ["derived_extractions_not_independent_scientific_support"]
    if keyword_ids is not None:
        reasons.append("remaining_keywords_are_generation_fulltext_conditions")
    if interpretation.intent in {"mixed", "mechanism"}:
        reasons.append("explanatory_synthesis_not_performed")
    if filters is not None and filters.include_unknown_pressure and (filters.ambient_only
            or filters.pressure_min is not None or filters.pressure_max is not None):
        reasons.append("unknown_pressure_cannot_prove_requested_pressure")
    return _prepared(LookupResult(results, ScientificLookupStatus(status="completed", returned_count=len(results),
        has_more=eligible_count > len(results), reason_codes=reasons)), pin, prepared_parents)


async def lookup_scientific_results(db, pin, interpretation, *, limit=20, filters=None,
                                    year_min=None, year_max=None, sort="relevance"):
    """Compatibility wrapper: prepare, end read, then fresh-check all results.

    No commit occurs. As before, clarification/missing-generation early returns
    leave the caller's transaction untouched. Preparation exceptions propagate;
    callers must clean up their own session, not retry with a consumed handle.
    """
    prepared = await prepare_scientific_lookup(db, pin, interpretation, limit=limit, filters=filters,
        year_min=year_min, year_max=year_max, sort=sort)
    inputs = prepared.consume()
    outcome = inputs.outcome
    if outcome.status.status != "completed":
        return outcome
    await db.rollback()
    if inputs.selection_pins:
        currentness = await retrieval_currentness.check_selected_sources(inputs.selection_pins,
            evidence_resolver=index_retrieval.resolve_evidence)
        if currentness.status != "unchanged":
            return unavailable(currentness.reason_code or "scientific_lookup_currentness_unavailable")
    await index_retrieval.require_current_pin(db, inputs.generation_pin)
    return outcome


def lookup_answer(outcome):
    if outcome.status.status == "unavailable":
        return "A version-pinned scientific lookup is currently unavailable. No numerical answer or older extraction is supplied."
    if not outcome.results:
        return ("No eligible source-linked extraction matched all interpreted conditions in this index generation. "
                "This does not establish that the material is not superconducting.")
    return ("Matching source-linked extraction records are listed below. They are not independently reviewed scientific results "
            "or original-passage support; check the cited papers and their reported conditions before reuse.")
