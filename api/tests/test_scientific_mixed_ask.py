"""Actual SQL + HTTP mixed retrieval, not numerical/explanatory synthesis.

Synthetic papers deliberately contain distinct specimens and conditions, and
original chunks carry the entire paper extraction list. Shared catalogue
membership must never establish an experimental or causal result/passage link.
All cloud clients are forbidden; vector search uses the disposable adapter.
"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from models.db import AskHistory, Paper, PaperWorkMap, Work, get_session_factory
from models.search import AskResponse
from routers import ask as ask_router
from services import (
    index_generations,
    index_vector_adapter,
    provider_resilience,
    rag,
    retrieval_currentness,
)
from services.scientific_query import interpret_scientific_query
from tests.index_generation_fixtures import RESOURCE, prepare_generation_items, publish_and_activate

AMBIENT_MIXED = "What is Tc of MgB2 at ambient pressure and why?"


def _records():
    def record(formula, tc, pressure, sample, phase, **extra):
        return {"formula": formula, "tc_kelvin": tc, "pressure": pressure, "sample_label": sample,
            "structure_phase": phase, "knowledge_origin": "Observed", "source_role": "primary",
            "extractor_version": "synthetic-mixed-extractor/1", "measurement_method": "resistance", **extra}
    return [record("MgB2", "39 K", "ambient pressure", "specimen A", "synthetic-phase-A"),
            record("MgB2", "20 K", "150 GPa", "specimen B", "synthetic-phase-B"),
            record("MgB2", "18 K", None, "specimen U", "synthetic-phase-U"),
            record("Nb", None, None, "specimen N", "synthetic-phase-N",
                   result_status="not_detected", minimum_temperature_k="1 K")]


def _forbid_generation(monkeypatch):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append("unexpected_generation_or_cloud_client")
        raise AssertionError("Mixed retrieval must not call Gemini, CountTokens or a cloud client")
    monkeypatch.setattr(rag, "genai_client", forbidden)
    monkeypatch.setattr(rag, "generate_answer", forbidden)
    monkeypatch.setattr(index_vector_adapter, "_public_clients", forbidden)
    return calls


async def _stage_mixed(monkeypatch, logical, *, meta=None, label="retained"):
    from ingestion.chunk.chunker import count_tokens
    from ingestion.embedding_contract import (
        LOCAL_DOCUMENT_COUNT_METHOD,
        LOCAL_DOCUMENT_INPUT_LIMIT,
        LOCAL_DOCUMENT_REQUEST_LIMIT,
        validate_embedding_response,
    )
    from ingestion.extract.fact_sentences import build_fact_chunks
    from ingestion.index import indexer
    from ingestion.models import ApsArticleMeta, Chunk

    meta = meta or ApsArticleMeta(doi="10.0000/MixedAsk." + uuid4().hex,
        title="Synthetic distinct superconductivity specimens", authors=["Synthetic Fixture"],
        abstract="Synthetic catalogue only; no real superconductivity claim.", date_published=date(2024, 1, 1))
    records = _records()
    chunks = build_fact_chunks(meta, records, start_index=0)
    assert len(chunks) == 4
    originals = [
        ("Results", "MgB2 specimen A in synthetic-phase-A has a reported Tc of 39 K at ambient pressure. Pairing explanation remains unresolved."),
        ("Methods", "MgB2 specimen B in synthetic-phase-B was measured at 150 GPa with Tc 20 K. These methods are not an explanation of specimen A."),
        ("Table 1", "MgB2 specimen U in synthetic-phase-U has a reported Tc of 18 K; pressure was not reported. Missing pressure does not establish ambient conditions."),
        ("Discussion", "Nb specimen N showed no detected superconductivity down to 1 K. This is a detection limit, not Tc equal to zero; its mechanism remains unresolved."),
    ]
    for offset, (section, text) in enumerate(originals, len(chunks)):
        text = "Synthetic " + label + " original: " + text
        chunks.append(Chunk(id=f"{meta.paper_id}_original_{offset:03d}", paper_id=meta.paper_id,
            chunk_index=offset, section=section, text=text, token_count=count_tokens(text), has_table=section == "Table 1",
            materials_mentioned=deepcopy(records), parser_version="synthetic-mixed-parser/1",
            evidence_candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage",
                "rendering_version": "sclib-section-chunker/2.0.0",
                "source_locator": {"section": section, "char_start": 0, "char_end": len(text)}}))
    for index, chunk in enumerate(chunks):
        count = count_tokens(chunk.text)
        chunk.token_count, chunk.parser_version = count, "synthetic-mixed-parser/1"
        vector, metadata = validate_embedding_response([chunk.text], SimpleNamespace(embeddings=[SimpleNamespace(
            values=[0.125 + index / 1000] * 768,
            statistics=SimpleNamespace(truncated=False, token_count=float(count)))]),
            model="text-embedding-005", dimension=768, task_type="RETRIEVAL_DOCUMENT", local_counts=[count],
            local_count_method=LOCAL_DOCUMENT_COUNT_METHOD, local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
            local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT)[0]
        chunk.embedding, chunk.embedding_provenance = vector, metadata
    monkeypatch.setattr(indexer, "_session_factory", get_session_factory)
    monkeypatch.setattr(indexer, "_index", lambda: (_ for _ in ()).throw(AssertionError("Unexpected vector cloud write")))
    staged = {}
    async def stager(session, selected):
        staged.update(await index_generations.stage_generation(session, generation_id=str(uuid4()), logical_index=logical,
            resource=RESOURCE, items=await prepare_generation_items(session, selected), dry_run=False))
    await indexer.upsert_aps_paper_with_chunks(meta, chunks, records, generation_stager=stager)
    return meta, chunks, staged


@pytest_asyncio.fixture
async def mixed_generation(monkeypatch):
    logical = "mixed-ask-" + uuid4().hex
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", logical)
    provider_resilience.reset()
    index_vector_adapter.clear_disposable()
    transport = index_vector_adapter.register_disposable(RESOURCE)
    forbidden_calls = _forbid_generation(monkeypatch)
    try:
        meta, chunks, staged = await _stage_mixed(monkeypatch, logical)
        async with get_session_factory()() as db:
            await publish_and_activate(db, staged)
            pin = await index_generations.load_active_generation(db, logical_index=logical)
            members = await index_generations.load_generation_members(db, generation_id=pin["generation_id"])
        # Keep the actual adapter's readback/hash verification. Only its final
        # synthetic transport ranking is controlled, never the HTTP lookup.
        originals = sorted((member for member in members if member["snapshot_json"]["section"] != "Facts"),
                           key=lambda member: member["snapshot_json"]["chunk_index"])
        points = [deepcopy(transport.points[member["vector_id"]]) for member in originals]
        def search(_pin, vectors, top_k, *_args, **_kwargs):
            return [[(deepcopy(point), 0.1 + index / 100) for index, point in enumerate(points[:top_k])] for _ in vectors]
        monkeypatch.setattr(transport, "search", search)
        yield {"logical": logical, "meta": meta, "chunks": chunks, "pin": pin, "members": members,
               "transport": transport, "forbidden_calls": forbidden_calls}
    finally:
        index_vector_adapter.clear_disposable()
        provider_resilience.reset()


def _assert_no_synthesis(payload, fixture):
    assert fixture["forbidden_calls"] == []
    assert payload["tokens_used"] == 0 and payload["input_budget"]["status"] == "not_requested"
    assert payload["answer_mode"] == "abstention" and payload["assessment_scope"] == "none"
    assert payload["scientific_support_status"] == "not_checked" and payload["claim_assessments"] == []
    assert payload["scientific_mixed"]["scientific_acceptance"] is False
    assert payload["scientific_mixed"]["independent_support_count"] is None


def _assert_withdrawn(payload, fixture):
    _assert_no_synthesis(payload, fixture)
    assert payload["scientific_mixed"]["status"] == "unavailable"
    assert payload["scientific_lookup"]["status"] == "unavailable"
    assert payload["scientific_results"] == payload["sources"] == payload["scientific_mixed"]["associations"] == []
    assert payload["scientific_mixed"]["result_count"] == payload["scientific_mixed"]["source_count"] == 0


@pytest.mark.parametrize("question", [AMBIENT_MIXED, "MgB2在常压下的临界温度是多少，为什么？"])
async def test_mixed_http_returns_exact_result_and_originals_but_no_causal_synthesis(client, mixed_generation, question):
    parsed = interpret_scientific_query(question)
    assert parsed.status == "resolved" and parsed.intent == "mixed"
    response = await client.post("/v1/ask", json={"question": question, "max_sources": 3})
    assert response.status_code == 200, response.text
    payload = response.json()
    AskResponse.model_validate(payload)
    _assert_no_synthesis(payload, mixed_generation)
    assert payload["scientific_mixed"]["status"] == "completed"
    assert payload["scientific_lookup"]["status"] == "completed"
    result, = payload["scientific_results"]
    assert result["result"]["tc"]["value"] == 39
    assert result["result"]["reported_context"]["sample_label"] == "specimen A"
    assert result["result"]["reported_context"]["structure_phase"] == "synthetic-phase-A"
    assert len(payload["sources"]) == 2
    assert all(source["evidence_provenance"]["chunk_kind"] == "original_passage" for source in payload["sources"])
    assert payload["retrieval_generation"]["generation_id"] == mixed_generation["pin"]["generation_id"]
    pairs = payload["scientific_mixed"]["associations"]
    assert len(pairs) == 2 and {pair["source_index"] for pair in pairs} == {1, 2}
    for pair in pairs:
        source = payload["sources"][pair["source_index"] - 1]
        assert pair["parent_result_revision_id"] == result["binding"]["parent_result_revision_id"]
        assert pair["source_vector_id"] == source["packing_info"]["chunk_id"]
        assert pair["source_content_sha256"] == source["evidence_provenance"]["content_sha256"]
        assert pair["status"] == "not_established" and pair["catalogue_relation"] == "same_snapshot"


async def test_same_paper_different_samples_pressures_phases_never_become_positive_links(client, mixed_generation):
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 5})
    assert response.status_code == 200, response.text
    payload = response.json()
    _assert_no_synthesis(payload, mixed_generation)
    assert payload["scientific_results"][0]["result"]["tc"]["value"] == 39
    assert any("specimen B" in source["snippet"] and "150 GPa" in source["snippet"]
               and "synthetic-phase-B" in source["snippet"] for source in payload["sources"])
    # Every original deliberately includes every paper extraction. That list
    # must not be promoted into result-specific original-passage entailment.
    for member in mixed_generation["members"]:
        if member["snapshot_json"]["section"] != "Facts":
            assert len(member["snapshot_json"]["materials_mentioned"]) == 4
    assert all(pair["status"] == "not_established" and pair["reason_code"] == "reviewed_result_passage_bridge_missing"
               for pair in payload["scientific_mixed"]["associations"])


async def test_not_detected_mixed_result_keeps_detection_limit_not_tc_zero(client, mixed_generation):
    response = await client.post("/v1/ask", json={"question": "Why is superconductivity not detected in Nb?", "max_sources": 3})
    assert response.status_code == 200, response.text
    payload = response.json()
    _assert_no_synthesis(payload, mixed_generation)
    result, = payload["scientific_results"]
    report = result["result"]
    assert report["outcome_state"] == "not_detected" and report["tc"]["value"] is None
    assert report["minimum_temperature"]["value"] == 1
    assert report["pressure"]["pressure_state"] == "not_reported" and report["pressure"]["value"] is None
    assert report["detection_adequacy_verified"] is False


async def test_unknown_pressure_does_not_match_ambient_but_remains_an_unconditioned_report(client, mixed_generation):
    broad = await client.post("/v1/ask", json={"question": "What is Tc of MgB2 and why?", "max_sources": 8})
    assert broad.status_code == 200, broad.text
    reports = [row["result"] for row in broad.json()["scientific_results"]]
    assert {row["tc"]["value"] for row in reports} == {18, 20, 39}
    unknown = next(row for row in reports if row["tc"]["value"] == 18)
    assert unknown["pressure"]["pressure_state"] == "not_reported"
    ambient = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 8})
    assert ambient.status_code == 200, ambient.text
    assert [row["result"]["tc"]["value"] for row in ambient.json()["scientific_results"]] == [39]


@pytest.mark.parametrize("limit", [1, 2, 3, 20])
async def test_mixed_result_and_original_inputs_share_one_budget_and_one_fresh_check(client, mixed_generation, monkeypatch, limit):
    checked = []
    original = retrieval_currentness.check_selected_sources
    async def check(pins, **kwargs):
        checked.append(tuple(pins))
        return await original(pins, **kwargs)
    monkeypatch.setattr(retrieval_currentness, "check_selected_sources", check)
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": limit})
    assert response.status_code == 200, response.text
    payload = response.json()
    _assert_no_synthesis(payload, mixed_generation)
    total = len(payload["scientific_results"]) + len(payload["sources"])
    assert total <= limit and payload["scientific_mixed"]["max_selected_inputs"] == limit
    assert len(checked) == 1 and len(checked[0]) == total
    expected = {row["binding"]["vector_id"] for row in payload["scientific_results"]} | {
        source["packing_info"]["chunk_id"] for source in payload["sources"]}
    assert {pin.chunk_id for pin in checked[0]} == expected
    assert all(pin.grouping_sha256 is not None for pin in checked[0])
    if limit == 1:
        assert len(payload["scientific_results"]) == 1 and not payload["sources"]
        assert "no_original_context" in payload["scientific_mixed"]["reason_codes"]


async def test_mixed_byte_budget_can_omit_originals_without_inventing_provider_token_measurement(client, mixed_generation, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_input_byte_limit", 1)
    monkeypatch.setattr(get_settings(), "gemini_max_input_tokens", 1)
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED})
    assert response.status_code == 200, response.text
    payload = response.json()
    _assert_no_synthesis(payload, mixed_generation)
    assert payload["scientific_mixed"]["status"] == "completed"
    assert len(payload["scientific_results"]) == 1 and payload["sources"] == []
    assert payload["evidence_packing"]["status"] == "base_budget_exceeded"
    assert payload["input_budget"]["input_tokens"] is None


@pytest.mark.parametrize("change", ["source_hold", "work_mapping", "activation", "activation_aba", "parent_descriptor"])
async def test_joint_currentness_change_withdraws_both_halves_and_associations(client, mixed_generation, monkeypatch, change):
    staged = None
    if change in {"activation", "activation_aba"}:
        _, _, staged = await _stage_mixed(monkeypatch, mixed_generation["logical"], meta=mixed_generation["meta"], label="new rendering")
    original_check = retrieval_currentness.check_selected_sources
    original_resolver = ask_router._resolve_evidence
    checking = False
    async def changed_resolver(db, chunks):
        values = await original_resolver(db, chunks)
        if checking and change == "parent_descriptor":
            for key, descriptor in values.items():
                if descriptor["chunk_kind"] == "derived_fact":
                    values[key] = {**descriptor, "parent_result_sha256": "0" * 64}
        return values
    async def change_then_check(pins, **kwargs):
        nonlocal checking
        checking = True
        async with get_session_factory()() as other:
            if change == "source_hold":
                await other.execute(sa.update(Paper).where(Paper.id == mixed_generation["meta"].paper_id).values(status="corrected"))
                await other.commit()
            elif change == "work_mapping":
                work = Work(id=uuid4(), canonical_title="Synthetic changed Work grouping")
                other.add(work)
                await other.flush()
                mapping = await other.get(PaperWorkMap, mixed_generation["meta"].paper_id)
                if mapping is None:
                    other.add(PaperWorkMap(paper_id=mixed_generation["meta"].paper_id, work_id=work.id,
                        relation_type="canonical_version", match_method="manual", review_status="accepted"))
                else:
                    mapping.work_id, mapping.review_status = work.id, "accepted"
                await other.commit()
            elif change in {"activation", "activation_aba"}:
                promoted, _, _ = await publish_and_activate(other, staged, expected_event_id=mixed_generation["pin"]["activation_event_id"])
                if change == "activation_aba":
                    await publish_and_activate(other, mixed_generation["pin"], expected_event_id=promoted["activation_event_id"], action="rollback")
        return await original_check(pins, **kwargs)
    monkeypatch.setattr(ask_router, "_resolve_evidence", changed_resolver)
    monkeypatch.setattr(retrieval_currentness, "check_selected_sources", change_then_check)
    response = await asyncio.wait_for(client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 3}), timeout=10)
    assert response.status_code == 200, response.text
    payload = response.json()
    _assert_withdrawn(payload, mixed_generation)
    assert "Synthetic retained original" not in response.text
    assert all(member["vector_id"] not in response.text for member in mixed_generation["members"])


async def test_withdrawn_mixed_history_does_not_retain_old_originals(client, mixed_generation, registered_user, monkeypatch):
    user, token = registered_user
    original = retrieval_currentness.check_selected_sources
    async def held(pins, **kwargs):
        async with get_session_factory()() as other:
            await other.execute(sa.update(Paper).where(Paper.id == mixed_generation["meta"].paper_id).values(status="corrected"))
            await other.commit()
        return await original(pins, **kwargs)
    monkeypatch.setattr(retrieval_currentness, "check_selected_sources", held)
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    _assert_withdrawn(response.json(), mixed_generation)
    async with get_session_factory()() as db:
        history = (await db.execute(sa.select(AskHistory).where(AskHistory.user_id == user.id).order_by(AskHistory.created_at.desc()))).scalars().first()
        assert history is not None and history.sources == []
        assert "Synthetic retained original" not in history.answer
        identifier = history.id
    assert response.json()["history"]["status"] == "saved", response.text
    detail = await client.get(f"/v1/history/{identifier}", headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200, detail.text
    evidence = detail.json()["evidence"]
    assert evidence["status"] == "verified" and evidence["binding_scope"] == "no_selected_evidence"
    assert evidence["receipt"]["bindings"]["items"] == []
    assert mixed_generation["meta"].paper_id not in json.dumps(evidence["receipt"])


@pytest.mark.parametrize("field", ["content_sha256", "snippet", "packing_snapshot", "title", "authors_short"])
async def test_modified_outgoing_original_cannot_reuse_untampered_selection_pin(client, mixed_generation, monkeypatch, field):
    original = ask_router._mixed_response
    changed = []

    async def modify_before_publication(*args, **kwargs):
        originals = kwargs.get("originals", ())
        if originals and kwargs.get("reason") is None:
            source = json.loads(originals[0]._source_json)
            if field == "content_sha256":
                source["evidence_provenance"]["content_sha256"] = "0" * 64
            elif field == "snippet":
                source["snippet"] = "Injected explanation of superconductivity in another specimen."
            elif field == "packing_snapshot":
                source["packing_info"]["source_snapshot_sha256"] = "0" * 64
            else:
                source[field] = "Injected attribution"
            # Simulate a corrupted private payload, not an authorised reseal.
            # SQL pins remain unchanged and the old local integrity seal must
            # reject publication of the newly altered representation.
            object.__setattr__(originals[0], "_source_json", json.dumps(source))
            changed.append(field)
        return await original(*args, **kwargs)

    monkeypatch.setattr(ask_router, "_mixed_response", modify_before_publication)
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 3})
    assert response.status_code == 200, response.text
    assert changed == [field]
    _assert_withdrawn(response.json(), mixed_generation)
    assert "Injected explanation" not in response.text


async def test_detached_original_projection_cannot_mutate_frozen_mixed_publication(client, mixed_generation, monkeypatch):
    original = ask_router._mixed_response
    detached = []

    async def mutate_detached_copy(*args, **kwargs):
        originals = kwargs.get("originals", ())
        if originals and kwargs.get("reason") is None:
            source = originals[0].source
            source.snippet = "Injected mutable projection"
            source.evidence_provenance["content_sha256"] = "0" * 64
            detached.append(source)
        return await original(*args, **kwargs)

    monkeypatch.setattr(ask_router, "_mixed_response", mutate_detached_copy)
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 3})
    assert response.status_code == 200, response.text
    assert len(detached) == 1
    payload = response.json()
    _assert_no_synthesis(payload, mixed_generation)
    assert payload["scientific_mixed"]["status"] == "completed"
    assert "Injected mutable projection" not in response.text
    assert all(source["evidence_provenance"]["content_sha256"] != "0" * 64 for source in payload["sources"])


async def test_typed_comparison_preserves_multi_target_results_and_unestablished_original_context(client, mixed_generation):
    question = "Compare MgB2 and Nb Tc and explain why"
    interpretation = interpret_scientific_query(question)
    assert interpretation.status == "resolved" and interpretation.intent == "comparison"
    response = await client.post("/v1/ask", json={"question": question, "max_sources": 8})
    assert response.status_code == 200, response.text
    payload = response.json()
    _assert_no_synthesis(payload, mixed_generation)
    assert payload["scientific_query"]["intent"] == "comparison"
    assert payload["scientific_mixed"]["status"] == "completed"
    assert {row["result"]["formula"] for row in payload["scientific_results"]} == {"MgB2", "Nb"}
    assert payload["sources"] and len(payload["scientific_mixed"]["associations"]) == (
        len(payload["scientific_results"]) * len(payload["sources"]))
    assert all(pair["status"] == "not_established" for pair in payload["scientific_mixed"]["associations"])


async def test_no_generation_mixed_request_is_unavailable_not_legacy_numerical_fallback(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", "missing-mixed-" + uuid4().hex)
    calls = _forbid_generation(monkeypatch)
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED})
    assert response.status_code == 200, response.text
    _assert_withdrawn(response.json(), {"forbidden_calls": calls})


async def test_unsupported_sample_filter_still_clarifies_before_mixed_retrieval(client, mixed_generation):
    response = await client.post("/v1/ask", json={"question": "What is Tc of MgB2 in sample A and why?"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scientific_lookup"]["status"] == "clarification_required"
    assert payload["scientific_mixed"]["status"] == "not_requested"
    assert payload["scientific_results"] == payload["sources"] == [] and mixed_generation["forbidden_calls"] == []
