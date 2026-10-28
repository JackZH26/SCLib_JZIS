"""Private projector projection and export; synthetic, attributed test inputs."""
from copy import deepcopy
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile
import pytest

REPO=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(REPO/'ingestion'),str(REPO/'ingestion/tests'),str(REPO/'scripts')]
from test_materials_ner_source_projector import queued,Fake
from test_materials_ner_reviewed_proposals import prepared,graph
from test_materials_ner_projector_proposals import terminal,findings
from ingestion.materials_ner import source_projector,projector_proposals
from services import materials_projector_review as context,materials_proposal_review as review,materials_proposal_export as export

NOW=datetime(2026,10,26,tzinfo=timezone.utc)


@pytest.fixture
def packet(terminal,tmp_path):
    store,job,bundle,_=terminal
    return projector_proposals.build(store.root,job,review_findings=findings(tmp_path/'findings.json',store,job,bundle))


def test_context_retains_assistant_findings_and_omissions_without_local_paths(packet):
    original=deepcopy(packet);value=context.project(packet)
    assert value['graph_authorship']==value['model']=='gpt-6-luna'
    assert value['raw_result_objects']==value['retained_result_rows']==1
    assert value['source_completeness_findings']==1 and value['findings_author']['kind']=='assistant'
    assert all(value[k] is False for k in ['independent_review','paper_completed','scientific_acceptance','ml_training_eligible'])
    assert '/Users/' not in json.dumps(value) and 'input_pins' not in json.dumps(value)
    assert packet==original
    detail=review.detail_projection(packet,NOW)
    assert detail['coverage']['projector_review']==value


@pytest.mark.parametrize('change',['model','provider','terminal','raw','scope','graph','findings','approval','completion','omissions'])
def test_bad_embedded_context_is_rejected_before_display(packet,change):
    p=deepcopy(packet);r=p['receipt'];provenance=r['projector_provenance']
    if change=='model':r['graph_authorship']='assistant'
    elif change=='provider':provenance['provider_json']+='\n'
    elif change=='terminal':provenance['terminal_json']+='\n'
    elif change=='raw':p['raw_output']+='\n'
    elif change=='scope':provenance['scope_json']+='\n'
    elif change=='graph':r['extraction']['results'][0]['quantity']['value']=9.0
    elif change=='findings':r['review_findings']['text']+='\n'
    elif change=='approval':r['scientific_acceptance']=True
    elif change=='completion':r['paper_review']['scope_review_complete']=True
    elif change=='omissions':r['paper_review']['source_completeness_findings']=[]
    with pytest.raises(review.ProposalIntegrityError):review.detail_projection(p,NOW)
    with pytest.raises(review.ProposalIntegrityError):export.package(p,NOW)


def test_unparsed_graph_is_diagnostic_file_and_header_only_csv(queued):
    store,_,job,bundle,_=queued;g=graph(bundle);g['results'][0]['protocol_id']='missing'
    fake=Fake(g);source_projector.run(store,job,provider_override=fake)
    p=projector_proposals.build(store.root,job)
    value=context.project(p)
    assert value['disposition']=='unparsed_model_graph' and value['raw_result_objects']==1 and value['retained_result_rows']==0
    assert value['terminal']['error_code']=='projector_schema_invalid' and value['terminal']['diagnostic']['details']
    descriptor,raw=export.package(p,NOW)
    assert descriptor['version']=='materials-proposal-export/4' and descriptor['counts']['results']==0
    with ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read('raw-model-graph.json')==fake.text.encode()
        assert len(archive.read('results.csv').decode().splitlines())==1
        rendered=json.loads(archive.read('graph.json'))
        assert rendered['coverage']['projector_review']==value
        assert not rendered['entities']['results']


def test_full_export_preserves_original_model_bytes_and_source_findings(packet):
    descriptor,raw=export.package(packet,NOW)
    assert export.package(packet,NOW)==(descriptor,raw)
    with ZipFile(io.BytesIO(raw)) as z:
        assert set(z.namelist())=={'README.txt','graph.json','manifest.json','raw-model-graph.json','results.csv'}
        assert z.read('raw-model-graph.json')==packet['raw_output'].encode()
        graph=json.loads(z.read('graph.json'))
        assert graph['coverage']['projector_review']['source_completeness_findings']==1
        assert graph['raw_model_graph_path']=='raw-model-graph.json'
        manifest=json.loads(z.read('manifest.json'))
        for entry in manifest['files']:
            assert export.sha(z.read(entry['name']))==entry['sha256']
