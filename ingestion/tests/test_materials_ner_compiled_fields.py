"""Scientific failure-mode regressions for durable source-field selection."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import jsonschema
from ingestion.materials_ner import compiled_fields as fields,compiled_field_worker as flow
from ingestion.materials_ner.source_occurrence import witness,active_catalog
from ingestion.materials_ner.contract import digest,canonical
from ingestion.materials_ner.sources import parse_local,sha
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from ingestion.materials_ner.providers import ProviderResult,ProviderFailure
from ingestion.materials_ner.validation import resolve_quote


def fixture(tmp_path,text='The maximum $T_c$ cannot exceed 60 K. Sample B has $T_c$ = 5 K.'):
    p=tmp_path/'paper.tex';p.write_bytes(text.encode())
    b=parse_local(p,work_id='test:paper',title='Test',source_uri='test:paper.tex',publication_version='v1',processing_permission='allowed')
    spans=list(source_catalog(b)['spans'])
    request=dict(schema_version='materials-compiled-field-request/1',work_id=b.work_id,bundle_sha256=digest(b.model_dump()),
        parent_dataset_sha256='a'*64,assertions=[dict(id='A1',source_span_ids=spans,context_span_ids=[],
            prior_assertion=dict(id='A1',context_span_ids=[],quantity_name='maximum Tc'),parent_entry_sha256='b'*64)])
    return b,request


def empty(catalog):
    return dict(schema_version=fields.POLICY,work_id=catalog['work_id'],assertions={aid:dict(
        nominal_occurrence_id=None,separate_uncertainty_id=None,source_attribution='unknown',result_role='unknown',
        fields={s:dict(status='unresolved',reason='not_stated',explanation='Test hold.') for s in fields.SLOTS},review_note='Test hold.')
        for aid in catalog['assertions']},limitations=[])


def choose(catalog,raw,aid='A1'):
    return next(k for k,v in catalog['assertions'][aid]['numbers'].items() if v['quote']==raw)


def test_compilation_preserves_bound_and_does_not_average(tmp_path):
    b,r=fixture(tmp_path,'The families cannot exceed 60 K, 50 K and 40 K.')
    _,packets,c=flow.prepare(b,r);output=empty(c)
    output['assertions']['A1'].update(nominal_occurrence_id=choose(c,'50 K'),result_role='interpretation')
    schema=fields.output_schema(c);jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(output,schema)
    result,v=flow.replay(canonical(output),b,r);q=result['records'][0]['compiled_quantity']
    assert q['relation']=='le' and q['upper']==50 and q['value'] is None
    assert not result['records'][0]['eligible_for_training'] and not v['canonical_graph_validated']


def test_cross_assertion_shared_candidate_is_held_not_borrowed(tmp_path):
    b,r=fixture(tmp_path,'First sample $T_c$ = 5 K. '+('Padding original text. '*70)+' Second sample $T_c$ = 8 K.')
    spans=list(source_catalog(b)['spans']);r['assertions'][0]['source_span_ids']=[spans[0]]
    r['assertions'].append(dict(r['assertions'][0],id='A2',source_span_ids=[spans[-1]],prior_assertion=dict(id='A2')))
    _,p,c=flow.prepare(b,r);output=empty(c)
    output['assertions']['A1']['nominal_occurrence_id']=choose(c,'8 K','A2')
    result,v=flow.replay(canonical(output),b,r)
    assert result['records'][0]['compiled_quantity'] is None
    assert any(i['code']=='numeric_candidate_outside_assertion_scope' for i in v['issues'])
    assert len(result['records'])==2


def test_repeated_source_candidates_share_only_exact_occurrences(tmp_path):
    b,r=fixture(tmp_path);r['assertions'].append(dict(r['assertions'][0],id='A2',prior_assertion=dict(id='A2')))
    _,p,c=flow.prepare(b,r)
    assert list(c['assertions']['A1']['numbers'])==list(c['assertions']['A2']['numbers'])
    assert list(c['assertions']['A1']['texts'])==list(c['assertions']['A2']['texts'])
    assert fields.render(b,c).count('SHARED NUMERIC OCCURRENCES:')==1


def test_name_layout_repair_keeps_original_bytes(tmp_path):
    b,r=fixture(tmp_path,'The maximum\r\n$T_c$ cannot exceed 60 K.')
    _,p,c=flow.prepare(b,r);out=empty(c);a=out['assertions']['A1']
    a['nominal_occurrence_id']=choose(c,'cannot exceed 60 K')
    tid=next(k for k,v in c['assertions']['A1']['texts'].items() if v['kind']=='clause' and 'maximum' in v['quote'])
    a['fields']['quantity_name']=dict(status='selected',candidate_id=tid,literal='maximum $T_c$')
    result,v=flow.replay(canonical(out),b,r)
    assert result['records'][0]['selected_fields']['quantity_name']['quote']=='maximum\r\n$T_c$'


def test_witness_disambiguates_whitespace_equivalent_occurrences(tmp_path):
    b,r=fixture(tmp_path,'Earlier work cannot exceed\r\n60 K. Current hypothesis cannot exceed 60 K.')
    text=b.blocks[0].text;raw='cannot exceed\r\n60 K';a=text.index(raw)
    assert text.count(raw)==1
    with pytest.raises(ValueError,match='ambiguous_quote_locator'):resolve_quote(text,raw)
    e=witness(b,dict(block_id=b.blocks[0].id,start_char=a,end_char=a+len(raw),quote=raw))
    left,right=resolve_quote(text,e['quote']);assert left<=a and a+len(raw)<=right
    assert 'Earlier work' in e['quote']


def test_comment_value_and_stale_coordinate_rejected(tmp_path):
    b,r=fixture(tmp_path,'Visible 5 K. % Ignored 99 K.\nAnother clause 8 K.')
    text=b.blocks[0].text;a=text.index('99 K')
    with pytest.raises(ValueError,match='comment_crossing'):witness(b,dict(block_id=b.blocks[0].id,start_char=a,end_char=a+4,quote='99 K'))
    with pytest.raises(ValueError,match='coordinate_mismatch'):witness(b,dict(block_id=b.blocks[0].id,start_char=0,end_char=4,quote='99 K'))
    assert all('99 K' not in s['text'] and sha(s['text'].encode())==s['text_sha256'] for s in active_catalog(b)['spans'].values())


@pytest.mark.parametrize('mode',['duplicate','wrong_bundle','unknown_span','wrong_identity'])
def test_request_binding_failures(tmp_path,mode):
    b,r=fixture(tmp_path)
    if mode=='duplicate':r['assertions'].append(deepcopy(r['assertions'][0]))
    if mode=='wrong_bundle':r['bundle_sha256']='0'*64
    if mode=='unknown_span':r['assertions'][0]['source_span_ids']=['S99999']
    if mode=='wrong_identity':r['assertions'][0]['prior_assertion']['id']='A2'
    with pytest.raises(ValueError):flow.prepare(b,r)


class Provider:
    def __init__(self,raw,callback=None):self.raw=raw;self.calls=0;self.callback=callback
    def extract(self,prompt,schema,config,directory):
        self.calls+=1
        if self.callback:self.callback()
        if isinstance(self.raw,Exception):raise self.raw
        return ProviderResult(self.raw,{'input_tokens':1,'output_tokens':1},'test','test',None,.01)


def test_durable_idempotent_job_replays_and_never_promotes(tmp_path):
    b,r=fixture(tmp_path);store=Store(tmp_path/'state');job=flow.enqueue(store,b,r)
    assert flow.enqueue(store,b,r)==job
    _,p,c=flow.prepare(b,r);raw=canonical(empty(c));provider=Provider(raw)
    result=run_one(store,job_id=job,provider_override=provider);assert provider.calls==1
    assert result['state']=='quarantined' and not result['scientific_acceptance']
    folder=Path(result['receipt_path']).parent;receipt=json.loads((folder/'receipt.json').read_bytes())
    assert receipt['source_request_unchanged'] and receipt['implementation_unchanged']
    assert flow.replay(raw,b,r)[0]==json.loads((folder/'compiled-fields.json').read_bytes())
    assert run_one(store,job_id=job,provider_override=provider) is None
    assert provider.calls==1


def test_provider_failure_retains_receipt_without_auto_retry(tmp_path):
    b,r=fixture(tmp_path);store=Store(tmp_path/'state');job=flow.enqueue(store,b,r)
    p=Provider(ProviderFailure('test_timeout',retryable=True));out=run_one(store,job_id=job,provider_override=p)
    assert out['state']=='failed' and out['error_code']=='test_timeout'
    assert json.loads(Path(out['receipt_path']).read_bytes())['terminal']
    assert run_one(store,job_id=job,provider_override=p) is None and p.calls==1


def test_input_budget_stops_before_provider(tmp_path):
    b,r=fixture(tmp_path);store=Store(tmp_path/'state');job=flow.enqueue(store,b,r,max_input_tokens=1000)
    p=Provider('{}');out=run_one(store,job_id=job,provider_override=p)
    assert p.calls==0 and out['error_code']=='compiled_input_budget_exceeded' and out['state']=='blocked'


def test_request_drift_during_call_quarantines(tmp_path):
    b,r=fixture(tmp_path);store=Store(tmp_path/'state');job=flow.enqueue(store,b,r)
    _,p,c=flow.prepare(b,r)
    path=next((store.root/'compiled-requests').glob('*.json'))
    provider=Provider(canonical(empty(c)),callback=lambda:path.write_text('{}'))
    out=run_one(store,job_id=job,provider_override=provider)
    assert out['state']=='quarantined' and out['error_code']=='compiled_source_request_drift'


def test_invalid_output_does_not_discard_raw_response(tmp_path):
    b,r=fixture(tmp_path);store=Store(tmp_path/'state');job=flow.enqueue(store,b,r);provider=Provider('{invalid')
    out=run_one(store,job_id=job,provider_override=provider)
    assert out['state']=='failed'
    assert (Path(out['receipt_path']).parent/'output.json').read_text()=='{invalid'
    assert json.loads(Path(out['receipt_path']).read_bytes())['raw_output_sha256']==sha(b'{invalid')
