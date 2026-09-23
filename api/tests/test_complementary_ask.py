"""Synthetic development regressions over real retained SQL, not an expert gold set."""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic import ValidationError

from config import get_settings
from models.db import Paper, PaperWorkMap, Work, get_session_factory
from models.search import AskResponse
from services import (
    complementary_retrieval,
    index_generations,
    index_vector_adapter,
    provider_resilience,
    rag,
    retrieval,
)
from tests import index_generation_fixtures as fixtures


@pytest_asyncio.fixture
async def complementary(monkeypatch):
    logical = "complementary-" + uuid4().hex
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", logical)
    provider_resilience.reset()
    index_vector_adapter.clear_disposable()
    transport = index_vector_adapter.register_disposable(fixtures.RESOURCE)
    original = fixtures.corpus

    def corpus(**kwargs):
        meta, record, chunks = original(**kwargs)
        for index, chunk in enumerate(chunks):
            chunk.section = ["Results", "Methods", "Results", "Table 1", "Discussion"][index]
            chunk.has_table = index == 3
            if index != 4:
                chunk.evidence_candidate = {"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage",
                    "rendering_version": "sclib-section-chunker/2.0.0"}
        return meta, record, chunks

    monkeypatch.setattr(fixtures, "corpus", corpus)
    meta, chunks, staged = await fixtures.write_generation(monkeypatch, logical_index=logical)
    async with get_session_factory()() as db:
        await fixtures.publish_and_activate(db, staged)
        pin = await index_generations.load_active_generation(db, logical_index=logical)
        members = await index_generations.load_generation_members(db, generation_id=pin["generation_id"])
    seed = next(item for item in members if item["snapshot_json"]["chunk_index"] == 0)
    point = deepcopy(transport.points[seed["vector_id"]])
    monkeypatch.setattr(transport, "search", lambda _pin, vectors, *_, **_kwargs: [[(deepcopy(point), 0.125)] for _ in vectors])

    async def no_lexical(*args, **kwargs):
        return []
    monkeypatch.setattr(retrieval, "lexical_search", no_lexical)
    yield {"meta": meta, "chunks": chunks, "pin": pin, "members": members, "seed": seed}
    index_vector_adapter.clear_disposable()
    provider_resilience.reset()


def fake_provider(monkeypatch, *, count=100, before_count=None):
    calls = []
    def count_tokens(**kwargs):
        calls.append(("count", kwargs))
        if before_count:
            before_count()
        return SimpleNamespace(total_tokens=count)
    def generate_content(**kwargs):
        calls.append(("generate", kwargs))
        return SimpleNamespace(text="The supplied excerpts do not establish an answer to this question.",
                               usage_metadata=SimpleNamespace(total_token_count=130))
    monkeypatch.setattr(rag, "genai_client", lambda: SimpleNamespace(models=SimpleNamespace(
        count_tokens=count_tokens, generate_content=generate_content)))
    return calls


async def test_real_same_snapshot_expansion_retains_three_full_roles_and_exact_payload(client, complementary, monkeypatch):
    calls = fake_provider(monkeypatch)
    response = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism", "language": "en"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [kind for kind, _ in calls] == ["count", "generate"]
    assert calls[0][1]["contents"] == calls[1][1]["contents"]
    sources = payload["sources"]
    assert len(sources) == 3
    assert [row["index"] for row in sources] == [1, 2, 3]
    assert {row["packing_info"]["role_hint"] for row in sources} == {"methods", "results", "table"}
    assert len({row["paper_id"] for row in sources}) == 1
    assert len({row["packing_info"]["source_group_id"] for row in sources}) == 1
    prompt = calls[0][1]["contents"][0]["parts"][0]["text"]
    for row in sources:
        original = next(item for item in complementary["members"] if item["vector_id"] == row["packing_info"]["chunk_id"])
        assert original["snapshot_json"]["text"] in prompt
        assert row["evidence_provenance"]["content_sha256"] == original["content_sha256"]
        assert row["packing_info"]["source_snapshot_sha256"] == original["source_snapshot_sha256"]
        assert row["evidence_provenance"]["independent_evidence"] is False
    assert payload["evidence_packing"]["payload_bytes"] == payload["input_budget"]["payload_bytes"]
    assert payload["evidence_packing"]["independent_support_count"] is None
    assert payload["input_budget"]["input_tokens"] == 100
    assert payload["tokens_used"] == 130  # actual total usage != preflight input count


async def test_token_rejection_does_not_generate_or_invent_zero_unknown_usage(client, complementary, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_max_input_tokens", 99)
    calls = fake_provider(monkeypatch, count=100)
    response = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [kind for kind, _ in calls] == ["count"]
    assert payload["input_budget"]["status"] == "rejected"
    assert payload["input_budget"]["generation_started"] is False
    assert payload["tokens_used"] is None  # preflight usage is not a generation receipt
    assert payload["scientific_support_status"] == "not_checked"


async def test_base_byte_budget_does_not_call_any_provider(client, complementary, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_input_byte_limit", 1)
    calls = fake_provider(monkeypatch)
    response = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert not calls and payload["sources"] == []
    assert payload["evidence_packing"]["status"] == "base_budget_exceeded"
    assert payload["input_budget"]["status"] == "not_requested"
    assert payload["tokens_used"] == 0


async def test_lexical_failure_is_bounded_sanitized_and_does_not_generate(client, complementary, monkeypatch):
    calls = fake_provider(monkeypatch)
    async def failed(*args, **kwargs):
        raise RuntimeError("PRIVATE_LEXICAL_ERROR_SENTINEL")
    monkeypatch.setattr(retrieval, "lexical_search", failed)
    response = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Lexical/formula-aware retrieval is unavailable"
    assert "PRIVATE_LEXICAL_ERROR_SENTINEL" not in response.text and not calls


async def test_one_source_limit_preserves_first_hit_not_a_synthetic_merged_chunk(client, complementary, monkeypatch):
    calls = fake_provider(monkeypatch)
    response = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism", "max_sources": 1})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["sources"]) == 1 and len(calls) == 2
    assert payload["sources"][0]["packing_info"]["chunk_id"] == complementary["seed"]["vector_id"]
    assert payload["evidence_packing"]["reason_counts"]["chunk_limit"] >= 1


@pytest.mark.parametrize("change", ["source_hold", "work_mapping"])
async def test_group_or_source_change_during_provider_withholds_all_old_citations(client, complementary, monkeypatch, change):
    entered, released = threading.Event(), threading.Event()
    def blocked_count():
        entered.set()
        assert released.wait(5)
    calls = fake_provider(monkeypatch, before_count=blocked_count)
    request = asyncio.create_task(client.post("/v1/ask", json={"question": "Explain the pairing mechanism"}))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        async with get_session_factory()() as db:
            if change == "source_hold":
                await db.execute(sa.update(Paper).where(Paper.id == complementary["meta"].paper_id).values(status="corrected"))
            else:
                work = Work(id=uuid4(), canonical_title="Synthetic grouping only")
                db.add(work)
                await db.flush()
                # Ingestion may already have installed a pending/singleton map.
                existing = await db.get(PaperWorkMap, complementary["meta"].paper_id)
                if existing is None:
                    db.add(PaperWorkMap(paper_id=complementary["meta"].paper_id, work_id=work.id,
                        relation_type="canonical_version", match_method="manual", review_status="accepted"))
                else:
                    existing.work_id, existing.review_status = work.id, "accepted"
            await db.commit()
    finally:
        released.set()
    response = await asyncio.wait_for(request, 5)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [kind for kind, _ in calls] == ["count", "generate"]
    assert payload["sources"] == [] and payload["answer_mode"] == "abstention"
    assert payload["evidence_packing"]["status"] == "withheld"
    assert payload["evidence_packing"]["selected_count"] == 0
    assert payload["evidence_packing"]["payload_bytes"] is None
    assert payload["input_budget"]["input_tokens"] == 100  # only operational observation remains
    assert not any(row["vector_id"] in response.text for row in complementary["members"])


async def test_late_count_after_outer_timeout_never_starts_generation(client, complementary, monkeypatch):
    entered, released, exited = threading.Event(), threading.Event(), threading.Event()
    def blocked_count():
        entered.set()
        try:
            assert released.wait(5)
        finally:
            exited.set()
    calls = fake_provider(monkeypatch, before_count=blocked_count)
    monkeypatch.setattr(get_settings(), "gemini_timeout_seconds", 0.2)
    request = asyncio.create_task(client.post("/v1/ask", json={"question": "Explain the pairing mechanism"}))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        response = await asyncio.wait_for(request, 3)
        assert response.status_code == 200, response.text
        assert response.json()["input_budget"]["generation_started"] is None
        assert response.json()["tokens_used"] is None
    finally:
        released.set()
    assert await asyncio.to_thread(exited.wait, 1)
    await asyncio.sleep(0.03)
    assert [kind for kind, _ in calls] == ["count"]


async def test_repeated_actual_count_failure_opens_circuit_and_preserves_failure_report(client, complementary, monkeypatch):
    monkeypatch.setattr(get_settings(), "provider_circuit_failure_threshold", 2)
    def fail():
        raise RuntimeError("PRIVATE_PROVIDER_FAILURE_SENTINEL")
    calls = fake_provider(monkeypatch, before_count=fail)
    for index in range(3):
        response = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["input_budget"]["status"] == "unavailable"
        assert payload["input_budget"]["generation_started"] is (False if index < 2 else None)
        assert payload["tokens_used"] is None
        assert "PRIVATE_PROVIDER_FAILURE_SENTINEL" not in response.text
        assert payload["scientific_support_status"] == "not_checked"
    assert [kind for kind, _ in calls] == ["count", "count"]  # no retry, third request is circuit-open


async def test_actual_generation_failure_keeps_successful_count_and_started_receipt(client, complementary, monkeypatch):
    calls = []
    def count_tokens(**kwargs):
        calls.append("count")
        return SimpleNamespace(total_tokens=91)
    def generate_content(**kwargs):
        calls.append("generate")
        raise RuntimeError("PRIVATE_GENERATION_FAILURE_SENTINEL")
    monkeypatch.setattr(rag, "genai_client", lambda: SimpleNamespace(models=SimpleNamespace(
        count_tokens=count_tokens, generate_content=generate_content)))
    response = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert calls == ["count", "generate"]
    assert payload["input_budget"]["status"] == "unavailable"
    assert payload["input_budget"]["input_tokens"] == 91
    assert payload["input_budget"]["generation_started"] is True
    assert payload["tokens_used"] is None and "PRIVATE_GENERATION_FAILURE_SENTINEL" not in response.text
    assert provider_resilience._circuits["gemini_generation"].failures == 1


async def test_local_no_provider_outcome_is_neutral_to_existing_circuit_failures():
    provider_resilience.reset()
    options = dict(timeout_seconds=1, max_attempts=1, failure_threshold=2, cooldown_seconds=60,
                   result_status=rag.provider_status)
    def fail():
        raise RuntimeError("synthetic")
    with pytest.raises(provider_resilience.ProviderUnavailable):
        await provider_resilience.run_blocking("test-neutral", fail, **options)
    neutral = rag.no_source_result()
    actual = await provider_resilience.run_blocking("test-neutral", lambda: neutral, **options)
    assert actual is neutral
    assert provider_resilience._circuits["test-neutral"].failures == 1
    with pytest.raises(provider_resilience.ProviderUnavailable):
        await provider_resilience.run_blocking("test-neutral", fail, **options)
    with pytest.raises(provider_resilience.ProviderUnavailable, match="circuit is open"):
        await provider_resilience.run_blocking("test-neutral", lambda: neutral, **options)
    provider_resilience.reset()


@pytest.mark.parametrize("section,table,expected", [
    ("Experimental methods", False, "methods"), ("Computational details", False, "methods"),
    ("Results and discussion", False, "results"), ("Methods and results", False, "other"),
    ("Results", True, "table"), (None, False, "other"), ("Methods" * 400, False, "other"),
    ("Unrecognized section", 1, "other"),
])
def test_role_hints_are_bounded_navigation_only(section, table, expected):
    assert complementary_retrieval.role_hint(section, table) == expected


@pytest.mark.parametrize("corruption", ["count", "position", "same_source_other_paper", "derived_complement", "byte_mismatch"])
async def test_public_response_rejects_incoherent_pack_context(client, complementary, monkeypatch, corruption):
    fake_provider(monkeypatch)
    response = await client.post("/v1/ask", json={"question": "Explain the pairing mechanism"})
    assert response.status_code == 200, response.text
    payload = response.json()
    if corruption == "count":
        payload["evidence_packing"]["source_group_count"] += 1
    elif corruption == "position":
        payload["sources"][1]["packing_info"]["position"] = 1
    elif corruption == "same_source_other_paper":
        payload["sources"][1]["paper_id"] = "forged:other-paper"
    elif corruption == "derived_complement":
        payload["sources"][1]["evidence_provenance"] = {}
    else:
        payload["input_budget"]["payload_bytes"] += 1
    with pytest.raises(ValidationError):
        AskResponse.model_validate(payload)
