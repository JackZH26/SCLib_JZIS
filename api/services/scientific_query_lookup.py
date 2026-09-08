"""Provider-free, generation-scoped exact extraction lookup with live holds.

Original chunks can carry all paper-level material extractions. They must never
be mistaken for original support of an arbitrary record in that list. This
lookup only reports records whose full input hash equals their verified 0060
derived-Fact parent, with an explicit non-approval association scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from models.scientific_lookup import (
    LinkedScientificResult,
    ScientificLookupStatus,
    ScientificResultBinding,
)
from services import index_generations, index_retrieval, retrieval_currentness
from services.rag_evidence_contract import input_record_sha256
from services.scientific_query_results import select_record_results
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import (
    occurrence_visibility,
    project_source_occurrences,
    source_visibility,
)

MAX_RESULTS = 20
MAX_RECORDS = 5000


@dataclass(frozen=True)
class LookupResult:
    results: list[LinkedScientificResult]
    status: ScientificLookupStatus


def result_query(interpretation):
    return (bool(interpretation.evidence_constraints) or interpretation.intent == "numerical"
            or interpretation.intent in {"mixed", "comparison"} and bool(interpretation.requested_fields
                or interpretation.constraints or interpretation.evidence_constraints))


def unavailable(reason):
    return LookupResult([], ScientificLookupStatus(status="unavailable", reason_codes=[reason]))


async def lookup_scientific_results(db, pin, interpretation, *, limit=20, filters=None,
                                    year_min=None, year_max=None, sort="relevance"):
    """Only exact complete-parent matches; no provider work or outer commit.

    The request database read transaction is rolled back before the final fresh
    selected-input check, matching existing Ask currentness semantics. Caller
    must not pass unrelated pending writes into this read-only operation.
    """
    if (db.new or db.dirty or db.deleted or type(limit) is not int or not 1 <= limit <= MAX_RESULTS
            or sort not in {"relevance", "date", "tc"}):
        raise ValueError("A clean session and bounded result count are required")
    if interpretation.status != "resolved":
        return LookupResult([], ScientificLookupStatus(status="clarification_required",
            reason_codes=["unresolved_query_constraints"]))
    if pin is None:
        return unavailable("active_generation_required")
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
    results, selected_pins = [], []
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
            paper_status=status, linked_materials=linked)
        record = chunk.materials_mentioned[result.record_index]
        result_visibility = occurrence_visibility(record, paper_status=status,
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
        selected_pins.append(retrieval_currentness.selection_pin(chunk, material_evidence=occurrences,
            source_review=visibility, evidence=descriptor))
        results.append(LinkedScientificResult(result=result, binding=ScientificResultBinding(
            paper_id=chunk.paper_id, vector_id=chunk.id, generation_id=pin["generation_id"],
            activation_event_id=pin["activation_event_id"], manifest_sha256=pin["manifest_sha256"],
            content_sha256=member["content_sha256"], evidence_revision_id=descriptor["evidence_revision_id"],
            evidence_record_sha256=descriptor["evidence_record_sha256"],
            parent_result_revision_id=descriptor["parent_result_revision_id"],
            parent_result_sha256=descriptor["parent_result_sha256"])))
    await db.rollback()
    if selected_pins:
        currentness = await retrieval_currentness.check_selected_sources(selected_pins,
            evidence_resolver=index_retrieval.resolve_evidence)
        if currentness.status != "unchanged":
            return unavailable(currentness.reason_code or "scientific_lookup_currentness_unavailable")
    await index_retrieval.require_current_pin(db, pin)
    reasons = ["derived_extractions_not_independent_scientific_support"]
    if keyword_ids is not None:
        reasons.append("remaining_keywords_are_generation_fulltext_conditions")
    if interpretation.intent in {"mixed", "mechanism"}:
        reasons.append("explanatory_synthesis_not_performed")
    if filters is not None and filters.include_unknown_pressure and (filters.ambient_only
            or filters.pressure_min is not None or filters.pressure_max is not None):
        reasons.append("unknown_pressure_cannot_prove_requested_pressure")
    return LookupResult(results, ScientificLookupStatus(status="completed", returned_count=len(results),
        has_more=eligible_count > len(results), reason_codes=reasons))


def lookup_answer(outcome):
    if outcome.status.status == "unavailable":
        return "A version-pinned scientific lookup is currently unavailable. No numerical answer or older extraction is supplied."
    if not outcome.results:
        return ("No eligible source-linked extraction matched all interpreted conditions in this index generation. "
                "This does not establish that the material is not superconducting.")
    return ("Matching source-linked extraction records are listed below. They are not independently reviewed scientific results "
            "or original-passage support; check the cited papers and their reported conditions before reuse.")
