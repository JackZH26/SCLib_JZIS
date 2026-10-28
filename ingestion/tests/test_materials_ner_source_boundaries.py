"""Published-source partition and occurrence-bound unit tests; no model calls."""
from copy import deepcopy
import gzip
import pytest
from ingestion.materials_ner import scoped_evidence as scoped,projection_binding as binding,paper_coverage as pc,reviewed_reader as reader
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.sources import parse_local
from ingestion.materials_ner.source_audit import audit_source
from test_materials_ner_reviewed_proposals import graph


def source_case(tmp_path,text,*,tex=True):
    path=tmp_path/'original.src';path.write_bytes(gzip.compress(text.encode(),mtime=0) if tex else text.encode())
    bundle=parse_local(path,work_id='arxiv:2401.00001',title='Synthetic source boundary',source_uri='https://arxiv.org/src/2401.00001v1',processing_permission='allowed')
    structure=audit_source(path,work_id=bundle.work_id,bundle=bundle)
    sp=tmp_path/'structure.json';reader.put(sp,structure)
    pp=tmp_path/'preflight.json';reader.put(pp,dict(synthetic=True))
    block=bundle.blocks[0]
    scope=dict(schema='materials-reviewed-reader-scope/1',preflight=reader.reference(pp),
        passages=[dict(block_id=block.id,start_char=0,end_char=len(block.text),role='target')],image_capture=None)
    inventory=pc.inventory(bundle,structure)
    manifest=pc.build(bundle=bundle,source=dict(preflight=reader.reference(pp),original=reader.reference(path),publication_version='v1',
        structure_ref=reader.reference(sp),structure_json=canonical(structure)),
        roles=[dict(block_id=block.id,start_char=0,end_char=len(block.text),role='main',note='Synthetic published scope.',
            anchors=[dict(block_id=block.id,start_char=0,end_char=len(block.text),quote=block.text)])],
        visuals=[dict(id=x['id'],status='pending',note='Not reviewed.',evidence=[]) for x in inventory['visual_units']],
        dependencies=[dict(id=x['id'],status='pending',note='Not reviewed.',evidence=[]) for x in inventory['dependencies']],
        supplement=dict(status='not_checked',note='Not reviewed.',anchors=[]),assertions=[],
        author=dict(kind='assistant',identity='Synthetic test author',thread_id='synthetic:test'),created_at='2026-10-26T00:00:00+00:00')
    return bundle,scope,manifest


def compile_units(bundle,scope,manifest,*,raw='5 K',unit='K',reverse=False):
    g=graph(bundle);cat=scoped.build(bundle,scope);ids=list(cat['spans'])
    for group in binding.GROUPS:
        for entity in g[group]:entity['evidence']=[]
    g['results'][0]['quantity'].update(raw=raw,unit=unit)
    g['results'][0]['evidence']=[dict(field='/quantity/'+key,witness_ids=ids) for key in ['raw','unit']]
    if reverse:g['results'][0]['evidence'].reverse()
    return g,binding.compile_catalog_bindings(g,bundle,scope,manifest,cat)


def test_comments_are_excluded_whole_and_offsets_account_for_every_character(tmp_path):
    text='Published 5 K. % comment with spaces 99 K\r\nPublished 6 K and 90 \\%.\n% second comment\nEnd.\n'
    b,s,m=source_case(tmp_path,text);cat=scoped.build(b,s)
    assert len(cat['excluded_source_ranges'])==2
    spans=list(cat['spans'].values())+cat['excluded_source_ranges'];end=0
    for span in sorted(spans,key=lambda x:x['start_char']):
        assert span['start_char']==end;end=span['end_char']
        if 'text' in span:assert text[span['start_char']:end]==span['text']
    assert end==len(text)
    selected=scoped.selected(cat,list(cat['spans']),b,s,m)
    assert len(selected)==3
    assert all(pc.published(x,m,b) for x in selected)
    assert any(r'90 \%' in x['quote'] for x in selected)
    assert not any('comment' in x['quote'] or '99 K' in x['quote'] for x in selected)
    assert cat['complete_publication_review'] is False


def test_legacy_catalogue_rebuild_keeps_its_bytes_and_old_publication_hold(tmp_path):
    b,s,m=source_case(tmp_path,'Published 5 K. % hidden 99 K\nPublished 6 K.\n')
    old=scoped.build(b,s,version=scoped.LEGACY_VERSION)
    assert set(old)=={'schema','source_span_algorithm','bundle_sha256','scope_sha256','spans','semantic_annotations','reference_answers_used'}
    assert 'hidden 99 K' in old['spans']['E0001']['text']
    with pytest.raises(ValueError,match='not_published'):scoped.selected(old,list(old['spans']),b,s,m)
    current=scoped.build(b,s);assert current['spans']!=old['spans']


def test_partial_comment_scope_and_non_tex_percent_are_not_conflated(tmp_path):
    text='A. % comment 99 K\nB. 5 K\n';b,s,m=source_case(tmp_path,text)
    s['passages'][0]['start_char']=text.index('comment')
    cat=scoped.build(b,s)
    assert cat['excluded_source_ranges'][0]['start_char']==text.index('comment')
    assert all('99 K' not in x['text'] for x in cat['spans'].values())
    plain=tmp_path/'plain';plain.mkdir();b,s,m=source_case(plain,'Measured 90 % and 5 K.\n',tex=False)
    cat=scoped.build(b,s);assert cat['excluded_source_ranges']==[]
    assert scoped.selected(cat,list(cat['spans']),b,s,m)[0]['quote']=='Measured 90 % and 5 K.\n'


def test_exclusion_ledger_drift_is_rejected(tmp_path):
    b,s,m=source_case(tmp_path,'Published. % hidden\nEnd.\n');cat=scoped.build(b,s)
    cat['excluded_source_ranges'][0]['end_char']-=1
    with pytest.raises(ValueError,match='catalog_drift'):scoped.selected(cat,list(cat['spans']),b,s,m)


@pytest.mark.parametrize('reverse',[False,True])
def test_repeated_units_use_the_same_unique_numeric_occurrence_regardless_of_list_order(tmp_path,reverse):
    text='The sample showed a resistive onset at 5 K. Another sample showed 6 K.\n'
    b,s,m=source_case(tmp_path,text);g,out=compile_units(b,s,m,reverse=reverse)
    assert not out['holds'],out['holds']
    evidence=out['graph']['results'][0]['evidence'];unit=next(e for e in evidence if e['field']=='/quantity/unit')
    assert unit['start_char']==text.index('5 K')+2 and unit['quote']=='K'
    assert any(x['resolution']=='inline_unit_in_bound_raw_occurrence' for x in out['selections'])
    assert binding.scientific_payload(g)==binding.scientific_payload(out['graph'])


def test_inline_unit_does_not_jump_to_another_selected_source_occurrence(tmp_path):
    text='The sample showed a resistive onset at 5 K. Another sample showed 6 K.\n'
    b,s,m=source_case(tmp_path,text);cut=text.index('Another')
    s['passages']=[dict(block_id=b.blocks[0].id,start_char=0,end_char=cut,role='target'),
        dict(block_id=b.blocks[0].id,start_char=cut,end_char=len(text),role='context')]
    cat=scoped.build(b,s);g=graph(b)
    for group in binding.GROUPS:
        for e in g[group]:e['evidence']=[]
    g['results'][0]['evidence']=[dict(field='/quantity/raw',witness_ids=['E0001']),dict(field='/quantity/unit',witness_ids=['E0002'])]
    out=binding.compile_catalog_bindings(g,b,s,m,cat)
    assert any(x['code']=='catalog_inline_unit_outside_selection' for x in out['holds'])


@pytest.mark.parametrize('raw,unit,code',[
    ('5','K','catalog_literal_ambiguous'),
    ('5 K','mK','catalog_inline_unit_disagrees_with_raw'),
])
def test_no_inline_unit_is_inferred_or_replaced(tmp_path,raw,unit,code):
    b,s,m=source_case(tmp_path,'The sample showed a resistive onset at 5 K. Another sample showed 6 K.\n')
    g,out=compile_units(b,s,m,raw=raw,unit=unit)
    assert any(x['code']==code for x in out['holds'])
    assert binding.scientific_payload(g)==binding.scientific_payload(out['graph'])


def test_raw_expression_cannot_bridge_a_removed_comment(tmp_path):
    text='The sample showed a resistive onset at 5 K.\nSplit value 7 % unpublished\nK.\n'
    b,s,m=source_case(tmp_path,text);g,out=compile_units(b,s,m,raw='7 K')
    assert any(x['code']=='catalog_literal_not_in_selected_source' for x in out['holds'])
    assert not any(e['field']=='/quantity/raw' for e in out['graph']['results'][0]['evidence'])


def test_no_published_text_is_not_an_empty_success(tmp_path):
    b,s,m=source_case(tmp_path,'% only commented assertions 5 K\n')
    with pytest.raises(ValueError,match='catalog_no_published_text'):scoped.build(b,s)
