"""Source compilation and failure isolation, not model-science acceptance tests."""
from copy import deepcopy
import pytest
from ingestion.materials_ner.sources import Bundle, sha
from ingestion.materials_ner import tc_events as tc
from ingestion.materials_ner.typed_inventory_v3 import catalog

@pytest.fixture
def source():
    text='Sample A of X2Y: Tc = 12.30(4) K at 2 GPa. The method was resistivity. The criterion was onset.'
    return Bundle.model_validate(dict(version='materials-source-bundle/1',work_id='arxiv:test',title='Test',family=None,
        source_status='unresolved',supplement_status='not_applicable',acquisition_notes=[],
        documents=[dict(id='d',source_uri='https://example.org/source',source_sha256=sha(text.encode()),
            source_kind='original_text',role='main',publication_version='v1',version_status='verified',
            processing_permission='allowed',redistribution_permission='unresolved',coverage='partial',parser='fixture')],
        blocks=[dict(id='b',document_id='d',ordinal=0,locator='target:test',text=text,sha256=sha(text.encode()))]))

def packet(source):
    cat=catalog(source); nums=cat['numeric_catalog']['numeric_candidates']
    key=next(k for k,v in nums.items() if '12.30' in v['quote'])
    choice=lambda text:dict(selection_id='S1',quote=text)
    event=dict(numeric_id=key,unit='K',unit_basis=choice('K'),sample_description='Sample A',
        identity=[dict(kind='formula',source=choice('X2Y')),dict(kind='label',source=choice('Sample A'))],
        method='resistivity',method_basis=choice('resistivity'),criterion='onset',criterion_basis=choice('onset'),
        transition_stage='unspecified',stage_basis=None,pressure_regime='unknown',pressure_basis=None,
        conditions=[],source_role='primary',attribution_basis=choice(None),limitations=[])
    return dict(schema_version=tc.VERSION,work_id=source.work_id,events=[event],unread_block_ids=[],coverage_limitations=[])

def test_source_numeric_uncertainty_and_no_authority(source):
    result=tc.compile_read(packet(source),source)
    assert not result['held']
    row=result['rows'][0]
    assert row['quantity']['value']==12.30
    assert row['quantity']['uncertainty']['plus']==0.04
    assert not row['ml_training_eligible'] and not row['canonical_promotion']
    assert not result['native_graph_compiled']

def test_one_bad_event_does_not_discard_good_event(source):
    data=packet(source); bad=deepcopy(data['events'][0]); bad['criterion_basis']['quote']='nonexistent criterion'
    data['events'].append(bad)
    out=tc.compile_read(data,source)
    assert len(out['rows'])==1 and len(out['held'])==1
    assert out['held'][0]['event_index']==1

def test_model_numbers_cannot_override_original(source):
    data=packet(source); data['events'][0]['numeric_id']='invented'
    out=tc.compile_read(data,source)
    assert not out['rows'] and out['held'][0]['code']=='result_number_outside_target_or_unselectable'

def test_repeated_literal_does_not_claim_unique_occurrence(source):
    choices={'witness_selections':{'S1':dict(block_id='b',start_char=10,end_char=15,quote='K K K')}}
    matches=tc.resolve(dict(selection_id='S1',quote='K'),choices)
    assert [x['start_char'] for x in matches]==[10,12,14]

def test_whitespace_rewrite_is_not_a_source_quote(source):
    choices={'witness_selections':{'S1':dict(block_id='b',start_char=0,end_char=5,quote='A\n  B')}}
    with pytest.raises(ValueError,match='source_quote_not_literal'):
        tc.resolve(dict(selection_id='S1',quote='A B'),choices)

def test_different_work_cannot_reuse_source_ids(source):
    data=packet(source);data['work_id']='another'
    with pytest.raises(ValueError,match='event_envelope_mismatch'):tc.compile_read(data,source)

def test_duplicate_event_stays_visible_as_hold(source):
    data=packet(source);data['events'].append(deepcopy(data['events'][0]))
    out=tc.compile_read(data,source)
    assert len(out['rows'])==1 and out['held'][0]['code']=='duplicate_event_payload'

def test_core_formula_cannot_be_silently_dropped(source):
    data=packet(source);data['events'][0]['identity']=data['events'][0]['identity'][1:]
    out=tc.compile_read(data,source)
    assert not out['rows'] and out['held'][0]['code']=='event_formula_unresolved'
