"""Pure API/storage/export projections; no HTTP or database-service claims."""
from copy import deepcopy
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

pytest.importorskip('sqlalchemy')
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'api'))
from services import materials_proposal_export as export, materials_proposal_review as review
from services.materials_proposal_storage import projected_rows
from test_materials_ner_reviewed_proposals import prepared, packet
from test_materials_ner_visual_regions import region_case, make_packet
from test_materials_ner_named_visual import named_case
from ingestion.materials_ner import visual_regions as visual

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_visual_api_does_not_present_optical_offsets_as_original_characters(region_case):
    p=make_packet(*region_case)
    ordinal, evidence=next((i,e) for i,e in enumerate(p['evidence']) if e.get('kind')=='visual_region')
    item=review.passage(p,ordinal,evidence)
    assert review.detail_projection(p,CREATED)['version']=='materials-proposal-review/2'
    assert item['transcription']=='5 K' and item['original_text_quote'] is False
    assert not {'start_char','end_char','quote'} & set(item)
    assert item['asset_path'].endswith(evidence['image_sha256']+'.png')
    rows=projected_rows(p)
    assert rows['evidence'][ordinal]['payload']==evidence
    assert rows['evidence'][ordinal]['block_id']==evidence['block_id']


def test_visual_zip_csv_graph_and_original_image_remain_consistent(region_case):
    p=make_packet(*region_case);before=deepcopy(p);descriptor,raw=export.package(p,CREATED)
    assert p==before and export.package(p,CREATED)==(descriptor,raw)
    assert descriptor['version']=='materials-proposal-export/3'
    with ZipFile(io.BytesIO(raw)) as z:files={n:z.read(n) for n in z.namelist()}
    manifest=json.loads(files['manifest.json']);g=json.loads(files['graph.json'])
    assert g['version']=='materials-proposal-graph/2' and g['visual_evidence_path']=='visual-evidence.json'
    assert json.loads(files['visual-evidence.json'])==p['receipt']['visual_support']
    v=next(e for e in g['evidence'] if e.get('kind')=='visual_region')
    assert hashlib.sha256(files[v['asset_path']]).hexdigest()==v['image_sha256']
    for file in manifest['files']:
        assert len(files[file['name']])==file['bytes']
        assert hashlib.sha256(files[file['name']]).hexdigest()==file['sha256']
    record=list(csv.DictReader(io.StringIO(files['results.csv'].decode())))[0]
    assert record['value']=='5.0' and record['source_value']=='5 K'
    assert v['graph_pointer'].endswith('/payload/quantity')
    assert not g['extraction_provenance']['structured_graph_authored_by_reader']
    assert g['extraction_provenance']['model']=='assistant'
    assert g['extraction_provenance']['reader']['model']=='gpt-6-luna'
    assert not any(g['authority'].values())


@pytest.mark.parametrize('change',['transcription','original_text_offset','image_identity','asset_hash'])
def test_visual_api_refuses_changed_evidence(region_case,change):
    p=make_packet(*region_case);i,e=next((i,e) for i,e in enumerate(p['evidence']) if e.get('kind')=='visual_region')
    e=deepcopy(e)
    if change=='transcription':e['transcription']='7 K'
    elif change=='original_text_offset':e['start_char']=0
    elif change=='image_identity':e['image_sha256']='0'*64
    else:p['receipt']['visual_support']['assets'][0]['asset_id']='0'*64
    with pytest.raises(review.ProposalIntegrityError):review.passage(p,i,e)


def test_export_limit_refuses_whole_visual_package(region_case,monkeypatch):
    p=make_packet(*region_case);monkeypatch.setattr(export,'MAX_UNCOMPRESSED_BYTES',100)
    with pytest.raises(review.ProposalUnavailable):export.package(p,CREATED)


def test_legacy_reader_export_keeps_text_contract_and_exposes_separate_authors(prepared):
    p=packet(prepared);_,raw=export.package(p,CREATED)
    with ZipFile(io.BytesIO(raw)) as z:
        assert set(z.namelist())=={'manifest.json','graph.json','results.csv','README.txt'}
        g=json.loads(z.read('graph.json'))
    assert g['version']=='materials-proposal-graph/1'
    assert review.detail_projection(p,CREATED)['version']=='materials-proposal-review/1'
    assert all('quote' in e and 'transcription' not in e for e in g['evidence'])
    assert g['extraction_provenance']['projection_author']['kind']=='assistant'


def test_unregistered_visual_exports_source_name_value_and_domain_hold(named_case):
    p = make_packet(*named_case, version=visual.NAMED_VERSION)
    _, raw = export.package(p, CREATED)
    with ZipFile(io.BytesIO(raw)) as z:
        g = json.loads(z.read('graph.json'))
        support = json.loads(z.read('visual-evidence.json'))
        row = list(csv.DictReader(io.StringIO(z.read('results.csv').decode())))[0]
    assert support['schema'] == visual.NAMED_VERSION
    assert row['quantity_kind'] == 'unmapped' and row['quantity_name_as_written'] == 'resistive onset'
    assert row['source_value'] == '5 K'
    assert not any(g['authority'].values())
    assert any(e.get('support_schema') == visual.NAMED_VERSION for e in g['evidence'])
    assert 'unregistered_quantity_requires_domain_review' in row['issue_codes_json']
    assert not g['validation']['technical_valid']
