"""Original 0711.2257v1 source ownership; these checks are not Gold labels."""
from copy import deepcopy
from pathlib import Path

import pytest

from materials_private_fixtures import private_json

from ingestion.materials_ner.sources import Bundle
from ingestion.materials_ner.table_ownership import compile_ownership, select_cell, verify_ownership

FIXTURES=Path(__file__).parent/'fixtures'


@pytest.fixture
def inputs():
    source=private_json('materials_ner_compiled_catalog_source.json')
    ledger=private_json('materials_ner_table_ownership_ledger.json')
    return Bundle.model_validate(source['bundle']),ledger['cells']


def compile(inputs):
    return compile_ownership(*inputs,marker_convention='numeric_to_lower_alpha')


def test_all_original_cells_and_only_explicit_footnote_edges(inputs):
    before=deepcopy(inputs[1]);result=compile(inputs)
    assert len(result['cells'])==58 and inputs[1]==before
    links=[(c['id'],c['row_label']['quote'],f['label']) for c in result['cells'] for f in c['footnotes']]
    assert links==[('T1:R7:C4','0.55','a'),('T1:R13:C2','0.00','b'),
                   ('T1:R13:C3','0.00','c'),('T1:R14:C2','0.40','b')]
    assert not result['scientific_acceptance'] and not result['ml_eligible']
    c=select_cell(result,'T1:R13:C3',row_label='0.00',column_header='$^{18}T_c$',footnote_label='c')
    assert c['source_cell']['quote']==r'91.16(4)\footnotemark[3]'
    assert r'$^{16}$O$\rightarrow$$^{18}$O' in c['footnotes'][0]['definition_source']['quote']
    assert all(not c['footnotes'] for c in result['cells'] if c['id'] not in {x[0] for x in links})


@pytest.mark.parametrize('cell,row,header,note',[
    ('T1:R13:C3','0.40','$^{18}T_c$','c'),
    ('T1:R14:C2','0.40','$^{16}T_c$','c'),
    ('T1:R13:C2','0.00','$^{18}T_c$','b'),
    ('T1:R1:C3','0.00','$^{18}T_c$','c'),
])
def test_back_exchange_footnote_does_not_propagate_by_proximity(inputs,cell,row,header,note):
    with pytest.raises(ValueError,match='table_selection_'):
        select_cell(compile(inputs),cell,row_label=row,column_header=header,footnote_label=note)


@pytest.mark.parametrize('change',['wrong_row','wrong_cell','wrong_header','wrong_label','wrong_column',
    'bool_column','changed_markers','duplicate_id','duplicate_cell','changed_quote','changed_hash',
    'changed_block','changed_bounds','cross_table_notes'])
def test_source_or_relationship_tampering_is_rejected(inputs,change):
    bundle,rows=inputs
    if change=='wrong_row':rows[0]['source_row']=rows[-1]['source_row']
    elif change=='wrong_cell':rows[0]['source_cell']=rows[1]['source_cell']
    elif change=='wrong_header':rows[0]['source_header']=rows[1]['source_header']
    elif change=='wrong_label':rows[0]['row_label']=rows[-1]['row_label']
    elif change=='wrong_column':rows[0]['column']=3
    elif change=='bool_column':rows[0]['column']=True
    elif change=='changed_markers':rows[0]['footnote_markers']=['3']
    elif change=='duplicate_id':rows.append(deepcopy(rows[0]))
    elif change=='duplicate_cell':r=deepcopy(rows[0]);r['id']='new-id';rows.append(r)
    elif change=='changed_quote':rows[0]['source_cell']['quote']='0'
    elif change=='changed_hash':rows[0]['source_cell']['quote_sha256']='0'*64
    elif change=='changed_block':rows[0]['source_cell']['block_id']='other'
    elif change=='changed_bounds':rows[0]['source_cell']['start_char']+=1
    elif change=='cross_table_notes':rows[0]['table_footnotes']=rows[0]['source_row']
    with pytest.raises(ValueError,match='table_'):compile_ownership(bundle,rows,marker_convention='numeric_to_lower_alpha')


@pytest.mark.parametrize('style',['numeric','unknown',None])
def test_marker_convention_cannot_be_guessed(inputs,style):
    with pytest.raises(ValueError,match='table_'):
        compile_ownership(*inputs,marker_convention=style)


@pytest.mark.parametrize('change',['approval','footnote'])
def test_replay_rejects_changed_ownership_or_authority(inputs,change):
    compiled=compile(inputs)
    assert verify_ownership(*inputs,compiled)==compiled
    if change=='approval':compiled['scientific_acceptance']=True
    else:compiled['cells'][0]['footnotes']=compiled['cells'][-5]['footnotes'] or [{'label':'c'}]
    with pytest.raises(ValueError,match='table_compiled_ownership_changed'):
        verify_ownership(*inputs,compiled)
