"""Development regressions over actual retained SQL parents, not a gold set."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from models.db import AskHistory, get_session_factory
from services import (
    index_generations,
    index_retrieval,
    index_vector_adapter,
    rag,
    retrieval_currentness,
)
from tests.index_generation_fixtures import RESOURCE, prepare_generation_items, publish_and_activate


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    # These tests retain read transactions across requests. Session teardown
    # must run on the same event loop that opened its asyncpg connection.
    async with get_session_factory()() as session:
        yield session


def record(formula="MgB2", tc="39 K", pressure="ambient", **extra):
    return {"formula": formula, "tc_kelvin": tc, "pressure": pressure, "knowledge_origin": "Observed",
        "source_role": "primary", "extractor_version": "synthetic/1", "measurement_method": "resistance", **extra}


@pytest.fixture
def scientific_runtime(monkeypatch):
    logical = "scientific-http-" + uuid4().hex
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", logical)
    index_vector_adapter.clear_disposable()
    index_vector_adapter.register_disposable(RESOURCE)
    yield logical
    index_vector_adapter.clear_disposable()


async def stage_records(monkeypatch, db, logical, records, *, meta=None, original=False, extra_record=None,
                        text_override=None):
    from ingestion.chunk.chunker import count_tokens
    from ingestion.embedding_contract import (
        LOCAL_DOCUMENT_COUNT_METHOD,
        LOCAL_DOCUMENT_INPUT_LIMIT,
        LOCAL_DOCUMENT_REQUEST_LIMIT,
        validate_embedding_response,
    )
    from ingestion.extract.fact_sentences import build_fact_chunks
    from ingestion.index import indexer
    from ingestion.models import ApsArticleMeta

    meta = meta or ApsArticleMeta(doi="10.0000/ScientificQuery." + uuid4().hex,
        title="Synthetic superconductivity extraction", authors=["Synthetic Fixture"], abstract="Synthetic abstract.",
        date_published=date(2024, 1, 1))
    chunks = build_fact_chunks(meta, records, start_index=0)
    assert chunks
    if text_override is not None:
        from ingestion.config import get_settings as ingestion_settings
        monkeypatch.setattr(ingestion_settings(), "chunk_size_tokens", 1536)
    for index, chunk in enumerate(chunks):
        if text_override is not None:
            chunk.text = text_override
        if original:
            chunk.evidence_candidate = {"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage",
                "rendering_version": "sclib-section-chunker/2.0.0"}
        if extra_record is not None:
            chunk.materials_mentioned.append(deepcopy(extra_record))
        count = count_tokens(chunk.text)
        chunk.token_count = count
        vector, receipt = validate_embedding_response([chunk.text], SimpleNamespace(embeddings=[SimpleNamespace(
            values=[0.125 + index / 1000] * 768, statistics=SimpleNamespace(truncated=False, token_count=float(count)))]),
            model="text-embedding-005", dimension=768, task_type="RETRIEVAL_DOCUMENT", local_counts=[count],
            local_count_method=LOCAL_DOCUMENT_COUNT_METHOD, local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
            local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT)[0]
        chunk.embedding, chunk.embedding_provenance = vector, receipt
    monkeypatch.setattr(indexer, "_session_factory", get_session_factory)
    staged = {}
    async def stager(session, selected):
        staged.update(await index_generations.stage_generation(session, generation_id=str(uuid4()), logical_index=logical,
            resource=RESOURCE, items=await prepare_generation_items(session, selected), dry_run=False))
    await indexer.upsert_aps_paper_with_chunks(meta, chunks, records, generation_stager=stager)
    return meta, chunks, staged


def forbid_providers(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Numerical/clarification lookup must not call a provider")
    monkeypatch.setattr(index_vector_adapter, "query", forbidden)
    from services import rag
    monkeypatch.setattr(rag, "generate_answer", forbidden)


async def test_numerical_ask_matches_all_conditions_in_one_bound_record(client, db_session, monkeypatch, scientific_runtime):
    values = [record(tc="39 K", pressure="150 GPa"), record(tc="20 K"), record(tc="38 K")]
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, values)
    active, _, _ = await publish_and_activate(db_session, staged)
    forbid_providers(monkeypatch)
    response = await client.post("/v1/ask", json={"question": "Show experimental MgB₂ with Tc > 30 K at ambient pressure"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_lookup"]["status"] == "completed", body
    assert [item["result"]["tc"]["value"] for item in body["scientific_results"]] == [38]
    item = body["scientific_results"][0]
    assert item["binding"]["generation_id"] == active["generation_id"]
    assert item["binding"]["association_scope"] == "derived_extraction_not_original_support"
    assert body["scientific_support_status"] == "not_checked" and body["tokens_used"] == 0
    assert not item["result"]["scientific_acceptance"] and not item["result"]["ml_training_eligible"]
    assert "not independently reviewed" in body["answer"]


@pytest.mark.parametrize("question", ["What is the Tc of MgB₂ at ambient pressure?", "MgB2在常压下的临界温度是多少？"])
async def test_missing_and_numeric_zero_pressure_are_not_ambient(client, db_session, monkeypatch, scientific_runtime, question):
    values = [record(pressure=None), record(pressure=0), record(tc="38 K")]
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, values)
    await publish_and_activate(db_session, staged)
    forbid_providers(monkeypatch)
    response = await client.post("/v1/ask", json={"question": question})
    assert response.status_code == 200, response.text
    assert [item["result"]["tc"]["value"] for item in response.json()["scientific_results"]] == [38]


async def test_original_chunk_paper_wide_materials_are_not_quantitative_parents(client, db_session, monkeypatch, scientific_runtime):
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [record()], original=True)
    await publish_and_activate(db_session, staged)
    response = await client.post("/v1/ask", json={"question": "What is the Tc of MgB2?"})
    assert response.status_code == 200, response.text
    assert response.json()["scientific_lookup"]["status"] == "completed"
    assert response.json()["scientific_results"] == []


async def test_same_chunk_unrelated_record_cannot_borrow_another_parent(client, db_session, monkeypatch, scientific_runtime):
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime,
        [record("Nb", "9.2 K")], extra_record=record())
    await publish_and_activate(db_session, staged)
    response = await client.post("/v1/ask", json={"question": "What is the Tc of MgB2?"})
    assert response.status_code == 200, response.text
    assert response.json()["scientific_lookup"]["status"] == "completed"
    assert response.json()["scientific_results"] == []


async def test_typographic_formula_lookup_recovers_real_generation_text(client, db_session, monkeypatch, scientific_runtime):
    meta, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [record("MgB₂")])
    await publish_and_activate(db_session, staged)
    found = []
    for spelling in ("MgB2", "MgB₂", "MgB_{2}"):
        response = await client.post("/v1/search", json={"query": spelling})
        assert response.status_code == 200, response.text
        found.append([item["paper_id"] for item in response.json()["results"]])
    assert found == [[meta.paper_id]] * 3


async def test_no_generation_and_unsafe_isotope_are_explicit_without_provider_calls(client, monkeypatch, scientific_runtime):
    forbid_providers(monkeypatch)
    missing = (await client.post("/v1/ask", json={"question": "What is the Tc of MgB2?"})).json()
    assert missing["scientific_lookup"]["status"] == "unavailable" and missing["scientific_results"] == []
    unsafe = (await client.post("/v1/ask", json={"question": "What is the Tc of Mg¹¹B2?"})).json()
    assert unsafe["scientific_lookup"]["status"] == "clarification_required" and unsafe["scientific_results"] == []
    assert unsafe["scientific_query"]["raw_query"] == "What is the Tc of Mg¹¹B2?"


async def test_non_detection_keeps_detection_temperature_separate(client, db_session, monkeypatch, scientific_runtime):
    negative = record("Nb", None, result_status="not_detected", minimum_temperature_k="1 K")
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [negative])
    await publish_and_activate(db_session, staged)
    response = await client.post("/v1/ask", json={"question": "Show not detected Nb"})
    assert response.status_code == 200, response.text
    item = response.json()["scientific_results"][0]["result"]
    assert item["outcome_state"] == "not_detected"
    assert item["tc"]["value"] is None and item["minimum_temperature"]["value"] == 1
    assert not item["detection_adequacy_verified"]


async def test_fresh_source_hold_withholds_all_prepared_results(client, db_session, monkeypatch, scientific_runtime):
    meta, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [record()])
    await publish_and_activate(db_session, staged)
    original = retrieval_currentness.check_selected_sources
    async def held(pins, **kwargs):
        async with get_session_factory()() as other:
            await other.execute(sa.text("UPDATE papers SET status='corrected' WHERE id=:id"), {"id": meta.paper_id})
            await other.commit()
        return await original(pins, **kwargs)
    monkeypatch.setattr(retrieval_currentness, "check_selected_sources", held)
    response = await client.post("/v1/ask", json={"question": "What is the Tc of MgB2?"})
    assert response.status_code == 200, response.text
    assert response.json()["scientific_lookup"]["status"] == "unavailable"
    assert response.json()["scientific_results"] == []


async def test_quantitative_search_respects_retained_year_and_output_kind(client, db_session, monkeypatch, scientific_runtime):
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [record()])
    await publish_and_activate(db_session, staged)
    first = (await client.post("/v1/search", json={"query": "MgB2 Tc > 30 K", "filters": {"year_min": 2023}})).json()
    second = (await client.post("/v1/search", json={"query": "MgB2 Tc > 30 K", "filters": {"year_min": 2025}})).json()
    assert first["results"] == [] and first["scientific_lookup"]["returned_count"] == 1
    assert second["scientific_lookup"]["status"] == "completed" and second["scientific_results"] == []


async def test_numeric_lookup_retains_old_parent_through_replacement_and_actual_rollback(
    client, db_session, monkeypatch, scientific_runtime,
):
    meta, _, old = await stage_records(monkeypatch, db_session, scientific_runtime, [record(tc="39 K")])
    first, _, _ = await publish_and_activate(db_session, old)
    _, _, new = await stage_records(monkeypatch, db_session, scientific_runtime, [record(tc="37 K")], meta=meta)
    forbid_providers(monkeypatch)
    async def read():
        response = await client.post("/v1/ask", json={"question": "What is the Tc of MgB2?"})
        assert response.status_code == 200, response.text
        return response.json()["scientific_results"][0]
    before = await read()
    assert before["result"]["tc"]["value"] == 39
    promoted, _, _ = await publish_and_activate(db_session, new, expected_event_id=first["activation_event_id"])
    after = await read()
    assert after["result"]["tc"]["value"] == 37
    # Reactivation deliberately requires the target's complete source snapshot.
    # Restore that exact synthetic source before rollback; do not relax 0062's
    # source-hash guard to make a changed scientific source look unchanged.
    await stage_records(monkeypatch, db_session, scientific_runtime, [record(tc="39 K")], meta=meta)
    restored, _, _ = await publish_and_activate(db_session, old, expected_event_id=promoted["activation_event_id"], action="rollback")
    rollback = await read()
    assert rollback["result"]["tc"]["value"] == 39
    assert rollback["binding"]["parent_result_revision_id"] == before["binding"]["parent_result_revision_id"]
    assert rollback["binding"]["activation_event_id"] == restored["activation_event_id"] != before["binding"]["activation_event_id"]


async def test_numeric_lookup_rejects_activation_aba_after_selected_input_check(client, db_session, monkeypatch, scientific_runtime):
    meta, _, old = await stage_records(monkeypatch, db_session, scientific_runtime, [record()])
    first, _, _ = await publish_and_activate(db_session, old)
    _, _, new = await stage_records(monkeypatch, db_session, scientific_runtime, [record()], meta=meta,
        text_override="Synthetic replacement rendering for MgB2; not original scientific evidence.")
    original = retrieval_currentness.check_selected_sources
    async def switched(pins, **kwargs):
        checked = await original(pins, **kwargs)
        async with get_session_factory()() as other:
            second, _, _ = await publish_and_activate(other, new, expected_event_id=first["activation_event_id"])
            await publish_and_activate(other, old, expected_event_id=second["activation_event_id"], action="rollback")
        return checked
    monkeypatch.setattr(retrieval_currentness, "check_selected_sources", switched)
    response = await client.post("/v1/ask", json={"question": "MgB2 Tc"})
    assert response.status_code == 200, response.text
    assert response.json()["scientific_lookup"]["status"] == "unavailable"
    assert response.json()["scientific_results"] == []


async def test_numeric_search_bounds_use_raw_uncertainty_and_same_record_filters(client, db_session, monkeypatch, scientific_runtime):
    values = [record(tc=39, raw_extraction={"tc_kelvin": "39 ± 5 K"}), record(tc="38.5 K"),
        record(tc="39 K", knowledge_origin="Observed", raw_extraction={"knowledge_origin": "Computed"}),
        record(tc="39 K", pressure="ambient", raw_extraction={"pressure": "150 GPa"})]
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, values)
    await publish_and_activate(db_session, staged)
    response = await client.post("/v1/search", json={"query": "MgB2 Tc", "filters": {
        "tc_min": 38, "ambient_only": True, "experimental_only": True}})
    assert response.status_code == 200, response.text
    assert [row["result"]["tc"]["value"] for row in response.json()["scientific_results"]] == [38.5]


async def test_numeric_results_are_capped_with_explicit_more_flag(client, db_session, monkeypatch, scientific_runtime):
    values = [record(tc=f"{10 + index} K", sample_label=f"synthetic-{index}") for index in range(24)]
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, values)
    await publish_and_activate(db_session, staged)
    response = await client.post("/v1/search", json={"query": "MgB2 Tc", "top_k": 40})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_lookup"]["returned_count"] == len(body["scientific_results"]) == 20
    assert body["scientific_lookup"]["has_more"] is True
    assert len({row["binding"]["parent_result_revision_id"] for row in body["scientific_results"]}) == 20


@pytest.mark.parametrize("question,structured", [("MgB2 Tc", True), ("What is the Tc of Mg¹¹B2?", False)])
async def test_lookup_history_keeps_no_fake_citations_or_unbound_numerical_rows(
    client, db_session, monkeypatch, scientific_runtime, registered_user, question, structured,
):
    user, token = registered_user
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [record()])
    await publish_and_activate(db_session, staged)
    forbid_providers(monkeypatch)
    response = await client.post("/v1/ask", json={"question": question}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    await db_session.rollback()
    history = (await db_session.execute(sa.select(AskHistory).where(AskHistory.user_id == user.id))).scalars().one()
    assert history.question == question and history.sources == [] and history.tokens_used == 0
    if structured:
        assert "not retained in this history schema" in history.answer
        assert "listed below" not in history.answer and "39" not in history.answer
    else:
        assert history.answer == response.json()["answer"]


@pytest.mark.parametrize("text", ["MgB2 " + " " * 21000, "MgB2 " * 300], ids=["long-whitespace", "many-mentions"])
async def test_valid_retained_text_above_query_scanner_budget_still_supports_formula_search(
    client, db_session, monkeypatch, scientific_runtime, text,
):
    meta, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [record()], original=True,
        text_override=text)
    await publish_and_activate(db_session, staged)
    response = await client.post("/v1/search", json={"query": "MgB2"})
    assert response.status_code == 200, response.text
    assert [row["paper_id"] for row in response.json()["results"]] == [meta.paper_id]


@pytest.mark.parametrize("question,origin", [("experimental MgB2", "Observed"), ("computed MgB2 pairing", "Computed")])
async def test_explicit_evidence_constraints_never_fall_through_to_unfiltered_generic_retrieval(
    client, db_session, monkeypatch, scientific_runtime, question, origin,
):
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime,
        [record(), record(tc="38 K", knowledge_origin="Computed", measurement_method="DFT")])
    await publish_and_activate(db_session, staged)
    forbid_providers(monkeypatch)
    response = await client.post("/v1/ask", json={"question": question})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_lookup"]["status"] == "completed"
    assert [row["result"]["result_classification"]["knowledge_origin"] for row in body["scientific_results"]] == [origin]
    if origin == "Computed":
        assert "explanatory_synthesis_not_performed" in body["scientific_lookup"]["reason_codes"]


@pytest.mark.parametrize("query", ["MgB2", "superconductivity", "MgB2 superconductivity", "unmatchedqueryneedle"])
async def test_ui_predicates_use_raw_extents_without_losing_remaining_keywords(
    client, db_session, monkeypatch, scientific_runtime, query,
):
    values = [record(tc=39, raw_extraction={"tc_kelvin": "39 ± 5 K"}), record(tc="38.5 K")]
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, values)
    await publish_and_activate(db_session, staged)
    forbid_providers(monkeypatch)
    response = await client.post("/v1/search", json={"query": query, "filters": {"tc_min": 38}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_lookup"]["status"] == "completed"
    assert [row["result"]["tc"]["value"] for row in body["scientific_results"]] == (
        [] if query == "unmatchedqueryneedle" else [38.5])


async def test_parent_deduplication_happens_after_rendering_admission(client, db_session, monkeypatch, scientific_runtime):
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [record(), record()])
    await publish_and_activate(db_session, staged)
    original = index_retrieval.resolve_evidence
    restricted_ids = []
    async def restricted_first(db, chunks):
        resolved = await original(db, chunks)
        if len(resolved) > 1:
            # Model one independently unavailable rendering at the resolver
            # boundary; the other exact SQL parent/rendering remains verified.
            first = sorted(resolved)[0]
            restricted_ids.append(first)
            resolved[first] = {**resolved[first], "permission_status": "restricted"}
        return resolved
    monkeypatch.setattr(index_retrieval, "resolve_evidence", restricted_first)
    response = await client.post("/v1/ask", json={"question": "MgB2 Tc"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_lookup"]["returned_count"] == 1 and not body["scientific_lookup"]["has_more"]
    assert body["scientific_results"][0]["binding"]["vector_id"] not in restricted_ids


@pytest.mark.parametrize("question", ["Explain MgB2 pairing", "Compare the pairing mechanisms of MgB2 and Nb"])
@pytest.mark.parametrize("original", [False, True], ids=["derived-fact", "original-passage"])
async def test_explanations_and_mechanism_comparisons_select_only_original_passages(
    client, db_session, monkeypatch, scientific_runtime, question, original,
):
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime, [record()], original=original)
    await publish_and_activate(db_session, staged)
    selected = []
    def generate(_question, sources, **_kwargs):
        selected.extend(sources)
        return rag.extractive_fallback(sources)
    monkeypatch.setattr(rag, "generate_answer", generate)
    response = await client.post("/v1/ask", json={"question": question})
    assert response.status_code == 200, response.text
    if original:
        assert selected
        assert all(source.evidence_provenance["chunk_kind"] == "original_passage" for source in selected)
    else:
        assert selected == [] and response.json()["sources"] == []


@pytest.mark.parametrize("path,field", [("search", "query"), ("ask", "question")])
async def test_blank_request_and_bounded_interpretation_overflow_do_not_raise_500(client, path, field):
    blank = await client.post("/v1/" + path, json={field: "   "})
    assert blank.status_code == 422
    overflow = await client.post("/v1/" + path, json={field: "Nb " * 257})
    assert overflow.status_code == 200, overflow.text
    assert overflow.json()["scientific_lookup"]["status"] == "clarification_required"
    assert overflow.json()["scientific_results"] == []


async def test_ui_family_and_tc_conditions_cannot_borrow_from_another_bound_result(
    client, db_session, monkeypatch, scientific_runtime,
):
    _, _, staged = await stage_records(monkeypatch, db_session, scientific_runtime,
        [record(tc="39 K", family="mgb2"), record(tc="20 K", family="synthetic-alternate")])
    await publish_and_activate(db_session, staged)
    for family, expected in (("mgb2", [39]), ("synthetic-alternate", [])):
        response = await client.post("/v1/search", json={"query": "MgB2", "filters": {
            "material_family": [family], "tc_min": 30}})
        assert response.status_code == 200, response.text
        assert response.json()["scientific_lookup"]["status"] == "completed"
        assert [row["result"]["tc"]["value"] for row in response.json()["scientific_results"]] == expected
