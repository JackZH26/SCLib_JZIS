"""TeX context discovery preserves bytes and scope without guessing method use."""
from copy import deepcopy

import pytest

from ingestion.materials_ner.document_context import (
    TEX_HEADING_POLICY, discover_inventory, attach_context, verify_inventory, _tex_code)
from ingestion.materials_ner.sources import make_blocks, load_bundle
from ingestion.materials_ner.windows import make_windows
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import targets
from test_materials_ner_scoped_conditions import fixture


def source(parts):
    parent, _, _ = fixture()
    parent.documents[0].source_kind = 'original_tex'
    parent.blocks = make_blocks(parent.documents[0].id,parts)
    return parent


def test_tex_methods_attach_to_distant_author_note_without_changing_targets(tmp_path):
    text = ('\\section{Introduction}\r\nA crystal is studied.\r\n' + 'Background prose.\r\n'*250 +
        '% \\section{Methods}\r\n'
        '\\section{experimental details}\r\nA crystal was annealed at 900 C for 48 h.\r\n'
        '\\subsection{NMR}\r\nNMR at 9 T; SQUID is a different method.\r\n'
        '\\section{results}\r\nResults here.\r\n' + 'Additional discussion.\r\n'*120 +
        '\\begin{thebibliography}{99}\r\n\\bibitem{own} Our Tc is 12 K at 26.42 T.\r\n')
    parent=source([('archive_member:main.tex',text)]); before=deepcopy(parent.model_dump())
    legacy=discover_inventory(parent); assert not legacy['selections']
    inventory=discover_inventory(parent,heading_policy=TEX_HEADING_POLICY)
    verify_inventory(parent,inventory); assert len(inventory['selections'])==1
    selected=inventory['selections'][0]
    assert text[selected['start_char']:selected['end_char']] == text[text.index('\\section{experimental details}'):text.index('\\section{results}')]
    manifest=make_windows(tmp_path,parent,max_chars=1000,adjacent_pages=False,context_chars=100)
    window=load_bundle(tmp_path/'bundles'/(manifest['windows'][-1]['bundle_sha256']+'.json'))
    old_targets=[b.model_dump() for b in window.blocks if b.locator.startswith('target:')]
    enriched,proof=attach_context(parent,window,inventory)
    assert [b.model_dump() for b in enriched.blocks if b.locator.startswith('target:')]==old_targets
    assert proof['added_characters']==selected['end_char']-selected['start_char']
    catalog=source_catalog(enriched)
    assert all(not catalog['blocks'][catalog['spans'][i]['block_alias']]['locator'].startswith('context-document:') for i in targets(catalog))
    assert parent.model_dump()==before
    assert not proof['sample_or_procedure_applicability_verified'] and not proof['counts_as_target_coverage']


@pytest.mark.parametrize('heading',[
    '\\section*{Experimental techniques} % source comment',
    '\\subsection[Short title]{Materials and Methods}\\label{sec:methods}',
    '\\section{\\label{sec:methods}Sample preparation and characterization}',
])
def test_literal_heading_variants_and_unrecognized_peer_stop(heading):
    command='subsection' if heading.startswith('\\subsection') else 'section'
    text=heading+'\nMethod details.\n\\'+command+'{Unrecognized $^{63}$Cu topic}\nDo not attach this.\n'
    parent=source([('archive_member:main.tex',text)])
    inventory=discover_inventory(parent,heading_policy=TEX_HEADING_POLICY)
    assert len(inventory['selections'])==1
    assert text[inventory['selections'][0]['start_char']:inventory['selections'][0]['end_char']]==heading+'\nMethod details.\n'


@pytest.mark.parametrize('wrapper',[
    '% \\section{Methods}\n',
    '\\begin{comment}\n\\section{Methods}\n\\end{comment}\n',
    '\\begin{verbatim}\n\\section{Methods}\n\\end{verbatim}\n',
    '\\iffalse\n\\iftrue\n\\section{Methods}\n\\fi\n\\fi\n',
    '\\newcommand{\\example}{\\section{Methods}}\n',
])
def test_inactive_or_example_headings_do_not_create_method_context(wrapper):
    parent=source([('archive_member:main.tex',wrapper+'No methods heading.\n')])
    assert not discover_inventory(parent,heading_policy=TEX_HEADING_POLICY)['selections']


def test_tex_member_order_does_not_imply_cross_file_section_continuation():
    parent=source([('archive_member:methods.tex','\\section{Methods}\nActual methods.\n'),
                   ('archive_member:other.tex','Unrelated text, no heading.\n')])
    inventory=discover_inventory(parent,heading_policy=TEX_HEADING_POLICY)
    assert len(inventory['selections'])==1
    assert inventory['selections'][0]['source_block_id']==parent.blocks[0].id
    assert not inventory['all_relevant_context_identified']
    with pytest.raises(ValueError,match='heading_policy_unknown'):discover_inventory(parent,heading_policy='unknown')


def test_comment_recognition_respects_escaped_percent_without_rewriting_source():
    assert _tex_code(r'100\% retained % ignored') == r'100\% retained'
    assert _tex_code(r'line\\% ignored') == r'line\\'


def test_plain_document_discovery_is_unchanged_under_new_policy():
    parent=source([('text:0','METHODS\nOriginal text.\nRESULTS\nResult text.')])
    parent.documents[0].source_kind='original_text'
    assert discover_inventory(parent)==discover_inventory(parent,heading_policy=TEX_HEADING_POLICY)
