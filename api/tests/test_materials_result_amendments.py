"""Generic private amendment mapping; no scientific approval or live source calls."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import sys
import pytest

REPO=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(REPO/'ingestion'),str(REPO/'ingestion/tests'),str(REPO/'scripts')]
from test_materials_ner_reviewed_proposals import prepared
from test_materials_ner_result_amendments import amended
from ingestion.materials_ner.review_amendments import review_mapping
from services.materials_proposal_amendments import export,validate_result_mapping,RESULT_COLUMNS
from services.materials_proposal_review import ProposalIntegrityError
import materials_ner_amendment_bridge as bridge


@pytest.fixture
def value(prepared):
    parent,a=amended(prepared,quantity=dict(status='reported',raw='378 nm',relation='exact',value=378,unit='nm'))
    return parent,a,review_mapping(a)


def test_generic_csv_preserves_non_tc_and_does_not_add_tc_columns(value):
    _,a,m=value;raw,contract=export(a,m);rows=list(csv.DictReader(io.StringIO(raw.decode())))
    assert tuple(rows[0])==RESULT_COLUMNS and not any(k.startswith('tc_') for k in rows[0])
    assert rows[0]['quantity_kind']=='penetration_depth' and rows[0]['unit']=='nm'
    assert json.loads(rows[0]['source_quantity_json'])==a['graph']['results'][0]['quantity']
    assert json.loads(rows[0]['dependencies_json'])==a['graph']['results'][0]['dependencies']
    assert rows[0]['review_status']=='quarantined'
    assert all(c['type']=='json_or_null' for c in contract['columns'] if c['name'].endswith('_json'))
    assert next(c for c in contract['columns'] if c['name']=='value')['type']=='number_or_null'


@pytest.mark.parametrize('field,replacement',[
    ('quantity_kind','tc'),('source_quantity',{}),('dependencies',[{'result_id':'other','relation':'derived_from'}]),
    ('normalized',{'wrong':5}),('target_table','material_claims'),('target_id','invented'),
    ('sample_pointer','/graph/samples/99'),('source_result_id','other'),('review_pointer','/reviews/1'),
    ('holds',[]),('scientific_acceptance',True),
])
def test_mapping_mismatch_is_refused(value,field,replacement):
    _,a,m=value;changed=deepcopy(m);changed['records'][0][field]=replacement
    with pytest.raises(ProposalIntegrityError):validate_result_mapping(a,changed)
    with pytest.raises(ProposalIntegrityError):export(a,changed)


@pytest.mark.parametrize('version,registry,validator',[
    ('materials-ner/15','materials-quantities/3.0.0','materials-ner-validation/1.26.0'),
    ('materials-ner/14','materials-quantities/2.0.0','materials-ner-validation/1.26.0'),
    ('materials-ner/14','materials-quantities/3.0.0','materials-ner-validation/1.24.0'),
])
def test_mixed_or_unknown_semantic_versions_are_refused(value,version,registry,validator):
    _,a,m=value;a=deepcopy(a);a['graph']['schema_version']=version
    a['validation'].update(registry_version=registry,validator_version=validator)
    with pytest.raises(ProposalIntegrityError):validate_result_mapping(a,m)


@pytest.mark.asyncio
async def test_rehashed_invalid_amendment_is_rejected_before_engine(value,monkeypatch):
    parent,a,_=value;a=deepcopy(a);a['source_scope']='Changed without replay'
    from ingestion.materials_ner.contract import digest
    a['amendment_id']=digest({k:v for k,v in a.items() if k!='amendment_id'})
    def forbidden(*args,**kwargs):pytest.fail('Database engine opened before semantic verification')
    monkeypatch.setattr(bridge,'create_async_engine',forbidden)
    with pytest.raises(ValueError,match='amendment_replay_mismatch'):
        await bridge.process(dict(action='ingest',parent=parent,amendment=a),database_url='unused')
