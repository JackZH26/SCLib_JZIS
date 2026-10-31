"""Adjacent PDF context is literal, bounded and separate from target coverage."""
from copy import deepcopy

import pytest

from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.sources import load_bundle, make_blocks
from ingestion.materials_ner.windows import make_windows
from test_materials_ner_scoped_conditions import fixture


def document():
    bundle,_,_=fixture()
    bundle.blocks=make_blocks(bundle.documents[0].id, [
        ('pdf_page:9','p9 '+ 'a'*2200), ('pdf_page:10','A transition decreases upon'),
        ('pdf_page:11','compression. Phase III reaches 6 K. '+ 'b'*2200)])
    return bundle


def test_adjacent_context_keeps_exact_boundaries_and_old_manifest(tmp_path):
    parent=document();before=deepcopy(parent.model_dump())
    old=make_windows(tmp_path,parent,max_chars=1000)
    old_bytes=(tmp_path/'windows'/digest(before)/'manifest.json').read_bytes()
    new=make_windows(tmp_path,parent,max_chars=1000,adjacent_pages=True,context_chars=200)
    assert parent.model_dump()==before
    assert (tmp_path/'windows'/digest(before)/'manifest.json').read_bytes()==old_bytes
    assert old['target_characters']==new['target_characters']==sum(len(b.text) for b in parent.blocks)
    assert old['schema'].endswith('/2') and new['schema'].endswith('/3')
    assert not new['adjacent_page_context']['counts_as_target_coverage']
    target=next(r for r in new['windows'] if r['source_block_id']==parent.blocks[1].id)
    window=load_bundle(tmp_path/'bundles'/(target['bundle_sha256']+'.json'))
    assert [b.text for b in window.blocks if b.locator.startswith('target:')]==[parent.blocks[1].text]
    assert next(b for b in window.blocks if b.locator.startswith('context-previous-page:')).text==parent.blocks[0].text[-200:]
    assert next(b for b in window.blocks if b.locator.startswith('context-next-page:')).text==parent.blocks[2].text[:200]
    assert all(d.coverage=='partial' for d in window.documents)
    # First segment of a long page does not borrow its next page while local
    # following text still exists; the last segment does not borrow the prior page.
    long=[r for r in new['windows'] if r['source_block_id']==parent.blocks[0].id]
    assert not any(c['role']=='context-next-page' for c in long[0]['adjacent_page_context'])
    assert any(c['role']=='context-next-page' for c in long[-1]['adjacent_page_context'])


@pytest.mark.parametrize('variant',['gap','other_document','non_pdf'])
def test_context_never_crosses_page_gaps_or_documents(tmp_path,variant):
    parent=document()
    if variant=='gap': parent.blocks[2].locator='pdf_page:12'
    if variant=='other_document':
        second=parent.documents[0].model_copy(deep=True);second.id+='-second'
        parent.documents.append(second);parent.blocks[2].document_id=second.id
    if variant=='non_pdf': parent.blocks[1].locator='tex:section.tex'
    new=make_windows(tmp_path,parent,adjacent_pages=True)
    row=next(r for r in new['windows'] if r['source_block_id']==parent.blocks[1].id)
    assert not any(c['role']=='context-next-page' for c in row['adjacent_page_context'])


def test_ambiguous_page_mapping_is_not_guessed(tmp_path):
    parent=document();parent.blocks[2].locator=parent.blocks[1].locator
    with pytest.raises(ValueError,match='ambiguous PDF page'):make_windows(tmp_path,parent,adjacent_pages=True)
