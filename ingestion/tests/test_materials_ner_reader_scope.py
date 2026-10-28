"""Explicit visual ownership without expected values or changes to fixed reading instructions."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ingestion.materials_ner import reader_scope, reviewed_reader as reader, reviewed_proposals as projection
from ingestion.materials_ner import visual_regions
from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.sources import save_bundle,sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.proposals import verify_packet
from test_materials_ner_reviewed_reader import Fake,scope_fixture
from test_materials_ner_reviewed_proposals import prepared,reframe,AUTHOR,NOW
from test_materials_ner_visual_regions import region_case


def upgraded(case,role='target',rect=None):
    s=deepcopy(case['scope']);s.update(schema=reader_scope.VERSION,
        visual_scope=[dict(image_id='P1',role=role,region=rect or [0,0,1,1])])
    capture=case['assets'][0]['capture'];raw=canonical(capture).encode()
    s['image_capture']=dict(path='/synthetic/capture.json',sha256=sha(raw),bytes=len(raw))
    return s,capture


def test_renderer_names_page_and_scope_without_inventing_scientific_labels(region_case):
    case,_=region_case;s,c=upgraded(case)
    units=reader_scope.visual_units(s,c,case['bundle'])
    assert units[0]['pdf_page']==1 and units[0]['original_block_ids']==[case['bundle'].blocks[0].id]
    text=reader_scope.render(s,c,case['bundle'])
    assert 'explicit printed labels' in text and 'share a method, criterion or condition' in text
    assert '5 K' not in text and 'transcription' not in text and 'Synthetic explicit binding' not in text


@pytest.mark.parametrize('change',['missing_page','unknown_page','overlap','conflicting_role','bad_bounds','nan',
    'wrong_role','extra_hint','context_text','partial_text','wrong_capture'])
def test_visual_scope_rejects_ambiguous_or_unbound_ownership(region_case,change):
    case,_=region_case;s,c=upgraded(case);u=s['visual_scope'][0]
    if change=='missing_page':s['visual_scope']=[]
    elif change=='unknown_page':u['image_id']='P2'
    elif change=='overlap':s['visual_scope'].append(deepcopy(u))
    elif change=='conflicting_role':s['visual_scope'].append(dict(u,role='context'))
    elif change=='bad_bounds':u['region']=[1,0,0,1]
    elif change=='nan':u['region'][0]=float('nan')
    elif change=='wrong_role':u['role']='ignore'
    elif change=='extra_hint':u['expected_tc']='5 K'
    elif change=='context_text':s['passages'][0]['role']='context'
    elif change=='partial_text':s['passages'][0]['start_char']=1
    else:c=deepcopy(c);c['pages'][0]['pdf_page']=2
    with pytest.raises(ValueError):reader_scope.visual_units(s,c,case['bundle'])


def test_adjacent_regions_have_no_overlap_and_context_cannot_supply_label(region_case):
    case,_=region_case;s,c=upgraded(case,'context')
    support=visual_regions.build(**case);binding=visual_regions.resolve(support,case['bundle'],case['manifest'],case['scope'],case['extraction'])[0]
    with pytest.raises(ValueError,match='outside_target_region'):reader_scope.require_target(binding,s,c,case['bundle'])
    s['visual_scope']=[dict(image_id='P1',role='target',region=[0,0,.5,1]),dict(image_id='P1',role='context',region=[.5,0,1,1])]
    assert len(reader_scope.visual_units(s,c,case['bundle']))==2
    with pytest.raises(ValueError,match='outside_target_region'):reader_scope.require_target(binding,s,c,case['bundle'])


def test_v1_prompt_and_text_only_v2_preserve_exact_source_positions(tmp_path):
    path=scope_fixture(tmp_path/'source');old=reader.prepare_scope(path);s=json.loads(path.read_text())
    s.update(schema=reader_scope.VERSION,visual_scope=[]);new_path=tmp_path/'new.json';new_path.write_text(canonical(s))
    new=reader.prepare_scope(new_path)
    assert old['schema']==new['schema']==reader.protocol()[1]
    assert old['prompt'].startswith(reader.protocol()[0]) and new['prompt'].startswith(reader.protocol()[0])
    for a,b in zip(old['prompt_source_spans'],new['prompt_source_spans']):
        assert old['prompt'][a['prompt_start_char']:a['prompt_end_char']]==new['prompt'][b['prompt_start_char']:b['prompt_end_char']]
    assert reader.prepare_scope(path)['prompt']==old['prompt']


def test_new_scope_has_durable_reading_and_portable_visual_projection(region_case,tmp_path,monkeypatch):
    case,_=region_case;b=case['bundle'];s,c=upgraded(case)
    old_preflight=json.loads(Path(s['preflight']['path']).read_text());bundle_hash,bundle_path=save_bundle(tmp_path/'new-source',b)
    structure=tmp_path/'structure.json';structure.write_text(case['manifest']['source']['structure_json'])
    old_preflight.update(bundle=reader.reference(bundle_path),bundle_sha256=bundle_hash,structure=reader.reference(structure))
    preflight=tmp_path/'preflight.json';preflight.write_text(canonical(old_preflight));s['preflight']=reader.reference(preflight)
    capture=tmp_path/'capture.json';capture.write_text(canonical(c));s['image_capture']=reader.reference(capture)
    path=tmp_path/'scope.json';path.write_text(canonical(s))
    source=deepcopy(case['manifest']['source']);source.update(preflight=s['preflight'],structure_ref=reader.reference(structure))
    case['manifest']=reframe(case['manifest'],b,source=source);case['scope']=s
    support=visual_regions.build(**case)
    store=Store(tmp_path/'v2-queue');job=reader.enqueue(store,path);fake=Fake();reader.run(store,job,provider_override=fake)
    assert fake.calls==1 and reader.status(store)['attempts']==1
    monkeypatch.setattr(visual_regions,'verify_local_assets',lambda *args:None) # Synthetic pixels have no physical PDF.
    p=projection.build(store,job,graph=case['extraction'].model_dump(),manifest=case['manifest'],author=AUTHOR,created_at=NOW,
        note='Synthetic source-scope projection.',visual_support=support)
    assert p['receipt']['validation']['valid'] and p['receipt']['reader_provenance']['image_capture_json']==canonical(c)
    before=deepcopy(p)
    monkeypatch.setattr(Path,'read_text',lambda *a,**k:(_ for _ in ()).throw(AssertionError('portable file read')))
    monkeypatch.setattr(Path,'read_bytes',lambda *a,**k:(_ for _ in ()).throw(AssertionError('portable file read')))
    verify_packet(p);assert p==before
    p['receipt']['reader_provenance']['image_capture_json']+=' '
    p['run_id']=digest(p['receipt']);p['packet_hash']=digest({k:v for k,v in p.items() if k!='packet_hash'})
    with pytest.raises(ValueError,match='image_capture_pin'):verify_packet(p)
