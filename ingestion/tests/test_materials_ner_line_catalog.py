"""Source-address granularity tests; synthetic providers, no scientific claims."""
from copy import deepcopy
import json
import gzip
from pathlib import Path

import pytest

from ingestion.materials_ner import scoped_evidence as catalog, source_projector as projector
from ingestion.materials_ner import projection_binding as binding, reviewed_reader as reader
from ingestion.materials_ner import projector_proposals
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.sources import parse_local
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.proposals import verify_packet
from test_materials_ner_projector_native15 import native15_case, SyntheticNative15Provider


@pytest.mark.parametrize('text',[
    '', '\r\n\t\n', '\r\n  alpha\r\n\r\n beta\r\n', 'alpha\rbeta',
    'μ = −0.1\nK\n', 'a\u2028b\nsecond', '5\r\nK',
    r'A & 5 K & 80 GPa \\'+'\n'+r'B & 5 K & 100 GPa \\', 'x'*2000,
])
def test_original_lines_preserve_characters_and_contiguous_offsets(text):
    spans=list(catalog.original_line_spans(text))
    assert ''.join(text[a:z] for a,z in spans)==text
    assert all(a<z and z-a<=900 for a,z in spans)
    assert all(left[1]==right[0] for left,right in zip(spans,spans[1:]))
    if text:
        assert spans[0][0]==0 and spans[-1][1]==len(text)
    if '\u2028' in text:
        assert any('\u2028' in text[a:z] for a,z in spans)


def test_line_catalog_preserves_scope_and_tex_comment_exclusions(tmp_path):
    path=tmp_path/'synthetic.src'
    path.write_bytes(gzip.compress(b'Published 5 K. % unpublished 99 K\r\n\r\nNext 100 GPa.\r\n% hidden 1 K\r\n',mtime=0))
    bundle=parse_local(path,work_id='arxiv:2401.00001',title='Synthetic source',source_uri='https://arxiv.org/src/2401.00001v1',processing_permission='allowed')
    assert bundle.documents[0].source_kind=='original_tex'
    scope=dict(schema='materials-reviewed-reader-scope/2',preflight={},image_capture=None,visual_scope=[],
        passages=[dict(block_id=bundle.blocks[0].id,start_char=0,end_char=len(bundle.blocks[0].text),role='target')])
    original=deepcopy(scope)
    old=catalog.build(bundle,scope);new=catalog.build(bundle,scope,version=catalog.LINE_VERSION)
    assert scope==original and old['schema']==catalog.VERSION
    assert old['excluded_source_ranges']==new['excluded_source_ranges']
    assert ''.join(s['text'] for s in old['spans'].values())==''.join(s['text'] for s in new['spans'].values())
    assert all('99 K' not in s['text'] and '1 K' not in s['text'] for s in new['spans'].values())


def line_case(native15_case,tmp_path):
    path,before,wire=native15_case
    request=json.loads(path.read_bytes());request['source_catalog_version']=catalog.LINE_VERSION
    current=tmp_path/'line-request.json';reader.put(current,request)
    after=projector.prepare(current);graph=deepcopy(wire)
    # Explicit source selections retain exactly the old selected source coverage.
    for group in binding.GROUPS:
        for entity in graph[group]:
            for e in entity['evidence']:
                original=[before['source_catalog']['spans'][i] for i in e['witness_ids']]
                e['witness_ids']=[key for key,s in after['source_catalog']['spans'].items()
                    if any(s['block_id']==o['block_id'] and o['start_char']<=s['start_char'] and s['end_char']<=o['end_char'] for o in original)]
    return current,before,after,graph


def test_opt_in_keeps_reading_scope_and_default_catalogue(native15_case,tmp_path):
    path,before,after,g=line_case(native15_case,tmp_path)
    assert before['scope']==after['scope']
    assert before['source_catalog']['schema']==catalog.VERSION
    assert after['source_catalog']['schema']==catalog.LINE_VERSION
    assert len(after['source_catalog']['spans'])>len(before['source_catalog']['spans'])
    assert projector.prepare(native15_case[0])['prompt']==before['prompt']
    assert projector.prepare(native15_case[0])['schema']==before['schema']
    compiled=binding.compile_catalog_bindings(g,after['bundle'],after['scope'],after['coverage'],after['source_catalog'])
    assert not compiled['holds'] and compiled['scientific_payload_unchanged']


def test_cross_line_evidence_stays_in_original_reading_range(native15_case,tmp_path):
    _,_,p,g=line_case(native15_case,tmp_path)
    block=p['bundle'].blocks[0];source=block.text
    # Bind a literal across physical lines; selection still joins original text.
    raw=source[:source.index('The reported displacement field')]
    g['protocols'][0]['details_raw']=raw
    ids=[key for key,s in p['source_catalog']['spans'].items() if s['start_char']<len(raw)]
    g['protocols'][0]['evidence'].append(dict(field='/details_raw',witness_ids=ids))
    out=binding.compile_catalog_bindings(g,p['bundle'],p['scope'],p['coverage'],p['source_catalog'])
    assert not out['holds']
    assert any(e['field']=='/details_raw' and e['quote']==raw.strip() for e in out['graph']['protocols'][0]['evidence'])
    assert out['scientific_payload_unchanged']


def test_same_line_repetition_is_still_held(native15_case,tmp_path):
    _,_,p,g=line_case(native15_case,tmp_path)
    g['results'][0]['definition']['criterion_raw']='onset'
    first=next(key for key,s in p['source_catalog']['spans'].items() if s['text'].count('onset')==2)
    g['results'][0]['evidence']=[dict(field='/definition/criterion_raw',witness_ids=[first])]
    out=binding.compile_catalog_bindings(g,p['bundle'],p['scope'],p['coverage'],p['source_catalog'])
    assert any(h['code']=='catalog_literal_ambiguous' for h in out['holds'])
    assert out['scientific_payload_unchanged']


def test_context_witness_cannot_be_promoted_by_finer_ids(native15_case,tmp_path):
    _,_,p,g=line_case(native15_case,tmp_path)
    scope=deepcopy(p['scope']);scope['passages'][0]['role']='context'
    finer=catalog.build(p['bundle'],scope,version=catalog.LINE_VERSION)
    out=binding.compile_catalog_bindings(g,p['bundle'],scope,p['coverage'],finer)
    assert any(h['code']=='explicit_evidence_selector_invalid' for h in out['holds'])
    assert out['scientific_payload_unchanged']


def test_tampered_fine_catalogue_is_rejected(native15_case,tmp_path):
    _,_,p,g=line_case(native15_case,tmp_path);fine=deepcopy(p['source_catalog'])
    fine['spans']['E0001']['text']='Invented source.'
    with pytest.raises(ValueError,match='scoped_catalog_drift'):
        binding.compile_catalog_bindings(g,p['bundle'],p['scope'],p['coverage'],fine)


@pytest.mark.parametrize('version',[None,True,{},'materials-scoped-source-spans/999'])
def test_invalid_catalogue_option_is_rejected(native15_case,version):
    request=json.loads(native15_case[0].read_bytes());request['source_catalog_version']=version
    with pytest.raises(ValueError,match='projector_source_catalog_version'):projector.request_contract(request)


def test_line_catalogue_not_enabled_for_historical_requests(native15_case):
    request=json.loads(native15_case[0].read_bytes());request.update(schema=projector.NATIVE14_INPUT_SCHEMA,graph_schema='materials-ner/14',source_catalog_version=catalog.LINE_VERSION)
    with pytest.raises(ValueError,match='projector_input_shape'):projector.request_contract(request)


def test_synthetic_attempt_and_portable_packet_replay_line_catalogue(native15_case,tmp_path,monkeypatch):
    path,_,p,g=line_case(native15_case,tmp_path)
    fake=SyntheticNative15Provider(g);store=Store(tmp_path/'synthetic-line-queue')
    job=projector.enqueue(store,path);result=projector.run(store,job,provider_override=fake)
    assert result['state']=='succeeded',result
    assert projector.run(store,job,provider_override=fake)==result and fake.calls==1
    packet=projector_proposals.build(store.root,job);verify_packet(packet)
    assert packet['receipt']['extraction']['schema_version']=='materials-ner/15'
    assert packet['scientific_acceptance'] is False and packet['ml_training_eligible'] is False
    def forbidden(*args,**kwargs):raise AssertionError('Portable replay accessed source or provider')
    monkeypatch.setattr(reader,'checked',forbidden);monkeypatch.setattr(fake,'extract',forbidden)
    verify_packet(packet)
