"""Literal citation context preserves coordinates and never decides attribution."""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner.reference_context import build_index,attach_references,visible_source,verified_edges
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.document_context import build_inventory,attach_context
from ingestion.materials_ner.sources import load_bundle
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import targets
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.windows import make_windows
from test_materials_ner_tex_context import source


def fixture(tmp_path,*,citation=r'\cite{own,prior,absent}',bibliography=None):
    if bibliography is None:
        bibliography='\\begin{references}\r\n\\bibitem{own} Our transition is 12 K at 9 T.\r\n\\bibitem[Author 2020]{prior} Other authors, journal 1, 2 (2020).\r\n\\end{references}\r\n'
    text='Target result '+citation+'.\r\n'+'Distant discussion without further citations.\r\n'*250+bibliography
    parent=source([('archive_member:main.tex',text)])
    manifest=make_windows(tmp_path,parent,max_chars=1000,adjacent_pages=False,context_chars=100)
    window=load_bundle(tmp_path/'bundles'/(manifest['windows'][0]['bundle_sha256']+'.json'))
    return parent,window


def test_author_note_and_ordinary_reference_have_identical_context_treatment(tmp_path):
    parent,window=fixture(tmp_path);original=deepcopy(window.model_dump());index=build_index(parent)
    enriched,proof=attach_references(parent,window,index)
    assert [x['status'] for x in proof['citations']]==['unique_source_entry','unique_source_entry','missing_source_entry']
    assert not proof['source_role_verified'] and not proof['scientific_acceptance']
    assert not proof['counts_as_target_coverage']
    assert window.model_dump()==original
    assert [b.model_dump() for b in enriched.blocks[:len(window.blocks)]]==[b.model_dump() for b in window.blocks]
    for slice in proof['attachment']['attached_slices']:
        b=next(b for b in enriched.blocks if b.id==slice['block_id'])
        source_block=next(b for b in parent.blocks if b.id==slice['source_block_id'])
        assert b.text==source_block.text[slice['start_char']:slice['end_char']]
        assert '\r\n' in b.text
    catalog=source_catalog(enriched)
    assert all(not catalog['blocks'][catalog['spans'][s]['block_alias']]['locator'].startswith('context-document:') for s in targets(catalog))
    assert 'Other authors' in ''.join(b.text for b in enriched.blocks[len(window.blocks):])
    repeated,repeated_proof=attach_references(parent,window,index)
    assert repeated.model_dump()==enriched.model_dump() and repeated_proof==proof
    with pytest.raises(ValueError,match='already_attached'):attach_references(parent,enriched,index)


def test_existing_methods_context_and_reference_context_do_not_collide(tmp_path):
    parent,window=fixture(tmp_path);text=parent.blocks[0].text
    start=text.index('Distant');end=start+45
    inventory=build_inventory(parent,[dict(source_block_id=parent.blocks[0].id,start_char=start,end_char=end,purpose='test',selection_basis='Synthetic context.')])
    first,_=attach_context(parent,window,inventory)
    both,proof=attach_references(parent,first,build_index(parent))
    assert len({b.id for b in both.blocks})==len(both.blocks)
    assert proof['added_characters']>0
    assert sum(n.startswith('DOCUMENT_CONTEXT ') for n in both.acquisition_notes)==1
    assert sum(n.startswith('REFERENCE_CONTEXT ') for n in both.acquisition_notes)==1
    with pytest.raises(ValueError,match='parent_mismatch'):attach_context(parent,first,inventory)


@pytest.mark.parametrize('citation',[r'\cite*{own}',r'\citep[see][p. 2]{own}',r'\citet {own}',r'\autocite{own}',r'\textcite{own}',r'\onlinecite{own}',r'\parencite{own}', '\\cite{\r\nown\r\n}'])
def test_supported_literal_citation_forms_preserve_raw_offsets(tmp_path,citation):
    parent,window=fixture(tmp_path,citation=citation);enriched,proof=attach_references(parent,window,build_index(parent))
    assert len(proof['citations'])==1
    entry=proof['citations'][0];block=next(b for b in window.blocks if b.id==entry['block_id'])
    assert entry['status']=='unique_source_entry' and block.text[entry['start_char']:entry['end_char']]==citation


@pytest.mark.parametrize('hidden',[
    '% \\cite{own}\n',r'\verb|\cite{own}|',
    '\\begin{comment}\n\\cite{own}\n\\end{comment}\n',
    '\\begin{verbatim}\n\\cite{own}\n\\end{verbatim}\n',
    '\\iffalse\n\\iftrue\n\\cite{own}\n\\fi\n\\else\n\\cite{own}\n\\fi\n',
    r'\newcommand{\example}{\cite{own}}',
    '\\newcommand{\\example}[1]{\n\\cite{own}\n}',
    r'\def\example#1{\cite{own}}',r'\\cite{own}',
])
def test_common_inactive_example_and_escaped_commands_do_not_attach(tmp_path,hidden):
    parent,window=fixture(tmp_path,citation=hidden);_,proof=attach_references(parent,window,build_index(parent))
    assert not proof['citations'] and proof['added_characters']==0
    assert len(visible_source(hidden))==len(hidden)


def test_duplicate_keys_and_unsupported_macro_keys_never_select_first_match(tmp_path):
    bib='\\begin{thebibliography}{99}\n\\bibitem{own} First source.\n\\bibitem{own} Different source.\n\\end{thebibliography}'
    parent,window=fixture(tmp_path,citation=r'\cite{own}\cite{\generatedkey}',bibliography=bib)
    _,proof=attach_references(parent,window,build_index(parent))
    assert [c['status'] for c in proof['citations']]==['ambiguous_source_entry','unsupported_syntax']
    assert proof['added_characters']==0


def test_unclosed_and_comment_bibliographies_remain_gaps(tmp_path):
    bib='% \\begin{references}\n% \\bibitem{prior} Comment only.\n% \\end{references}\n\\begin{references}\n\\bibitem{own} Truncated entry.'
    parent,window=fixture(tmp_path,bibliography=bib);index=build_index(parent)
    assert not index['entries'] and len(index['unclosed_bibliography_regions'])==1
    _,proof=attach_references(parent,window,index)
    assert all(c['status']=='missing_source_entry' for c in proof['citations'])


@pytest.mark.parametrize('newline',['\n', '\r\n'])
def test_multiline_bibtex_author_labels_retain_exact_entry_and_citation(tmp_path,newline):
    # Generated .bbl files commonly wrap optional author/year labels.
    bib=newline.join([r'\begin{thebibliography}{2}',
        r'\bibitem[{\citenamefont{Author et~al.}(2008)\citenamefont{Author,',
        r'  Coauthor, and Another}}]{own}',
        r'Observed transition, journal 1, 2 (2008).',
        r'\bibitem{prior} A different result.',r'\end{thebibliography}'])
    parent,window=fixture(tmp_path,citation=r'\cite{own,prior}',bibliography=bib)
    index=build_index(parent)
    assert [e['key'] for e in index['entries']]==['own','prior']
    enriched,proof=attach_references(parent,window,index)
    assert all(c['status']=='unique_source_entry' for c in proof['citations'])
    edges=verified_edges(enriched)
    assert [e['key'] for e in edges]==['own','prior']
    for entry in index['entries']:
        block=next(b for b in parent.blocks if b.id==entry['source_block_id'])
        raw=block.text[entry['start_char']:entry['end_char']]
        assert raw.count(r'\bibitem')==1 and newline in raw
    assert not proof['source_role_verified'] and not proof['scientific_acceptance']


def test_unsupported_bibitem_is_a_boundary_and_cannot_consume_next_label(tmp_path):
    bib='\n'.join([r'\begin{references}', r'\bibitem{own} First entry.',
        r'\bibitem[unterminated author label',
        r'  Unsupported entry body.', r'\bibitem[Valid author]{prior} Last entry.',
        r'\end{references}'])
    parent,window=fixture(tmp_path,citation=r'\cite{own,prior}',bibliography=bib)
    index=build_index(parent)
    assert [e['key'] for e in index['entries']]==['own','prior']
    for entry in index['entries']:
        block=next(b for b in parent.blocks if b.id==entry['source_block_id'])
        raw=block.text[entry['start_char']:entry['end_char']]
        assert raw.count(r'\bibitem')==1 and 'Unsupported entry body' not in raw
    enriched,_=attach_references(parent,window,index)
    assert [e['key'] for e in verified_edges(enriched)]==['own','prior']


def test_index_parent_and_context_budget_are_fail_closed(tmp_path):
    parent,window=fixture(tmp_path);index=build_index(parent);changed=deepcopy(index)
    changed['entries'][0]['end_char']-=1
    with pytest.raises(ValueError,match='index_mismatch'):attach_references(parent,window,changed)
    before=digest(window.model_dump())
    with pytest.raises(ValueError,match='budget_exceeded_no_silent_truncation'):attach_references(parent,window,index,max_context_chars=1)
    assert digest(window.model_dump())==before
    foreign=window.model_copy(deep=True);foreign.work_id='arxiv:another'
    with pytest.raises(ValueError,match='parent_mismatch'):attach_references(parent,foreign,index)


def test_source_percent_escapes_do_not_hide_following_citation(tmp_path):
    parent,window=fixture(tmp_path,citation=r'100\% retained \cite{own} % \cite{prior}')
    _,proof=attach_references(parent,window,build_index(parent))
    assert [c['key'] for c in proof['citations']]==['own']


def test_literal_edges_reconstruct_citation_and_entry_bytes(tmp_path):
    parent,window=fixture(tmp_path);enriched,_=attach_references(parent,window,build_index(parent))
    assert verified_edges(window)==[]
    edges=verified_edges(enriched)
    assert [e['key'] for e in edges]==['own','prior']
    catalog=source_catalog(enriched)
    for edge in edges:
        assert edge['citation_span_ids'] and edge['entry_span_ids'] and not edge['scientific_attribution_verified']
        assert all(s not in targets(catalog) for s in edge['entry_span_ids'])


@pytest.mark.parametrize('mutation',['key','citation','entry_hash','entry_bounds','document','base_hash','multiple_candidates'])
def test_reference_edge_proof_cannot_reassign_source_bytes(tmp_path,mutation):
    parent,window=fixture(tmp_path);enriched,proof=attach_references(parent,window,build_index(parent))
    proof=deepcopy(proof);citation=proof['citations'][0];entry=citation['candidates'][0]
    if mutation=='key':citation['key']='prior'
    elif mutation=='citation':citation['start_char']+=1
    elif mutation=='entry_hash':entry['text_sha256']='0'*64
    elif mutation=='entry_bounds':entry['end_char']-=1
    elif mutation=='document':entry['document_id']='another-document'
    elif mutation=='base_hash':proof['base_window_sha256']='0'*64
    else:citation['candidates'].append(deepcopy(entry))
    enriched.acquisition_notes=[n for n in enriched.acquisition_notes if not n.startswith('SOURCE_REFERENCE_RESOLUTION ')]
    enriched.acquisition_notes.append('SOURCE_REFERENCE_RESOLUTION '+canonical(proof))
    with pytest.raises(ValueError,match='staged_reference_'):verified_edges(enriched)


@pytest.mark.parametrize('gap',[' ', '\r\n', '\r\n\r\n', ' % inactive comment\n'])
def test_citation_at_span_boundary_keeps_immediate_adjacency_without_crossing_paragraph(tmp_path,monkeypatch,gap):
    from ingestion.materials_ner import evidence
    parent,window=fixture(tmp_path,citation='A reported result.'+gap+r'\cite{own}')
    enriched,_=attach_references(parent,window,build_index(parent));original=evidence.source_spans
    def split(text):
        if text.startswith('Target result'):
            at=text.index(r'\cite{own}')
            yield 0,at
            yield at,len(text)
        else:yield from original(text)
    monkeypatch.setattr(evidence,'source_spans',split)
    edge=verified_edges(enriched)[0]
    assert len(edge['citation_span_ids'])==1
    assert len(edge['citation_context_span_ids'])==(1 if gap.count('\n')==2 or '%' in gap else 2)
