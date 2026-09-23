"""Real SQL/HTTP diversity regressions; synthetic inputs are not scientific evidence.

Five retained catalogue papers share one active immutable generation. Four
have a database Work mapping; the fifth is an unrelated selection control.
Only the external provider/ANN transport is substituted. No resolver, packing,
currentness, lineage, or generation-membership service is mocked.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio

from config import get_settings
from models.db import PaperWorkMap, Work, get_session_factory
from services import index_generations, index_vector_adapter, provider_resilience, rag, retrieval
from tests import index_generation_fixtures as fixtures


@pytest_asyncio.fixture
async def multi_paper_generation(monkeypatch):
    logical = "complementary-diversity-" + uuid4().hex
    monkeypatch.setattr(get_settings(), "retrieval_logical_index", logical)
    provider_resilience.reset()
    index_vector_adapter.clear_disposable()
    transport = index_vector_adapter.register_disposable(fixtures.RESOURCE)
    monkeypatch.setattr(fixtures.indexer, "_session_factory", get_session_factory)

    def no_cloud():
        raise AssertionError("Unexpected cloud index access")

    monkeypatch.setattr(fixtures.indexer, "_index", no_cloud)
    papers, chunks = [], []
    for position in range(5):
        meta, record, units = fixtures.corpus(count=3, label=f"distinct-catalogue-source-{position}")
        for index, chunk in enumerate(units):
            chunk.section = ["Results", "Methods", "Table 1"][index]
            chunk.has_table = index == 2
            # These are synthetic development passages, not an ingestion
            # authorization or proof of an authenticated publisher original.
            chunk.evidence_candidate = {
                "version": "rag-evidence/1.0.0", "chunk_kind": "original_passage",
                "rendering_version": "sclib-section-chunker/2.0.0",
            }
        await fixtures.indexer.upsert_aps_paper_with_chunks(meta, units, [record])
        papers.append(meta)
        chunks.extend(units)

    async with get_session_factory()() as db:
        items = await fixtures.prepare_generation_items(db, chunks)
        staged = await index_generations.stage_generation(
            db, generation_id=str(uuid4()), items=items, resource=deepcopy(fixtures.RESOURCE),
            logical_index=logical, dry_run=False,
        )
        await db.commit()
        await fixtures.publish_and_activate(db, staged)
        pin = await index_generations.load_active_generation(db, logical_index=logical)
        members = await index_generations.load_generation_members(db, generation_id=pin["generation_id"])
        work = Work(id=uuid4(), canonical_title="Synthetic shared Work; selection grouping only")
        db.add(work)
        await db.flush()
        work_id = str(work.id)
        for index, paper in enumerate(papers[:4]):
            db.add(PaperWorkMap(
                paper_id=paper.paper_id, work_id=work.id,
                relation_type=["canonical_version", "preprint", "published_version", "supplement"][index],
                match_method="manual", review_status="accepted",
            ))
        await db.commit()

    # Real vector observations and SQL member hashes remain mandatory. Return
    # one actual point per catalogue paper; real SQL expansion supplies roles.
    seeds = [next(member for member in members if member["paper_id"] == paper.paper_id
                  and member["snapshot_json"]["chunk_index"] == 0) for paper in papers]
    points = [deepcopy(transport.points[member["vector_id"]]) for member in seeds]
    monkeypatch.setattr(transport, "search", lambda _pin, vectors, *_, **_kwargs: [
        [(deepcopy(point), 0.1 + index / 100) for index, point in enumerate(points)] for _ in vectors
    ])

    async def no_lexical(*args, **kwargs):
        return []

    monkeypatch.setattr(retrieval, "lexical_search", no_lexical)
    calls = []

    def count_tokens(**kwargs):
        calls.append(("count", kwargs))
        return SimpleNamespace(total_tokens=100)

    def generate_content(**kwargs):
        calls.append(("generate", kwargs))
        return SimpleNamespace(text="The supplied excerpts do not establish an answer to this question.",
                               usage_metadata=SimpleNamespace(total_token_count=130))

    monkeypatch.setattr(rag, "genai_client", lambda: SimpleNamespace(models=SimpleNamespace(
        count_tokens=count_tokens, generate_content=generate_content)))
    try:
        yield {"papers": papers, "members": members, "work_id": work_id, "calls": calls, "pin": pin}
    finally:
        index_vector_adapter.clear_disposable()
        provider_resilience.reset()


@pytest.mark.parametrize("mapping_status", ["accepted", "pending", "rejected"])
async def test_http_only_accepted_work_maps_share_the_three_excerpt_diversity_limit(
    client, multi_paper_generation, mapping_status,
):
    fixture = multi_paper_generation
    related = {paper.paper_id for paper in fixture["papers"][:4]}
    control = fixture["papers"][4].paper_id
    if mapping_status != "accepted":
        async with get_session_factory()() as db:
            for paper_id in related:
                mapping = await db.get(PaperWorkMap, paper_id)
                mapping.review_status = mapping_status
            await db.commit()

    response = await client.post("/v1/ask", json={
        "question": "Explain the pairing mechanism", "language": "en", "max_sources": 20,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["retrieval_generation"]["generation_id"] == fixture["pin"]["generation_id"]
    assert [kind for kind, _ in fixture["calls"]] == ["count", "generate"]
    assert fixture["calls"][0][1]["contents"] == fixture["calls"][1][1]["contents"]
    sources, summary = body["sources"], body["evidence_packing"]
    related_sources = [source for source in sources if source["paper_id"] in related]
    control_sources = [source for source in sources if source["paper_id"] == control]
    assert len(control_sources) == 3
    assert summary["candidate_count"] == 15
    assert summary["max_per_work"] == 3
    assert [source["index"] for source in sources] == list(range(1, len(sources) + 1))
    assert len({source["packing_info"]["chunk_id"] for source in sources}) == len(sources)
    assert str(fixture["work_id"]) not in response.text  # raw Work identity remains private

    if mapping_status == "accepted":
        assert len(related_sources) == 3  # NOT three from each of four source papers
        assert len({source["paper_id"] for source in related_sources}) == 3
        assert len({source["packing_info"]["source_group_id"] for source in related_sources}) == 3
        assert len({source["packing_info"]["source_snapshot_sha256"] for source in related_sources}) == 3
        assert len({source["packing_info"]["diversity_group_id"] for source in related_sources}) == 1
        assert {source["packing_info"]["group_basis"] for source in related_sources} == {"accepted_work_mapping"}
        assert Counter(source["packing_info"]["selection_reason"] for source in related_sources) == {
            "source_diversity": 1, "source_coverage": 2,
        }
        assert summary["reason_counts"] == {"work_limit": 9}
        assert (summary["selected_count"], summary["source_group_count"], summary["diversity_group_count"]) == (6, 4, 2)
    else:
        assert len(related_sources) == 12
        assert len({source["packing_info"]["diversity_group_id"] for source in related_sources}) == 4
        assert {source["packing_info"]["group_basis"] for source in related_sources} == {"source_snapshot"}
        assert summary["reason_counts"] == {}
        assert (summary["selected_count"], summary["source_group_count"], summary["diversity_group_count"]) == (15, 5, 5)

    by_id = {member["vector_id"]: member for member in fixture["members"]}
    prompt = fixture["calls"][0][1]["contents"][0]["parts"][0]["text"]
    for source in sources:
        item = source["packing_info"]
        member = by_id[item["chunk_id"]]
        assert member["snapshot_json"]["text"] in prompt
        assert source["paper_id"] == member["paper_id"]
        assert item["source_snapshot_sha256"] == member["source_snapshot_sha256"]
        assert source["evidence_provenance"]["content_sha256"] == member["content_sha256"]
        assert source["evidence_provenance"]["independent_evidence"] is False
        assert item["scientific_acceptance"] is False
    assert summary["independent_support_count"] is None
    assert summary["independence_status"] == "independence_not_established"
    assert summary["scientific_acceptance"] is False
    assert body["scientific_support_status"] != "supported"


async def test_http_diversity_precedes_more_versions_when_only_three_citations_fit(client, multi_paper_generation):
    fixture = multi_paper_generation
    response = await client.post("/v1/ask", json={
        "question": "Explain the pairing mechanism", "max_sources": 3,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    sources = body["sources"]
    related = {paper.paper_id for paper in fixture["papers"][:4]}
    assert len(sources) == 3
    assert sources[0]["paper_id"] in related
    assert sources[1]["paper_id"] == fixture["papers"][4].paper_id
    assert sources[2]["paper_id"] in related
    assert sources[0]["paper_id"] != sources[2]["paper_id"]
    assert [source["packing_info"]["selection_reason"] for source in sources] == [
        "source_diversity", "source_diversity", "source_coverage",
    ]
    assert body["evidence_packing"]["diversity_group_count"] == 2
    assert body["evidence_packing"]["independent_support_count"] is None
    assert body["evidence_packing"]["reason_counts"]["chunk_limit"] > 0
