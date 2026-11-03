"""Explicit non-serving Search/Ask over fresh synthetic SQL, never acceptance."""
import json
import os
from types import SimpleNamespace

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
import sqlalchemy as sa

from config import get_settings
from models.db import get_session_factory
from models.index_read import retrieval_read_metadata
from models.search import SearchRequest, AskRequest
from routers.deps import Identity
from routers.ask import _ask
from services import content_search, content_scientific_lookup, query_embedding, rag
from services import retrieval_content, retrieval_members, content_answer_evidence
from services.candidate_context import CandidateContext
from services.candidate_http import create_private_app
from services.candidate_runtime import CandidateRetriever
from tests.test_retrieval_candidate import candidate as candidate
from tests.test_native_publisher import bridge as bridge, prepared
from native_publisher.producer import publish_prepared
from tests.test_retrieval_activation import prepared_build
from tests.test_index_generations import db_session as db_session
from tests.test_research_freeze import state

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST') != '1',
    reason='Requires fresh owned PostgreSQL/vector services')]


@pytest_asyncio.fixture(loop_scope='function')
async def flows(candidate, bridge, db_session, tmp_path, monkeypatch):
    old, pin, _, _ = candidate
    paper, chunks, inputs = prepared(tmp_path)
    published = await publish_prepared(paper, chunks, [], archive_root=tmp_path, inputs=inputs,
        logical_index=pin.logical_index, dry_run=False)
    content = await retrieval_content.stage_native_content(db_session, base_content_id=pin.content_id,
        publication_ids=[published['publication']['publication_id']], dry_run=False)
    refs = await retrieval_content.source_reference_page(db_session, content_id=content['content_id'])
    await retrieval_content.append_content_partition(db_session, content_id=content['content_id'],
        partition_id=0, references=refs, dry_run=False)
    await retrieval_content.seal_content(db_session, content_id=content['content_id'], dry_run=False)
    built = await prepared_build(db_session, content_id=content['content_id'], logical_index=pin.logical_index)
    await db_session.commit()
    reader = CandidateRetriever(get_session_factory(), old._transport, build_id=built['build_id'],
        validation_id=built['validation_id'], expected_database=pin.database_name)
    new_pin = await reader.pin(logical_index=pin.logical_index)
    await reader.prepare(new_pin)
    monkeypatch.setattr(get_settings(), 'retrieval_logical_index', pin.logical_index)
    monkeypatch.setattr(query_embedding, 'embed_query', lambda *args: [0.25] * 768)
    calls = []
    def generate(question, sources, **kwargs):
        calls.append((question, len(sources)))
        return rag.extractive_fallback(sources, evidence_packing=kwargs['evidence_packing'])
    monkeypatch.setattr(rag, 'generate_answer', generate)
    try:
        yield reader, new_pin, paper.meta.paper_id, calls
    finally:
        await reader.close()


async def test_shared_search_and_ask_project_explicit_private_identity_without_history(flows, db_session):
    reader, pin, paper_id, calls = flows
    before = await state(db_session)
    app = create_private_app(reader, pin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://owned-loopback') as client:
        search = await client.post('/candidate/search', json={'query': 'synthetic', 'top_k': 3})
        ask = await client.post('/candidate/ask', json={'question': 'synthetic', 'max_sources': 3})
    assert search.status_code == ask.status_code == 200
    for response in (search.json(), ask.json()):
        assert response['scope'] == 'owned_restore_not_activated'
        assert response['public_route_or_scientific_acceptance'] is response['history_writes'] is response['quota_consumed'] is False
        read = response['response']['retrieval_generation']
        assert read['version'] == 'sclib-engineering-candidate-pin/1.0.0' and read['build_id'] == pin.build_id
        assert 'activation_event_id' not in read
    assert any(row['paper_id'] == paper_id for row in search.json()['response']['results'])
    assert any(row['paper_id'] == paper_id for row in ask.json()['response']['sources'])
    assert ask.json()['response']['history']['status'] == 'not_requested' and calls
    assert await state(db_session) == before


async def test_public_orchestrators_and_receipts_still_refuse_candidate(flows, db_session):
    reader, pin, _, _ = flows
    guest = Identity(user=None, guest_ip='127.0.0.1', guest_remaining=1)
    with pytest.raises(ValueError):
        await content_search.search(reader, SearchRequest(query='synthetic'), guest)
    with pytest.raises(ValueError):
        await _ask(AskRequest(question='synthetic'), SimpleNamespace(), guest, db_session, reader=reader)
    with pytest.raises(ValueError):
        retrieval_read_metadata(pin)
    with pytest.raises(content_answer_evidence.ContentAnswerEvidenceError):
        content_answer_evidence.capture_inputs(request=AskRequest(question='synthetic'), backend_pin=pin)


async def test_private_numeric_query_does_not_hide_positive_parent_inventory(flows):
    reader, pin, _, calls = flows
    async with AsyncClient(transport=ASGITransport(app=create_private_app(reader, pin)), base_url='http://owned-loopback') as client:
        response = await client.post('/candidate/search', json={'query': 'What is the Tc of MgB2?'})
    assert response.status_code == 200
    assert response.json()['response']['scientific_lookup']['status'] == 'unavailable' and not calls


async def test_zero_parent_branch_is_explicit_and_provider_free(flows, monkeypatch):
    # Controlled synthetic inventory; actual corpus parent count is a separate
    # operator measurement and is never established by this mock.
    reader, pin, _, calls = flows
    async def no_parents(*args):
        return []
    monkeypatch.setattr(content_scientific_lookup, '_derived_ids', no_parents)
    async with AsyncClient(transport=ASGITransport(app=create_private_app(reader, pin)), base_url='http://owned-loopback') as client:
        for route, payload in [('search', {'query': 'What is the Tc of MgB2?'}),
                               ('ask', {'question': 'What is the Tc of MgB2?'})]:
            response = await client.post('/candidate/' + route, json=payload)
            assert response.status_code == 200
            body = response.json()['response']
            assert body['scientific_lookup']['status'] == 'completed' and not body['scientific_results']
            assert 'declared_content_no_extraction_parents' in body['scientific_lookup']['reason_codes']
    assert not calls


async def test_private_context_cannot_be_used_as_authenticated_or_after_marker_change(flows, db_session):
    reader, pin, _, _ = flows
    context = CandidateContext(reader, pin)
    with pytest.raises(ValueError, match='authenticated'):
        await _ask(AskRequest(question='synthetic'), SimpleNamespace(),
            Identity(user=SimpleNamespace(id='synthetic-user'), guest_ip=None, guest_remaining=None),
            db_session, reader=reader, candidate_context=context)
    await db_session.execute(sa.text("UPDATE sclib_pgvector_rehearsal.source SET manifest=:bad"), {'bad': '0' * 64})
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=create_private_app(reader, pin)), base_url='http://owned-loopback') as client:
        response = await client.post('/candidate/search', json={'query': 'synthetic'})
    assert response.status_code == 503
