"""Authenticated disposable HTTP reads of source-owned scientific proposals."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text

from config import get_settings
from models.db import get_engine
from services import materials_proposal_review as service
from tests.research_access_helpers import research_operator, research_user, revoke_research_grant

REPO=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(REPO/'scripts'),str(REPO/'ingestion'),str(REPO/'ingestion/tests')]
from materials_ner_db_bridge_v2 import process
from ingestion.materials_ner.proposals import import_packet
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.worker import configuration,run_one
from test_materials_ner_formula_missingness import fixture
from test_materials_ner_inventory_v2 import SequenceProvider

PREFIX='/v1/research/materials-ner'


@pytest.fixture(scope='module')
def retained(tmp_path_factory):
    root=tmp_path_factory.mktemp('private-proposal-review')
    bundle,inventory,raw=fixture();store=Store(root)
    bundle.work_id=inventory.work_id=raw['work_id']='arxiv:0001.00001'
    checksum,_=save_bundle(root,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=checksum,config=configuration(workflow='inventory_v12'))
    run_one(store,job_id=job,provider_override=SequenceProvider([inventory.model_dump(),raw]))
    return import_packet(store,job)


@pytest_asyncio.fixture
async def proposals(retained,monkeypatch):
    # The parent conftest has already verified the disposable service capability.
    monkeypatch.setenv('MATERIALS_NER_REVIEW_ENABLED','true');get_settings.cache_clear()
    await process(dict(action='initialize'),get_settings().database_url)
    await process(dict(action='ingest',packet=retained),get_settings().database_url)
    try:yield retained
    finally:
        async with get_engine().begin() as conn:await conn.execute(text('DROP SCHEMA materials_ner_v1 CASCADE'))
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_disabled_anonymous_and_explicit_role_boundaries(client,proposals,monkeypatch):
    monkeypatch.setenv('MATERIALS_NER_REVIEW_ENABLED','false');get_settings.cache_clear()
    assert (await client.get(PREFIX+'/capabilities')).status_code==404
    monkeypatch.setenv('MATERIALS_NER_REVIEW_ENABLED','true');get_settings.cache_clear()
    admin=await research_user(is_admin=True)
    publisher=await research_operator(role='publisher')
    reviewer=await research_operator(role='reviewer')
    for headers,status in [({},401),(admin['headers'],403),(publisher['headers'],403),(reviewer['headers'],200)]:
        r=await client.get(PREFIX+'/capabilities',headers=headers)
        assert r.status_code==status,r.text
        assert r.headers['cache-control']=='private, no-store'
    assert not any(r.json()['authority'].values())
    await revoke_research_grant(grant_id=reviewer['grant_id'],revoked_by=reviewer['grantor_id'])
    assert (await client.get(PREFIX+'/runs',headers=reviewer['headers'])).status_code==403


@pytest.mark.asyncio
async def test_null_formula_graph_source_coordinates_and_page_parity(client,proposals):
    actor=await research_operator();headers=actor['headers'];run=proposals['run_id']
    listed=await client.get(PREFIX+'/runs',params={'work_id':proposals['work_id']},headers=headers)
    assert listed.status_code==200,listed.text
    assert listed.json()['items'][0]['run_id']==run
    r=await client.get(f'{PREFIX}/runs/{run}',params={'limit':1},headers=headers)
    assert r.status_code==200,r.text
    data=r.json();assert data['run']['packet_sha256']==proposals['packet_hash']
    assert data['entities']['samples'][0]['payload']['formula_raw'] is None
    assert data['entities']['samples'][0]['payload']['identity_resolution']=='unresolved'
    assert data['entities']['samples'][0]['payload']['formula_unavailability']['status']=='ambiguous'
    ids=[data['results'][0]['local_id']]
    if data['next_cursor']:
        next_page=(await client.get(f'{PREFIX}/runs/{run}',params={'after':data['next_cursor']},headers=headers)).json()
        ids.extend(x['local_id'] for x in next_page['results'])
    assert sorted(ids)==sorted(x['local_id'] for x in proposals['rows']['results'])
    selected=ids[0];items=[];after=-1
    while True:
        ev=await client.get(f'{PREFIX}/runs/{run}/evidence',params={'result_id':selected,'limit':2,'after':after},headers=headers)
        assert ev.status_code==200,ev.text
        body=ev.json();items.extend(body['items'])
        if body['next_cursor'] is None:break
        after=body['next_cursor']
    assert len(items)==body['total_count'] and len({x['ordinal'] for x in items})==len(items)>0
    blocks={b['id']:b for b in proposals['bundle']['blocks']}
    for x in items:assert x['quote']==blocks[x['block_id']]['text'][x['start_char']:x['end_char']]
    serialized=json.dumps(data)
    assert 'raw_output' not in serialized and 'prompt_sha256' not in serialized and 'material_id' not in serialized
    assert data==json.loads(json.dumps(data)) and not any(data['authority'].values())


@pytest.mark.parametrize('suffix', ['/runs?limit=26','/runs?work_id=anything','/runs?after=bad',
    '/runs/bad','/runs/'+('a'*64),'/runs/'+('a'*64)+'/evidence?result_id=x&after=-2'])
@pytest.mark.asyncio
async def test_invalid_and_missing_queries_are_bounded(client,proposals,suffix):
    actor=await research_operator()
    r=await client.get(PREFIX+suffix,headers=actor['headers'])
    assert r.status_code in {400,404,422} and r.headers['cache-control']=='private, no-store'
    assert proposals['bundle']['title'] not in r.text


@pytest.mark.parametrize('sql',[
    "UPDATE materials_ner_v1.results SET payload='{}'::jsonb",
    "UPDATE materials_ner_v1.states SET review_status=CASE review_status WHEN 'pending_review' THEN 'quarantined' ELSE 'pending_review' END",
    "UPDATE materials_ner_v1.evidence SET block_id='unrelated'",
])
@pytest.mark.asyncio
async def test_inconsistent_storage_never_returns_scientific_detail(client,proposals,sql):
    actor=await research_operator()
    async with get_engine().begin() as conn:await conn.execute(text(sql))
    r=await client.get(f"{PREFIX}/runs/{proposals['run_id']}",headers=actor['headers'])
    assert r.status_code==409 and 'sample' not in r.text.lower()


@pytest.mark.asyncio
async def test_role_revocation_during_read_prevents_egress(client,proposals,monkeypatch):
    actor=await research_operator();original=service.run_detail
    async def revoke_after_projection(*args,**kwargs):
        data=await original(*args,**kwargs)
        await revoke_research_grant(grant_id=actor['grant_id'],revoked_by=actor['grantor_id'])
        return data
    monkeypatch.setattr(service,'run_detail',revoke_after_projection)
    r=await client.get(f"{PREFIX}/runs/{proposals['run_id']}",headers=actor['headers'])
    assert r.status_code==403 and proposals['bundle']['title'] not in r.text


@pytest.mark.asyncio
async def test_missing_schema_is_not_reported_as_an_empty_dataset(client,monkeypatch):
    monkeypatch.setenv('MATERIALS_NER_REVIEW_ENABLED','true');get_settings.cache_clear()
    try:
        actor=await research_operator()
        r=await client.get(PREFIX+'/runs',headers=actor['headers'])
        assert r.status_code==404
    finally:get_settings.cache_clear()


def test_source_quote_mismatch_is_refused_without_retyping(retained):
    ev=deepcopy(retained['evidence'][0]);ev['quote_sha256']='0'*64
    with pytest.raises(service.ProposalIntegrityError,match='quote_mismatch'):
        service.passage(retained,0,ev)
