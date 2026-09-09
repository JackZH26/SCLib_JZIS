"""POST /ask — grounded retrieval-augmented Q&A.

The pinned hybrid path fuses exact-generation ANN and PostgreSQL full-text
results; no active generation means legacy lexical-only. It packs admitted
snapshots with bounded source diversity and complementary original roles. Source excerpts are
passed to Gemini as explicitly untrusted data with a strict citation contract.
Provider failures degrade to lexical retrieval and an extractive answer.

The shape of `sources` in the response maps 1:1 to the [n] markers
Gemini emits — frontend just hyperlinks each bracket to the paper.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from dataclasses import replace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import get_db
from models.db import ApiKey, AskHistory, Base, User, get_engine
from models.evidence_packing import EvidencePackingSummary, PackingCandidate
from models.history_receipts import HistorySaveDisposition
from models.index_read import generation_read_metadata
from models.rag_input_budget import RagInputBudgetReport
from models.scientific_lookup import ScientificLookupStatus
from models.scientific_mixed import ScientificMixedEvidence
from models.search import AskRequest, AskResponse, AskSource
from routers.deps import Identity, require_identity
from services import (
    answer_evidence,
    auth_service,
    complementary_retrieval,
    evidence_packing,
    index_retrieval,
    index_vector_adapter,
    provider_resilience,
    rag,
    retrieval,
    retrieval_currentness,
    retrieval_groups,
    scientific_mixed,
)
from services.authors import short as _authors_short
from services.metrics import observe_rag
from services.scientific_query import interpret_scientific_query
from services.scientific_query_lookup import (
    lookup_answer,
    prepare_scientific_lookup,
    result_query,
    unavailable,
)
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import (
    citation_evidence,
    project_source_occurrences,
    source_visibility,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])
EVIDENCE_RESOLUTION_TIMEOUT_SECONDS = 10.0


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    request: Request,
    identity: Identity = Depends(require_identity),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> AskResponse:
    t0 = time.perf_counter()
    # The catalogue read transaction is closed before provider generation.
    # Retain primitives, not an ORM User that rollback would expire.
    history_user_id = identity.user.id if identity.user is not None else None

    async def finish(response, captured=None):
        return await _persist_history(db, request, history_user_id, body, response, captured)

    interpretation = interpret_scientific_query(body.question)
    mixed_inputs = None
    original_limit = body.max_sources
    if interpretation.status == "clarification_required":
        answer = ("Please clarify the unresolved scientific conditions before a numerical lookup or synthesis. "
                  + " ".join(interpretation.clarification_questions))
        latency_ms = int((time.perf_counter() - t0) * 1000)
        _observe_lookup_interaction()
        response = AskResponse(answer=answer, sources=[], tokens_used=0,
            query_time_ms=latency_ms,
            citation_indices_valid=True, scientific_query=interpretation,
            scientific_lookup=ScientificLookupStatus(status="clarification_required", reason_codes=["unresolved_query_constraints"]),
            guest_remaining=identity.guest_remaining,
            remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining)
        return await finish(response, _capture_inputs(body, None))

    try:
        async with asyncio.timeout(10):
            pin = await index_retrieval.load_pin(db)
    except Exception:
        raise HTTPException(503, "Retrieval generation is unavailable") from None
    if scientific_mixed.is_mixed_request(interpretation):
        try:
            async with asyncio.timeout(15):
                prepared = await prepare_scientific_lookup(db, pin, interpretation,
                    limit=max(1, body.max_sources // 2))
                mixed_inputs = prepared.consume()
            if mixed_inputs.outcome.status.status != "completed":
                raise ValueError("Mixed numerical lookup is unavailable")
            original_limit = body.max_sources - len(mixed_inputs.outcome.results)
            # Detached private snapshots/pins survive rollback; no numeric read
            # transaction spans a semantic provider call or later context work.
            await db.rollback()
        except Exception:
            await db.rollback()
            return await _mixed_response(db, body, identity, history_user_id, interpretation, pin, t0,
                reason="mixed_lookup_unavailable", finish=finish)
        if original_limit == 0:
            return await _mixed_response(db, body, identity, history_user_id, interpretation, pin, t0,
                inputs=mixed_inputs, finish=finish)
    elif result_query(interpretation):
        captured = None
        try:
            async with asyncio.timeout(15):
                prepared = await prepare_scientific_lookup(db, pin, interpretation, limit=body.max_sources)
                numeric_inputs = prepared.consume()
                outcome = numeric_inputs.outcome
                captured = _capture_inputs(body, pin, scientific_inputs=numeric_inputs)
                if outcome.status.status == "completed":
                    await db.rollback()
                    if numeric_inputs.selection_pins:
                        currentness = await retrieval_currentness.check_selected_sources(
                            numeric_inputs.selection_pins, evidence_resolver=index_retrieval.resolve_evidence)
                        if currentness.status != "unchanged":
                            outcome = unavailable(currentness.reason_code or "scientific_lookup_currentness_unavailable")
                    if outcome.status.status == "completed":
                        await index_retrieval.require_current_pin(db, numeric_inputs.generation_pin)
        except Exception:
            await db.rollback()
            outcome = unavailable("scientific_lookup_unavailable")
        answer = lookup_answer(outcome)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        _observe_lookup_interaction()
        response = AskResponse(answer=answer, sources=[], tokens_used=0,
            query_time_ms=latency_ms, citation_indices_valid=True,
            support_warnings=["structured_extractions_not_scientific_validation"],
            guest_remaining=identity.guest_remaining,
            remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
            retrieval_generation=generation_read_metadata(pin), scientific_query=interpretation,
            scientific_lookup=outcome.status, scientific_results=outcome.results)
        return await finish(response, captured or _capture_inputs(body, pin))
    settings = get_settings()
    vector_hits = []
    if pin is not None:
        try:
            neighbors = await provider_resilience.run_blocking(
                "vector_search", lambda: index_vector_adapter.query(pin, body.question,
                    top_k=min(body.max_sources * 4, 80)),
                timeout_seconds=settings.vector_search_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
                failure_threshold=settings.provider_circuit_failure_threshold,
                cooldown_seconds=settings.provider_circuit_cooldown_seconds,
            )
            async with asyncio.timeout(10):
                vector_hits = await index_retrieval.verified_vector_hits(db, pin, neighbors)
        except Exception:
            log.warning("Ask semantic retrieval unavailable; using generation-scoped lexical fallback")
            await db.rollback()

    candidate_limit = min(body.max_sources * 5, 100)
    try:
        async with asyncio.timeout(15):
            lexical_hits = await retrieval.lexical_search(
                db,
                interpretation.normalized_query,
                limit=candidate_limit,
                generation_id=pin["generation_id"] if pin is not None else None,
            )
            formula_hits = await retrieval.formula_lexical_search(db, interpretation, pin, limit=candidate_limit)
        lexical_hits = retrieval.combine_lexical_hits(formula_hits, lexical_hits, limit=candidate_limit)
    except Exception:
        if mixed_inputs is not None:
            await db.rollback()
            return await _mixed_response(db, body, identity, history_user_id, interpretation, pin, t0,
                reason="mixed_context_unavailable", finish=finish)
        raise HTTPException(503, "Lexical/formula-aware retrieval is unavailable") from None
    candidates = retrieval.fuse_rankings(
        vector_hits,
        lexical_hits,
        limit=candidate_limit,
    )
    if not candidates:
        if mixed_inputs is not None:
            return await _mixed_response(db, body, identity, history_user_id, interpretation, pin, t0,
                inputs=mixed_inputs, finish=finish)
        if pin is not None:
            try:
                async with asyncio.timeout(10):
                    await index_retrieval.require_current_pin(db, pin)
            except Exception:
                raise HTTPException(503, "Retrieval generation changed; please ask again") from None
        latency_ms = int((time.perf_counter() - t0) * 1000)
        result = rag.no_source_result()
        observe_rag(
            sources=0, tokens=0, citation_valid=result.citation_valid, fallback=False,
            citation_indices_valid=result.citation_indices_valid,
            scientific_support_status=result.scientific_support_status, answer_mode=result.answer_mode,
        )
        response = AskResponse(
            answer=result.answer,
            sources=[],
            tokens_used=0,
            query_time_ms=latency_ms,
            **result.quality_fields(),
            guest_remaining=identity.guest_remaining,
            remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
            retrieval_generation=generation_read_metadata(pin),
            scientific_query=interpretation,
        )
        return await finish(response, _capture_inputs(body, pin))

    # Hydrate exact immutable members, never resolve opaque ANN IDs through
    # mutable Chunk positions. Legacy lexical rows use their separate path.
    MAX_IN_CLAUSE = 100
    candidates = candidates[:MAX_IN_CLAUSE]
    chunk_ids = [candidate.chunk_id for candidate in candidates]
    try:
        async with asyncio.timeout(10):
            chunk_by_id = await index_retrieval.hydrate(db, pin, chunk_ids)
    except Exception:
        if mixed_inputs is not None:
            await db.rollback()
            return await _mixed_response(db, body, identity, history_user_id, interpretation, pin, t0,
                reason="mixed_context_unavailable", finish=finish)
        raise HTTPException(503, "Retrieval generation is unavailable") from None
    candidates = retrieval.rerank_candidates(body.question, candidates, chunk_by_id)
    evidence_failure_reason = None
    try:
        async with asyncio.timeout(15):
            candidates = await complementary_retrieval.expand_candidates(db, pin, candidates, chunk_by_id)
            # Rehydrate the whole bounded inventory, not one unchecked extra
            # set whose combined byte count could exceed the hydration budget.
            chunk_by_id = await index_retrieval.hydrate(db, pin, [item.chunk_id for item in candidates])
            rows = list(chunk_by_id.values())
            groups = [chunk.materials_mentioned for chunk in rows]
            if any(type(group) is not list for group in groups) or sum(map(len, groups)) > 5000:
                raise retrieval_currentness.CurrentnessUnavailable("candidate occurrence inventory")
            linked_materials = await retrieval_currentness._bounded_materials(db, groups)
            source_statuses = await resolve_paper_lifecycle(db, {chunk.paper_id for chunk in rows})
            grouping_bindings = await retrieval_groups.resolve_grouping_bindings(db, [chunk.paper_id for chunk in rows])
        evidence_by_chunk = await _resolve_evidence(db, rows)
    except TimeoutError:
        log.warning("Ask typed evidence resolution timed out; selected text withheld")
        evidence_by_chunk = None
        evidence_failure_reason = "retrieval_currentness_timeout"
    except Exception:  # no raw error/source payload reaches the answer
        log.warning("Ask typed evidence resolution unavailable; selected text withheld")
        evidence_by_chunk = None
        evidence_failure_reason = "retrieval_currentness_unavailable"

    rag_inputs: list[rag.RagSourceInput] = []
    sources_out: list[AskSource] = []
    selected_pins: list[retrieval_currentness.SelectionPin] = []
    frozen_originals = ()
    captured = None
    pin_unavailable = evidence_by_chunk is None
    admitted, input_by_id, output_by_id, pins_by_id = [], {}, {}, {}
    packing_summary = EvidencePackingSummary(status="unavailable", reason_codes=["packing_unavailable"])
    for candidate in candidates:
        if pin_unavailable:
            break
        chunk = chunk_by_id.get(candidate.chunk_id)
        if chunk is None or chunk.paper is None:
            continue
        evidence = evidence_by_chunk[chunk.id]
        if interpretation.intent in {"mechanism", "comparison", "mixed"} and evidence["chunk_kind"] != "original_passage":
            continue  # derived numerical Facts are not original explanatory passages
        # Never send or quote a known-restricted/stale evidence projection.
        # Other unresolved lineage is navigation data, not original support.
        if evidence["permission_status"] == "restricted" or evidence["currentness"] == "stale":
            continue
        paper_status = source_statuses.get(chunk.paper.id)
        if not source_visibility(paper_status)["reported_claim_filter_eligible"]:
            continue
        paper = index_retrieval.attribution(chunk)
        authors_short = _authors_short(paper.authors or [])
        year = paper.date_submitted.year if paper.date_submitted else None
        occurrences, occurrence_summary = project_source_occurrences(
            chunk.materials_mentioned, paper_status=paper_status, linked_materials=linked_materials, container_paper_id=chunk.paper_id,
        )
        source_review = source_visibility(paper_status)
        source_review["warning_codes"] = sorted(set(source_review["warning_codes"] + occurrence_summary["warning_codes"]))
        try:
            pins_by_id[chunk.id] = retrieval_currentness.selection_pin(
                chunk, material_evidence=occurrences, source_review=source_review, evidence=evidence,
                grouping_binding=grouping_bindings[chunk.paper_id],
            )
            admitted.append(PackingCandidate(chunk_id=chunk.id, paper_id=chunk.paper_id,
                source_snapshot_sha256=(chunk.member["source_snapshot_sha256"]
                    if isinstance(chunk, index_retrieval.GenerationChunk) else None),
                accepted_work_id=grouping_bindings[chunk.paper_id].accepted_work_id,
                content_sha256=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                chunk_kind=evidence["chunk_kind"],
                role_hint=complementary_retrieval.role_hint(chunk.section, chunk.has_table)))
        except retrieval_currentness.CurrentnessUnavailable:
            pin_unavailable = True
            break
        input_by_id[chunk.id] = rag.RagSourceInput(
                index=1,  # assigned only by the final ordered packing plan
                paper_id=paper.id,
                title=paper.title,
                authors_short=authors_short,
                year=year,
                section=chunk.section,
                text=chunk.text,
                material_evidence=occurrences,
                source_visibility=source_review,
                visibility_resolved=True,
                evidence_provenance=evidence,
                source_snapshot_sha256=(chunk.member["source_snapshot_sha256"]
                    if isinstance(chunk, index_retrieval.GenerationChunk) else None),
        )
        output_by_id[chunk.id] = AskSource(
                index=1,
                paper_id=paper.id,
                arxiv_id=paper.arxiv_id,
                title=paper.title,
                authors_short=authors_short,
                year=year,
                section=chunk.section,
                snippet=_snippet(chunk.text),
                material_evidence=citation_evidence(occurrences, visibility_resolved=True),
                source_visibility=source_review,
                evidence_provenance=evidence,
        )

    if not pin_unavailable:
        try:
            def trial_inputs(ordered_ids):
                return [replace(input_by_id[item.chunk_id], index=item.position, packing_info=item)
                    for item in evidence_packing.describe_selection(admitted, ordered_ids)]

            plan = evidence_packing.pack_evidence(admitted,
                cost=lambda ids: rag.measure_input_bytes(body.question, trial_inputs(ids), language=body.language),
                byte_budget=settings.gemini_input_byte_limit, max_chunks=original_limit)
            packing_summary = evidence_packing.public_summary(plan)
            rag_inputs = trial_inputs(tuple(item.chunk_id for item in plan.selected))
            sources_out = [AskSource.model_validate({**output_by_id[item.chunk_id].model_dump(),
                "index": item.position, "packing_info": item.model_dump()}) for item in plan.selected]
            selected_pins = [pins_by_id[item.chunk_id] for item in plan.selected]
            if mixed_inputs is not None:
                frozen_originals = tuple(scientific_mixed.freeze_original(source, selected_pin)
                    for source, selected_pin in zip(sources_out, selected_pins, strict=True))
            captured = _capture_inputs(body, pin, sources=tuple(sources_out),
                chunks=tuple(chunk_by_id[item.chunk_id] for item in plan.selected),
                selection_pins=tuple(selected_pins), scientific_inputs=mixed_inputs)
        except Exception:
            log.warning("Ask complete evidence packing unavailable; selected context withheld")
            pin_unavailable = True
            evidence_failure_reason = "evidence_packing_unavailable"

    # Empty/byte-rejected plans have no selected-source recheck below, but
    # must not publish stale generation accounting after an activation change.
    if not rag_inputs and not pin_unavailable and pin is not None:
        try:
            async with asyncio.timeout(10):
                await index_retrieval.require_current_pin(db, pin)
        except Exception:
            pin_unavailable = True
            evidence_failure_reason = "retrieval_generation_changed"

    # No transaction, snapshot or table locks span a potentially slow provider
    # call. API-key accounting has already committed in require_identity.
    await db.rollback()
    if pin_unavailable:
        rag_inputs, sources_out, selected_pins = [], [], []
        frozen_originals = ()

    if mixed_inputs is not None:
        # A mixed query reaches BOTH real retrieval paths, but no current
        # catalogue relation establishes a scientific numerical explanation.
        # Do not ask Gemini to invent that missing association. One final fresh
        # snapshot checks numeric parents and original context as a single unit.
        return await _mixed_response(db, body, identity, history_user_id, interpretation, pin, t0,
            inputs=mixed_inputs, originals=frozen_originals, packing=packing_summary,
            reason=(evidence_failure_reason or "mixed_context_unavailable") if pin_unavailable else None,
            finish=finish, captured=captured)

    # 3. One count+generation attempt behind the outer deadline. A late count
    # must not start generation after the await has timed out or been cancelled.
    stop_event = threading.Event()
    # A provider outage
    # degrades to cited excerpts instead of turning the whole endpoint into 5xx.
    try:
        if not rag_inputs:
            result = rag.no_source_result(evidence_packing=packing_summary)
        else:
            result = await provider_resilience.run_blocking(
                "gemini_generation",
                lambda: rag.generate_answer(
                    body.question,
                    rag_inputs,
                    language=body.language,
                    evidence_packing=packing_summary,
                    stop_event=stop_event,
                ),
                timeout_seconds=settings.gemini_timeout_seconds,
                max_attempts=1,
                result_status=rag.provider_status,
                failure_threshold=settings.provider_circuit_failure_threshold,
                cooldown_seconds=settings.provider_circuit_cooldown_seconds,
            )
    except provider_resilience.ProviderUnavailable as exc:
        stop_event.set()
        log.warning("Gemini generation unavailable; returning extractive fallback: %s", exc)
        if isinstance(exc.__cause__, rag.RagProviderFailure):
            # Recover the already sealed fallback only after the outer
            # provider boundary records failure. Do not discard its count or
            # relabel the old fallback as a new generated scientific draft.
            result = exc.__cause__.result
        else:
            result = rag.extractive_fallback(rag_inputs, evidence_packing=packing_summary,
                input_budget=RagInputBudgetReport(status="unavailable", generation_started=None,
                    byte_limit=settings.gemini_input_byte_limit), tokens_used=None)
    except asyncio.CancelledError:
        stop_event.set()
        raise

    # A seal only checks in-memory consistency. Re-read selected catalogue
    # inputs in a new bounded snapshot before accepting that provisional seal.
    currentness = (await retrieval_currentness.check_selected_sources(selected_pins, evidence_resolver=_resolve_evidence)
                   if rag_inputs else None)
    if pin_unavailable or currentness is not None and currentness.status != "unchanged":
        reason = (currentness.reason_code if currentness is not None
                  else evidence_failure_reason or "retrieval_currentness_unavailable")
        tokens_used = result.tokens_used if isinstance(result, rag.RagResult) else None
        # Never pass an already replaced fallback through the draft checker
        # again. No old excerpt, source label, or draft assessment is retained.
        result = _currentness_abstention(reason, tokens_used,
            input_budget=result.input_budget if isinstance(result, rag.RagResult) else None)
        rag_inputs, sources_out = [], []
    else:
        # Alternate/legacy generators still cannot bypass server checks. Stable
        # sources preserve the existing seal and original draft assessment.
        result = rag.finalize_result(result, rag_inputs, evidence_packing=packing_summary)

    retrieval_modes = sorted(
        {mode for candidate in candidates for mode in candidate.retrieval_modes}
    )
    log.info(
        "rag_quality sources=%d papers=%d retrieval=%s citation_valid=%s warnings=%s indices_valid=%s support=%s mode=%s",
        len(rag_inputs),
        len({source.paper_id for source in rag_inputs}),
        "+".join(retrieval_modes) or "none",
        result.citation_valid,
        ",".join(result.citation_warnings) or "none",
        result.citation_indices_valid,
        result.scientific_support_status,
        result.answer_mode,
    )
    observe_rag(
        sources=len(rag_inputs),
        tokens=result.tokens_used,
        citation_valid=result.citation_valid,
        fallback=result.answer_mode == "extractive_fallback",
        citation_indices_valid=result.citation_indices_valid,
        scientific_support_status=result.scientific_support_status,
        answer_mode=result.answer_mode,
    )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    response = AskResponse(
        answer=result.answer,
        sources=sources_out,
        tokens_used=result.tokens_used,
        query_time_ms=latency_ms,
        **result.quality_fields(),
        guest_remaining=identity.guest_remaining,
        remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
        retrieval_generation=generation_read_metadata(pin),
        scientific_query=interpretation,
    )
    return await finish(response, captured or _capture_inputs(body, pin))


async def _resolve_evidence(db, chunks):
    """One strict resolver path for initial hydration and the fresh snapshot."""
    from services.rag_evidence_contract import validate_evidence_descriptor

    async with asyncio.timeout(EVIDENCE_RESOLUTION_TIMEOUT_SECONDS):
        resolved = await index_retrieval.resolve_evidence(db, chunks)
        if not isinstance(resolved, dict) or set(resolved) != {chunk.id for chunk in chunks}:
            raise retrieval_currentness.CurrentnessUnavailable("incomplete typed evidence inventory")
        return {identifier: validate_evidence_descriptor(value) for identifier, value in resolved.items()}


async def _mixed_response(db, body, identity, history_user_id, interpretation, pin, t0, *,
                          inputs=None, originals=(), packing=None, reason=None, finish=None, captured=None):
    """Publish both current inventories together, or withdraw both without a draft."""
    await db.rollback()
    report = None
    sources = []
    if reason is None:
        try:
            if type(originals) is not tuple or any(type(item) is not scientific_mixed.FrozenMixedOriginal for item in originals):
                raise ValueError("Frozen mixed original inputs are required")
            sources = [item.source for item in originals]
            original_pins = tuple(item.selection_pin for item in originals)
            pins = scientific_mixed.combined_pins(inputs, original_pins, max_selected_inputs=body.max_sources)
            if len(original_pins) != len(sources) or any(source.packing_info is None
                    or source.packing_info.chunk_id != original_pin.chunk_id or source.paper_id != original_pin.paper_id
                    for source, original_pin in zip(sources, original_pins, strict=True)):
                raise ValueError("Incomplete original citation pin inventory")
            report = scientific_mixed.resolve_mixed_associations(inputs, sources,
                max_selected_inputs=body.max_sources)
            if pins:
                check = await retrieval_currentness.check_selected_sources(pins, evidence_resolver=_resolve_evidence)
                if check.status != "unchanged":
                    reason = check.reason_code or "mixed_currentness_unavailable"
            else:
                async with asyncio.timeout(10):
                    await index_retrieval.require_current_pin(db, pin)
        except Exception:
            reason = "mixed_currentness_unavailable"
    if reason is not None:
        # Reason values from lower-level boundaries stay inside the public
        # closed inventory; neither raw errors nor prior inputs are returned.
        try:
            report = ScientificMixedEvidence(status="unavailable", max_selected_inputs=body.max_sources,
                reason_codes=[reason])
        except ValueError:
            report = ScientificMixedEvidence(status="unavailable", max_selected_inputs=body.max_sources,
                reason_codes=["mixed_currentness_unavailable"])
        sources = []
        outcome = unavailable("mixed_retrieval_withheld")
        packing = EvidencePackingSummary(status="withheld", reason_codes=["selected_context_withheld"])
    else:
        outcome = inputs.outcome
    answer = scientific_mixed.mixed_answer(report)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    observe_rag(sources=len(sources), tokens=0, citation_valid=False, fallback=False,
        citation_indices_valid=True, scientific_support_status="not_checked", answer_mode="abstention")
    response = AskResponse(answer=answer, sources=list(sources), tokens_used=0, query_time_ms=latency_ms,
        citation_indices_valid=True, scientific_query=interpretation, scientific_lookup=outcome.status,
        scientific_results=outcome.results, scientific_mixed=report,
        support_warnings=["numerical_explanation_not_established", "structured_extractions_not_scientific_validation"]
            if report.status == "completed" else list(report.reason_codes),
        evidence_packing=packing or EvidencePackingSummary(),
        retrieval_generation=generation_read_metadata(pin), guest_remaining=identity.guest_remaining,
        remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining)
    if captured is None:
        captured = _capture_inputs(body, pin, scientific_inputs=inputs if reason is None and not sources else None)
    if finish is None:
        # Internal direct calls have no authenticated request authority to save.
        return response
    return await finish(response, captured)


def _currentness_abstention(reason: str, tokens_used: int | None, *, input_budget=None) -> rag.RagResult:
    return rag.RagResult(
        answer="The selected evidence changed or could not be checked. "
               "No synthesized answer or old excerpt is provided. Please ask again to retrieve current sources.",
        tokens_used=tokens_used, citation_valid=False, citation_warnings=[reason],
        citation_indices_valid=True, support_warnings=[reason],
        answer_mode="abstention", assessment_scope="none",
        evidence_packing=EvidencePackingSummary(status="withheld", reason_codes=["selected_context_withheld"]),
        input_budget=input_budget or RagInputBudgetReport(),
    )


def _capture_inputs(body, pin, *, sources=(), chunks=(), selection_pins=(), scientific_inputs=None):
    """Detach admitted input references before ORM rollback or provider work."""
    try:
        return answer_evidence.capture_inputs(request=body, generation_pin=pin,
            sources=sources, chunks=chunks, selection_pins=selection_pins,
            scientific_inputs=scientific_inputs)
    except Exception:
        log.warning("Answer history input capture unavailable; no unbound saved receipt will be created")
        return None


_HISTORY_SLOTS = threading.BoundedSemaphore(2)


async def _history_actor(request, session, expected_user_id):
    """Recheck the original auth path without consuming another quota slot."""
    key = request.headers.get("x-api-key")
    if key:
        user_id = await session.scalar(select(ApiKey.user_id).where(
            ApiKey.key_hash == auth_service.hash_api_key(key), ApiKey.revoked.is_(False)))
        if user_id != expected_user_id:
            return False
        user = await session.get(User, user_id)
        return user is not None and user.is_active
    from routers.deps import _resolve_jwt_user
    user = await _resolve_jwt_user(request, session)
    return user is not None and user.id == expected_user_id


async def _persist_history(db, request, user_id, body, response, captured):
    """Save only the final response, atomically with its immutable evidence.

    The answer remains usable if saving fails. A commit whose acknowledgement
    is lost yields its original recovery ID, never an asserted successful save
    or an automatic second write. No ORM identity survives the provider await.
    """
    if type(response) is not AskResponse:
        raise TypeError("History can retain only a validated final Ask response")
    try:
        await db.rollback()
    except Exception:
        disposition = HistorySaveDisposition(status="not_saved", reason_code="storage_unavailable")
        return response.model_copy(update={"history": disposition})
    if user_id is None:
        return response.model_copy(update={"history": HistorySaveDisposition(reason_code="guest_request")})
    try:
        prepared = answer_evidence.finish_capture(captured, response)
    except Exception:
        return response.model_copy(update={"history": HistorySaveDisposition(
            status="not_saved", reason_code="capture_unavailable")})
    if not _HISTORY_SLOTS.acquire(blocking=False):
        return response.model_copy(update={"history": HistorySaveDisposition(
            status="not_saved", reason_code="storage_unavailable")})
    history_id, commit_started = uuid4(), False
    try:
        async with asyncio.timeout(10):
            async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as session:
                await session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                await session.execute(text("SET LOCAL statement_timeout='5000ms'"))
                if not await _history_actor(request, session, user_id):
                    return response.model_copy(update={"history": HistorySaveDisposition(
                        status="not_saved", reason_code="session_no_longer_authorized")})
                fields = await answer_evidence.receipt_fields(session, prepared)
                fields = {**fields,
                    "generation_id": UUID(fields["generation_id"]) if fields["generation_id"] else None,
                    "activation_event_id": UUID(fields["activation_event_id"]) if fields["activation_event_id"] else None}
                session.add(AskHistory(id=history_id, user_id=user_id,
                    question=body.question, answer=response.answer,
                    sources=[source.model_dump(mode="json") for source in response.sources],
                    tokens_used=response.tokens_used, latency_ms=response.query_time_ms, language=body.language,
                    evidence_receipt_version="ask-answer-evidence/1.0.0"))
                await session.flush()
                stored = (await session.execute(insert(Base.metadata.tables["answer_evidence_receipts"])
                    .values(history_id=history_id, **fields).returning(
                        Base.metadata.tables["answer_evidence_receipts"].c.record_sha256))).scalar_one()
                # Deferred parent/receipt completeness is checked by this real
                # outer commit. A flush or savepoint is not successful saving.
                commit_started = True
                await session.commit()
        disposition = HistorySaveDisposition(status="saved", history_id=str(history_id), receipt_sha256=stored)
    except Exception:
        log.warning("Answer history persistence unavailable; private database details withheld")
        disposition = (HistorySaveDisposition(status="unknown", history_id=str(history_id), reason_code="commit_unconfirmed")
            if commit_started else HistorySaveDisposition(status="not_saved", reason_code="storage_unavailable"))
    finally:
        _HISTORY_SLOTS.release()
    return response.model_copy(update={"history": disposition})


def _observe_lookup_interaction():
    observe_rag(sources=0, tokens=0, citation_valid=False, fallback=False,
        citation_indices_valid=True, scientific_support_status="not_checked", answer_mode="abstention")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snippet(text: str, max_chars: int = 280) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
