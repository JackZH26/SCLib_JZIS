"""Generic review transport preserves native payloads; synthetic semantics stay held."""
from copy import deepcopy
import pytest
from ingestion.materials_ner import review_amendments as amendments
from ingestion.materials_ner.contract import canonical
from test_materials_ner_reviewed_proposals import prepared,packet,graph,AUTHOR,NOW,at


def amended(prepared,kind='penetration_depth',quantity=None):
    g=graph(prepared[3]);g['results'][0]['quantity_kind']=kind
    g['results'][0]['quantity_name_raw']='Synthetic quantity for transport checks'
    if quantity is not None:g['results'][0]['quantity']=quantity
    parent=packet(prepared,graph=g)
    anchor=at(prepared[3].blocks[0],'The criterion is onset.')
    changes=[dict(path='/states/0/label',before=None,after='Synthetic reviewed state',reason='Synthetic scoped editorial change.',anchors=[anchor])]
    reviews=[dict(result_id='r',fields={f:dict(disposition='not_reviewed',note='Transport test only.',anchors=[]) for f in amendments.FIELDS},holds=['independent_review_pending'])]
    value=amendments.build(parent,bundle=parent['bundle'],changes=changes,reviews=reviews,author=AUTHOR,created_at=NOW)
    amendments.verify(value,parent)
    return parent,value


def test_legacy_tc_mapping_is_unchanged(prepared):
    _,a=amended(prepared,'tc')
    assert canonical(amendments.review_mapping(a))==canonical(amendments.tc_mapping(a))


@pytest.mark.parametrize('kind,quantity',[
    ('penetration_depth',dict(status='reported',raw='378 nm',relation='exact',value=378,unit='nm')),
    ('penetration_depth',dict(status='reported',raw='5–7 nm',relation='interval',lower=5,upper=7,unit='nm')),
    ('penetration_depth',dict(status='reported',raw='<7 nm',relation='lt',upper=7,unit='nm')),
    ('penetration_depth',dict(status='reported',raw='5 ± 1 nm',relation='exact',value=5,unit='nm',uncertainty=dict(minus=1,plus=1,kind='reported_unspecified',raw='± 1'))),
    ('penetration_depth',dict(status='reported',raw='5 odd-units',relation='exact',value=5,unit='odd-units')),
    ('unmapped',dict(status='reported',raw='7 inverse square micrometers',relation='exact',value=7,unit='um^-2')),
    ('tc',dict(status='not_extracted')),
])
def test_native_quantities_missingness_and_holds_are_not_coerced(prepared,kind,quantity):
    _,a=amended(prepared,kind,quantity);original=deepcopy(a);m=amendments.review_mapping(a);r=m['records'][0]
    assert m['schema']=='materials-reviewed-result-mapping/1'
    assert r['quantity_kind']==kind and r['source_quantity']==a['graph']['results'][0]['quantity']
    assert r['target_id'] is r['target_table'] is None
    assert r['review_status']=='quarantined' and r['validation_issues']
    assert set(r['validation_issues']).issubset(r['holds'])
    assert r['ready_for_canonical_insert'] is r['scientific_acceptance'] is r['ml_training_eligible'] is False
    if quantity.get('unit') in {'odd-units','um^-2'}:assert not r['normalized']
    r['source_quantity']['value']=999
    assert a==original


def test_shared_state_change_and_derived_result_holds_survive_mapping(prepared):
    g=graph(prepared[3]);g['results'][0]['quantity_kind']='penetration_depth'
    second=deepcopy(g['results'][0]);second['id']='derived';second['dependencies']=[dict(result_id='r',relation='derived_from')]
    g['results'].append(second);parent=packet(prepared,graph=g);anchor=at(prepared[3].blocks[0],'The criterion is onset.')
    a=amendments.build(parent,bundle=parent['bundle'],changes=[dict(path='/states/0/label',before=None,after='Synthetic label',reason='Test shared state.',anchors=[anchor])],
        reviews=[dict(result_id=x['id'],fields={f:dict(disposition='not_reviewed',note='Synthetic test.',anchors=[]) for f in amendments.FIELDS},holds=[]) for x in g['results']],author=AUTHOR,created_at=NOW)
    m=amendments.review_mapping(a);derived=next(r for r in m['records'] if r['source_result_id']=='derived')
    assert a['affected_result_ids']==['derived','r'] and 'derived_input_has_validation_issues' in derived['validation_issues']
    assert derived['dependencies']==second['dependencies']
