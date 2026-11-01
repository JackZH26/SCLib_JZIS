"""Regression checks for source-bound Materials presentation (no database)."""
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"api"))

from services.materials_display import display_projection, registry
from services.materials_source_notation import definitions, expand, sha256


def block(source, locator='archive_member:paper.tex'):
    return dict(text=source,sha256=sha256(source),locator=locator)


def test_source_arguments_delimiters_and_paper_isolation():
    source=block(r'\newcommand{\pccox}[2]{Pr$_{#1}$Ce$_{#2}$CuO$_4$}')
    macros=definitions([source])
    text,refs=expand(r'\pccox{1.85}{0.15}\xspace',macros)
    assert text.startswith('Pr$_{1.85}$Ce$_{0.15}$CuO$_4$')
    assert refs[0]['member_sha256']==source['sha256']
    assert '1.83' in expand(r'\pccox{1.83}{0.17}',macros)[0]
    assert expand(r'\pccox{1.85}{0.15}',{})[0]==r'\pccox{1.85}{0.15}'
    for definition,call,expected in [
        (r'\def\MgB2{MgB$_2$}',r'\MgB2','MgB$_2$'),
        (r'\def\a-U{$\alpha$--U}',r'\a-U',r'$\alpha $--U'),
        (r'\def\1020{$10^{20}$ cm$^{-3}$}',r'\1020','$10^{20}$ cm$^{-3}$'),
        (r'\newcommand{\ped}[1]{_{#1}}',r'As\ped 2','As_{2}'),
    ]:
        assert expand(call,definitions([block(definition)]))[0]==expected
    assert expand(r'\MgB3',definitions([block(r'\def\MgB2{MgB$_2$}')]))[0]==r'\MgB3'


def test_conflicts_cycles_unsafe_bodies_and_missing_arguments_fail_closed():
    for sources,call in [
        ([r'\def\a{FeSe}',r'\def\a{CuO}'],r'\a'),
        ([r'\def\a{\b}\def\b{\a}'],r'\a'),
        ([r'\def\a{\input{secret}}'],r'\a'),
        ([r'\iffalse\def\a{FeSe}\fi'],r'\a'),
        ([r'{\def\a{FeSe}}'],r'\a'),
        ([r'\newcommand{\a}[2]{#1#2}'],r'\a{Fe}'),
        ([r'\newcommand{\a}[1][Fe]{#1Se}'],r'\a'),
    ]:
        assert expand(call,definitions([block(s) for s in sources]))==(call,[])


def test_macro_expansion_preserves_control_word_boundaries():
    text,_=expand(r'\stack',definitions([block(r'\def\stack{\slash\LAO}\def\LAO{LaAlO$_3$}')]))
    assert text==r'\slash LaAlO$_3$'


def fixture():
    claim='4e16efcf-ec72-54a0-88a0-bde61ebfbdbd'
    a=registry()['records'][claim]
    row=dict(id=claim,paper_id=a['paper_id'],material_id=a['material_id'],
        source_versions=a['source_versions'],formula=r'\pccox{1.85}{0.15}\xspace',
        compositions=[dict(formula=r'\pccox{1.85}{0.15}\xspace')],quantity={'raw':'24 K'})
    return row,a


def test_display_requires_assertion_paper_version_source_and_literal():
    row,a=fixture();before=copy.deepcopy(row)
    assert display_projection(row,{a['bundle_sha256']})['formula'].startswith('Pr$_{1.85}')
    assert row==before
    assert not display_projection(row,set())
    assert not display_projection(row,{'0'*64})
    for key,value in [('id','another-claim'),('paper_id','arxiv:wrong'),('source_versions',['v2']),('material_id','another-material')]:
        altered={**row,key:value}
        assert not display_projection(altered,{a['bundle_sha256']})
    altered={**row,'formula':r'\pccox{1.83}{0.17}'}
    assert 'formula' not in display_projection(altered,{a['bundle_sha256']})
    assert 'composition:0' in display_projection(altered,{a['bundle_sha256']})


def test_compiled_registry_has_provenance_and_no_local_paths():
    data=registry()
    assert data['version']=='materials-source-display/1'
    assert 'file:' not in json.dumps(data) and '/Users/' not in json.dumps(data)
    for item in data['records'].values():
        assert len(item['bundle_sha256'])==64
        assert item['definitions'] or item['font_mappings'] or item['reviewed_sources']
        for value in item['fields'].values():
            assert len(value['raw_sha256'])==64 and value['text']
        for ref in item['font_mappings']:
            assert ref['display'] and ref['font'] in {'Symbol','SymbolMT','SymbolMT,Italic'}
