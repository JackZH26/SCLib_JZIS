"""Real SQL/ingestion/adapter HTTP reads; disposable transport is not ANN recall."""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from models.db import Chunk, Material, Paper, PaperWorkMap, Work, get_session_factory
from services import (
    index_generations,
    index_retrieval,
    index_vector_adapter,
    provider_resilience,
    rag,
    rag_evidence,
)
from tests import index_generation_fixtures
from tests.index_generation_fixtures import (
    RESOURCE,
    prepare_generation_items,
    publish_and_activate,
    write_generation,
)


@pytest_asyncio.fixture
async def generation(monkeypatch):
    logical = "http-fixture-" + uuid4().hex
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", logical)
    provider_resilience.reset()
    transport = index_vector_adapter.register_disposable(RESOURCE)
    meta, chunks, staged = await write_generation(monkeypatch, logical_index=logical)
    async with get_session_factory()() as db:
        pin, _, _ = await publish_and_activate(db, staged)
        pin = await index_generations.load_active_generation(db, logical_index=logical)
        members = await index_generations.load_generation_members(db, generation_id=pin["generation_id"])
    yield {"logical": logical, "transport": transport, "meta": meta, "chunks": chunks,
           "pin": pin, "members": members}
    index_vector_adapter.clear_disposable()
    provider_resilience.reset()


def _one_hit(monkeypatch, fixture, member):
    point = deepcopy(fixture["transport"].points[member["vector_id"]])
    monkeypatch.setattr(fixture["transport"], "search", lambda _pin, vectors, *_args: [
        [(deepcopy(point), 0.125)] for _ in vectors])


def _assert_generation(payload, pin):
    metadata = payload["retrieval_generation"]
    assert metadata == {"version": "index-read/1.0.0", "mode": "generation_snapshot",
                        "generation_id": pin["generation_id"], "activation_event_id": pin["activation_event_id"],
                        "manifest_sha256": pin["manifest_sha256"]}
    assert "endpoint_resource" not in str(metadata) and "scientific_acceptance" not in metadata


@pytest.mark.asyncio
async def test_live_search_and_ask_retain_exact_old_fifth_chunk_after_real_five_to_three_replacement(
    client, generation, monkeypatch,
):
    old = next(member for member in generation["members"] if member["snapshot_json"]["chunk_index"] == 4)
    _one_hit(monkeypatch, generation, old)
    _, new_chunks, _ = await write_generation(monkeypatch, logical_index=generation["logical"],
        meta=generation["meta"], count=3, label="replacement")
    async with get_session_factory()() as db:
        actual = (await db.execute(sa.select(Chunk).where(Chunk.paper_id == generation["meta"].paper_id))).scalars().all()
        assert len(actual) == 3 and old["chunk_key"] not in {row.id for row in actual}
        historical = await index_retrieval.hydrate(db, generation["pin"], [member["vector_id"] for member in generation["members"]])
        assert len(historical) == 5
        assert historical[old["vector_id"]].text == old["snapshot_json"]["text"]
    captured = []
    def generate(_question, sources, **_kwargs):
        captured.extend(sources)
        return rag.extractive_fallback(sources)
    monkeypatch.setattr(rag, "generate_answer", generate)
    search = await client.post("/v1/search", json={"query": "unmatchedqueryneedle"})
    ask = await client.post("/v1/ask", json={"question": "unmatchedqueryneedle"})
    assert search.status_code == ask.status_code == 200, (search.text, ask.text)
    match, = search.json()["results"]
    assert match["matched_chunk"] == old["snapshot_json"]["text"]
    assert captured[0].text == old["snapshot_json"]["text"]
    source, = ask.json()["sources"]
    assert source["snippet"] == old["snapshot_json"]["text"]
    assert "replacement" not in ask.text and "replacement" not in search.text
    assert all(chunk.text != captured[0].text for chunk in new_chunks)
    for payload in (ask.json(), search.json()):
        _assert_generation(payload, generation["pin"])
    assert match["evidence_provenance"]["currentness"] == "current"
    assert match["evidence_provenance"]["support_eligible"] is False


@pytest.mark.asyncio
async def test_generation_lexical_fallback_and_real_rollback_restore_old_read_view(client, generation, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise index_vector_adapter.IndexVectorError("synthetic provider unavailable")
    monkeypatch.setattr(index_vector_adapter, "query", unavailable)
    _, _, second = await write_generation(monkeypatch, logical_index=generation["logical"],
        meta=generation["meta"], count=3, label="replacement")
    before = await client.post("/v1/search", json={"query": "old snapshot"})
    assert before.status_code == 200 and "old snapshot" in before.json()["results"][0]["matched_chunk"]
    async with get_session_factory()() as db:
        new, _, _ = await publish_and_activate(db, second, expected_event_id=generation["pin"]["activation_event_id"])
    changed = await client.post("/v1/search", json={"query": "replacement snapshot"})
    assert changed.status_code == 200 and "replacement snapshot" in changed.json()["results"][0]["matched_chunk"]
    async with get_session_factory()() as db:
        old, _, _ = await publish_and_activate(db, generation["pin"], expected_event_id=new["activation_event_id"], action="rollback")
    restored = await client.post("/v1/search", json={"query": "old snapshot"})
    assert restored.status_code == 200 and "old snapshot" in restored.json()["results"][0]["matched_chunk"]
    assert old["generation_id"] == generation["pin"]["generation_id"]
    assert old["activation_event_id"] != generation["pin"]["activation_event_id"]
    _assert_generation(restored.json(), old)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["unknown", "wrong_generation", "content", "vector", "revision"])
async def test_live_ann_cannot_launder_unknown_or_mismatched_member_into_text_or_score(client, generation, monkeypatch, mutation):
    member = generation["members"][0]
    fields = {key: member[key] for key in ("vector_id", "content_sha256", "vector_sha256", "chunk_revision_sha256")}
    if mutation == "unknown":
        fields["vector_id"] = index_generations.vector_id_for(generation["pin"]["generation_id"], "a" * 64)
    elif mutation == "wrong_generation":
        fields["vector_id"] = index_generations.vector_id_for(str(uuid4()), member["chunk_revision_sha256"])
    else:
        fields[{"content": "content_sha256", "vector": "vector_sha256", "revision": "chunk_revision_sha256"}[mutation]] = "0" * 64
    # Deliberately bypass only the provider adapter boundary: HTTP must still
    # compare every returned binding to its actual immutable SQL member.
    neighbor = index_vector_adapter.Neighbor(distance=0.001, **fields)
    monkeypatch.setattr(index_vector_adapter, "query", lambda *_args, **_kwargs: [neighbor])
    for path, body in (("search", {"query": "unmatchedqueryneedle"}), ("ask", {"question": "unmatchedqueryneedle"})):
        response = await client.post("/v1/" + path, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["results" if path == "search" else "sources"] == []
        assert "old snapshot" not in response.text and "0.999" not in response.text
        _assert_generation(response.json(), generation["pin"])


@pytest.mark.asyncio
async def test_generation_profile_config_mismatch_is_rejected_before_cloud_client(generation, monkeypatch):
    real_pin = generation["pin"]
    # Runtime incompatibility is detected by the actual adapter before a
    # provider client is constructed; SQL fallback remains explicitly pinned.
    pin = {**real_pin, "resource": {**real_pin["resource"], "backend": "vertex-public"}}
    calls = []
    monkeypatch.setattr(index_vector_adapter, "_public_clients", lambda *_args: calls.append(True))
    with pytest.raises(index_vector_adapter.IndexVectorError, match="incompatible"):
        index_vector_adapter.query(pin, "synthetic", top_k=3)
    assert calls == []


@pytest.mark.asyncio
async def test_search_rechecks_retained_year_not_mutable_ann_numeric_restriction(client, generation, monkeypatch):
    member = generation["members"][0]
    assert member["snapshot_json"]["year"] is None
    point = deepcopy(generation["transport"].points[member["vector_id"]])
    point["numeric_restricts"] = [{"namespace": "year", "value_int": 2026}]
    monkeypatch.setattr(generation["transport"], "search", lambda _pin, vectors, *_args: [
        [(deepcopy(point), 0.125)] for _ in vectors])
    response = await client.post("/v1/search", json={"query": "unmatchedqueryneedle", "filters": {"year_min": 2026}})
    assert response.status_code == 200 and response.json()["results"] == [], response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", ["work", "restricted_history", "renderer"])
async def test_live_generation_holds_do_not_depend_on_current_chunk_pointer(client, generation, monkeypatch, hold):
    member = generation["members"][0]
    _one_hit(monkeypatch, generation, member)
    async with get_session_factory()() as db:
        if hold == "work":
            work = Work(canonical_title="Synthetic held work", publication_status="corrected")
            db.add(work)
            await db.flush()
            db.add(PaperWorkMap(paper_id=generation["meta"].paper_id, work_id=work.id,
                               match_method="manual", review_status="accepted"))
        elif hold == "restricted_history":
            for item in generation["members"]:
                await rag_evidence.register_chunk_evidence(db, chunk_id=item["chunk_key"], dry_run=False,
                    candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage", "permission_status": "restricted"})
            await db.execute(sa.delete(Chunk).where(Chunk.paper_id == generation["meta"].paper_id))
        else:
            monkeypatch.setattr(rag_evidence, "CURRENT_FACT_RENDERER_VERSION", "synthetic-renderer/changed")
        await db.commit()
    generated = []
    monkeypatch.setattr(rag, "generate_answer", lambda *_args, **_kwargs: generated.append(True))
    searched = await client.post("/v1/search", json={"query": "unmatchedqueryneedle"})
    asked = await client.post("/v1/ask", json={"question": "unmatchedqueryneedle"})
    similar = await client.get("/v1/similar/" + generation["meta"].paper_id)
    assert searched.status_code == asked.status_code == similar.status_code == 200, (searched.text, asked.text, similar.text)
    match, = searched.json()["results"]
    assert match["matched_chunk"] == "" and match["materials"] == []
    assert asked.json()["sources"] == [] and similar.json()["results"] == [] and generated == []
    for response in (searched, asked, similar):
        assert "old snapshot" not in response.text
    descriptor = match["evidence_provenance"]
    if hold == "restricted_history":
        assert descriptor["permission_status"] == "restricted"
    else:
        assert descriptor["currentness"] == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source_hold", "aba"])
async def test_actual_post_llm_barrier_rechecks_live_source_and_activation_event(client, generation, monkeypatch, change):
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    captured = []
    def generate(_question, sources, **_kwargs):
        captured.extend(sources)
        entered.set()
        try:
            assert released.wait(5), "Synthetic provider barrier timed out"
            return rag.extractive_fallback(sources)
        finally:
            finished.set()
    monkeypatch.setattr(rag, "generate_answer", generate)
    request = asyncio.create_task(client.post("/v1/ask", json={"question": "old snapshot"}))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if change == "source_hold":
            async with get_session_factory()() as db:
                await db.execute(sa.update(Paper).where(Paper.id == generation["meta"].paper_id).values(status="corrected"))
                await db.commit()
        else:
            _, _, second = await write_generation(monkeypatch, logical_index=generation["logical"],
                meta=generation["meta"], count=3, label="replacement")
            async with get_session_factory()() as db:
                new, _, _ = await publish_and_activate(db, second, expected_event_id=generation["pin"]["activation_event_id"])
                await publish_and_activate(db, generation["pin"], expected_event_id=new["activation_event_id"], action="rollback")
    finally:
        released.set()
    response = await asyncio.wait_for(request, 5)
    assert await asyncio.to_thread(finished.wait, 1)
    assert captured and response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_mode"] == "abstention" and payload["sources"] == []
    # The new interpretation faithfully echoes the user's query, not source
    # content. Neither answer nor any other returned evidence may leak it.
    assert payload["scientific_query"]["raw_query"] == "old snapshot"
    assert "old snapshot" not in str({key: value for key, value in payload.items() if key != "scientific_query"})
    assert payload["scientific_results"] == []
    assert ("retrieval_generation_changed" if change == "aba" else "retrieval_source_no_longer_eligible") in payload["citation_warnings"]


@pytest.mark.asyncio
async def test_post_llm_material_hold_is_live_even_when_generation_and_snapshot_are_unchanged(client, generation, monkeypatch):
    identifier = "generation-material:" + uuid4().hex
    async with get_session_factory()() as db:
        db.add(Material(id=identifier, formula="Nb", formula_normalized="Nb", records=[], needs_review=False))
        await db.commit()
    original = index_generation_fixtures.corpus
    def linked_corpus(**kwargs):
        meta, record, chunks = original(**kwargs)
        record["material_id"] = identifier
        for chunk in chunks:
            chunk.materials_mentioned = [deepcopy(record)]
            chunk.evidence_candidate["parent_record"] = deepcopy(record)
        return meta, record, chunks
    monkeypatch.setattr(index_generation_fixtures, "corpus", linked_corpus)
    _, _, staged = await write_generation(monkeypatch, logical_index=generation["logical"], meta=generation["meta"])
    async with get_session_factory()() as db:
        active, _, _ = await publish_and_activate(db, staged, expected_event_id=generation["pin"]["activation_event_id"])
    entered, released = threading.Event(), threading.Event()
    captured = []
    def generate(_question, sources, **_kwargs):
        captured.extend(sources)
        entered.set()
        assert released.wait(5), "Synthetic provider barrier timed out"
        return rag.extractive_fallback(sources)
    monkeypatch.setattr(rag, "generate_answer", generate)
    request = asyncio.create_task(client.post("/v1/ask", json={"question": "old snapshot"}))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        async with get_session_factory()() as db:
            await db.execute(sa.update(Material).where(Material.id == identifier).values(needs_review=True))
            await db.commit()
    finally:
        released.set()
    response = await asyncio.wait_for(request, 5)
    assert captured and captured[0].material_evidence[0]["visibility"]["reported_claim_filter_eligible"] is True
    assert response.status_code == 200 and response.json()["answer_mode"] == "abstention", response.text
    assert response.json()["sources"] == [] and "retrieval_source_changed" in response.json()["citation_warnings"]
    _assert_generation(response.json(), active)


@pytest.mark.asyncio
async def test_similar_reads_retained_source_text_and_no_active_generation_is_not_a_fake_empty_success(
    client, generation, monkeypatch,
):
    _, _, _ = await write_generation(monkeypatch, logical_index=generation["logical"], meta=generation["meta"], count=3, label="replacement")
    received = []
    real = index_vector_adapter.query_many
    def capture(pin, texts, **kwargs):
        received.extend(texts)
        return real(pin, texts, **kwargs)
    monkeypatch.setattr(index_vector_adapter, "query_many", capture)
    response = await client.get("/v1/similar/" + generation["meta"].paper_id)
    assert response.status_code == 200, response.text
    assert len(received) == 5 and all("old snapshot" in value for value in received)
    assert response.json()["results"] == []  # This one-paper generation contains no other paper.
    _assert_generation(response.json(), generation["pin"])
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", "empty-fixture-" + uuid4().hex)
    calls = []
    monkeypatch.setattr(index_vector_adapter, "query_many", lambda *_args, **_kwargs: calls.append(True))
    unavailable = await client.get("/v1/similar/" + generation["meta"].paper_id)
    assert unavailable.status_code == 503 and "results" not in unavailable.json() and calls == []


@pytest.mark.asyncio
async def test_similar_hydrates_exact_opaque_target_and_frozen_attribution_not_id_prefix_or_latest_paper(
    client, generation, monkeypatch,
):
    target, target_chunks, _ = await write_generation(monkeypatch, logical_index=generation["logical"], count=2, label="target-old")
    async with get_session_factory()() as db:
        combined = await prepare_generation_items(db, generation["chunks"] + target_chunks)
        staged = await index_generations.stage_generation(db, generation_id=str(uuid4()), items=combined,
            resource=RESOURCE, logical_index=generation["logical"], dry_run=False)
        await db.commit()
        active, _, _ = await publish_and_activate(db, staged, expected_event_id=generation["pin"]["activation_event_id"])
    changed_meta = deepcopy(target)
    changed_meta.title = "Changed current target title"
    await write_generation(monkeypatch, logical_index=generation["logical"], count=1, meta=changed_meta, label="target-replacement")
    response = await client.get("/v1/similar/" + generation["meta"].paper_id)
    assert response.status_code == 200, response.text
    result, = response.json()["results"]
    assert result["paper_id"] == target.paper_id and result["title"] == target.title
    assert result["title"] != changed_meta.title and -1 <= result["similarity"] <= 1
    assert not result["paper_id"].startswith("ig62_")
    _assert_generation(response.json(), active)
    async with get_session_factory()() as db:
        await db.execute(sa.update(Paper).where(Paper.id == target.paper_id).values(status="corrected"))
        await db.commit()
    held = await client.get("/v1/similar/" + generation["meta"].paper_id)
    assert held.status_code == 200 and held.json()["results"] == [], held.text


@pytest.mark.asyncio
async def test_no_active_generation_search_and_ask_are_explicit_legacy_lexical_only(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", "empty-fixture-" + uuid4().hex)
    calls = []
    monkeypatch.setattr(index_vector_adapter, "query", lambda *_args, **_kwargs: calls.append(True))
    for path, field in (("search", "query"), ("ask", "question")):
        response = await client.post("/v1/" + path, json={field: "unmatchedqueryneedle"})
        assert response.status_code == 200, response.text
        assert response.json()["retrieval_generation"]["mode"] == "legacy_lexical_only"
        assert response.json()["retrieval_generation"]["generation_id"] is None
    assert calls == []
