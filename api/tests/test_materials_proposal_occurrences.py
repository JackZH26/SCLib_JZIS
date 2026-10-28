"""Held candidates remain visible through authenticated review and ZIP export."""
from copy import deepcopy
from datetime import datetime,timezone
import csv,io,json,sys
from pathlib import Path
import pytest
from config import get_settings
from services import materials_proposal_review as review,materials_proposal_export as export
from services.materials_proposal_storage import digest
from tests.test_materials_proposal_review import proposals,retained,PREFIX
from tests.test_materials_proposal_export import unpack
from tests.research_access_helpers import research_operator

REPO=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(REPO/'scripts'),str(REPO/'ingestion'),str(REPO/'ingestion/tests')]
from materials_ner_db_bridge_v2 import process
from test_materials_ner_observation_holds import requested
from test_materials_ner_staged_revision import execute


@pytest.fixture(scope='module')
def held_packet(tmp_path_factory):
    args=requested(tmp_path_factory.mktemp('held-proposal'))
    _,packet=execute(*args)
    return packet


def test_original_item_and_source_hold_survive_complete_export(held_packet):
    original=deepcopy(held_packet);created=datetime(2026,10,23,tzinfo=timezone.utc)
    view=review.detail_projection(held_packet,created,limit=1)
    accounting=view['coverage']['source_item_accounting']
    assert accounting['original_item_count']==5 and accounting['original_status_counts']=={'emitted':4,'held':1}
    history=accounting['observation_hold_history'];assert len(history)==1
    assert history[0]['observation_id']=='item:I2'
    assert history[0]['original_observation']['inventory_item_ids']==['I2']
    assert not history[0]['scientific_exclusion_approved'] and history[0]['reviewer_kind']=='model'
    _,raw=export.package(held_packet,created);files,_,graph=unpack(raw)
    assert graph['coverage']['source_item_accounting']==accounting
    rows=list(csv.DictReader(io.StringIO(files['results.csv'].decode(),newline='')))
    assert len(rows)==4 and 'item:I2' not in {row['result_id'] for row in rows}
    assert all(not value for value in graph['authority'].values()) and held_packet==original


def test_original_hold_is_not_recovered_by_an_additional_result_alias(retained):
    packet=deepcopy(retained);item=packet['receipt']['inventory']['items'][0]['id']
    packet['receipt']['inventory_coverage']={'result_mapping':{'additional-result':['additional:1']},
        'unextracted_items':[{'item_id':item,'reason':'unresolved','explanation':'Synthetic original-item hold.'}]}
    packet['run_id']=digest(packet['receipt'])
    a=review.source_item_accounting(packet)
    row=next(x for x in a['original_items'] if x['item_id']==item)
    assert row['status']=='held' and row['result_ids']==[]
    assert len(a['additional_result_mappings'])==1 and not a['independent_recall_denominator']


def test_hold_quote_must_match_its_original_source(held_packet):
    changed=deepcopy(held_packet)
    changed['receipt']['revision_audit']['changes'][0]['source_quotes'][0]['quote']+=' invented'
    changed['run_id']=digest(changed['receipt'])
    with pytest.raises(review.ProposalIntegrityError,match='hold_source_mismatch'):
        review.source_item_accounting(changed)


@pytest.mark.asyncio
async def test_authenticated_pages_and_csv_companion_agree_on_held_results(client,proposals,held_packet):
    await process(dict(action='ingest',packet=held_packet),get_settings().database_url)
    actor=await research_operator(role='reviewer');url=f"{PREFIX}/runs/{held_packet['run_id']}"
    response=await client.get(url,params={'limit':1},headers=actor['headers'])
    assert response.status_code==200,response.text
    page=response.json();a=page['coverage']['source_item_accounting']
    assert a['original_status_counts']=={'emitted':4,'held':1} and len(page['results'])==1
    descriptor=(await client.get(url+'/export',headers=actor['headers'])).json()
    package=await client.get(url+'/export/package',params={'expected_sha256':descriptor['sha256']},headers=actor['headers'])
    assert package.status_code==200 and package.headers['cache-control']=='private, no-store'
    _,_,graph=unpack(package.content)
    assert graph['coverage']['source_item_accounting']==a
    assert graph['run']['result_count']==4 and not any(graph['authority'].values())
