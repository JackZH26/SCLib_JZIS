"""Synthetic structure and provenance cases; no scientific reference labels."""
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import tarfile

import pytest
from pypdf import PdfWriter

from ingestion.materials_ner import source_audit as audit
from ingestion.materials_ner.cli import main
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.sources import parse_local,sha,save_bundle

WORK='arxiv:2401.00001'
MAIN=r'''% SYNTHETIC TEST SOURCE, not a paper.
\documentclass{article}
\begin{document}
\input{sections/results}
\includegraphics[width=0.9\linewidth]{plot}
\bibliography{refs}
\end{document}
'''


def archive(tmp_path,members):
    path=tmp_path/'original.tar.gz'
    with tarfile.open(path,'w:gz') as file:
        for name,raw in members:
            raw=raw.encode() if isinstance(raw,str) else raw
            info=tarfile.TarInfo(name);info.size=len(raw);file.addfile(info,io.BytesIO(raw))
    return path


def test_exact_member_inventory_and_literal_dependencies_do_not_assign_scientific_roles(tmp_path):
    path=archive(tmp_path,[('main.tex',MAIN),('sections/results.tex','Synthetic result.'),('plot.pdf',b'%PDF-synthetic'),
        ('refs.bbl','Synthetic bibliography.'),('extra_supplement.tex',r'\section{Supplement} Synthetic.')])
    before=path.read_bytes();result=audit.audit_source(path,work_id=WORK)
    assert result['source_sha256']==sha(before) and path.read_bytes()==before
    assert result['root_candidates']==[dict(member_index=0,name='main.tex')]
    assert [e['target_candidates'] for e in result['dependency_candidates']]==[
        ['sections/results.tex'],['plot.pdf'],['refs.bbl']]
    for edge in result['dependency_candidates']:
        assert MAIN[edge['start_char']:edge['end_char']]==edge['literal']
    assert result['supplement_name_candidates']==[4]
    assert not result['roles_auto_assigned'] and not result['full_paper_coverage_verified']
    assert not result['publication_version_verified'] and not result['scientific_acceptance']


def test_percent_comments_do_not_invent_roots_or_dependencies_and_offsets_remain_exact(tmp_path):
    text='% \\documentclass{old}\n% \\begin{document}\n% \\input{discarded}\n'+MAIN+r'escaped \% literal then \input{kept}'
    path=archive(tmp_path,[('main.tex',text),('kept.tex','Synthetic')])
    result=audit.audit_source(path,work_id=WORK)
    assert len(result['root_candidates'])==1
    assert all(e['argument']!='discarded' for e in result['dependency_candidates'])
    assert result['dependency_candidates'][-1]['argument']=='kept'
    masked=audit._mask_comments(text)
    assert len(masked)==len(text) and [i for i,c in enumerate(masked) if c=='\n']==[i for i,c in enumerate(text) if c=='\n']
    assert r'\% literal' in masked
    assert '\\input{ignored}' not in audit._mask_comments('\\\\% \\input{ignored}')


@pytest.mark.parametrize('mode',['two_roots','none','comment_only'])
def test_multiple_missing_and_commented_main_candidates_stay_unresolved(tmp_path,mode):
    items=[('one.tex',MAIN),('two.tex',MAIN)] if mode=='two_roots' else [('section.tex','Only a section.')]
    if mode=='comment_only':items=[('main.tex','% \\documentclass{article}\n% \\begin{document}')]
    result=audit.audit_source(archive(tmp_path,items),work_id=WORK)
    assert 'main_file_candidates_ambiguous_or_missing' in result['hold_codes']
    assert not result['roles_auto_assigned']


@pytest.mark.parametrize('reference,status',[
    (r'\input{missing}','not_resolved_by_literal_lookup'),
    (r'\input{\dynamicfile}','nonliteral_or_unsafe_reference'),
    (r'\input{../outside}','nonliteral_or_unsafe_reference'),
    (r'\input{/absolute}','nonliteral_or_unsafe_reference'),
])
def test_unresolved_dependencies_are_holds_not_evidence_of_complete_coverage(tmp_path,reference,status):
    result=audit.audit_source(archive(tmp_path,[('main.tex',reference)]),work_id=WORK)
    assert result['dependency_candidates'][0]['resolution']==status
    assert 'tex_dependencies_require_review' in result['hold_codes']


def test_differing_working_directory_candidates_are_not_arbitrarily_selected(tmp_path):
    result=audit.audit_source(archive(tmp_path,[('sections/main.tex',r'\input{part}'),
        ('part.tex','One'),('sections/part.tex','Different')]),work_id=WORK)
    edge=result['dependency_candidates'][0]
    assert edge['resolution']=='ambiguous_candidates' and len(edge['target_candidates'])==2


def test_unsupported_macro_syntax_is_exposed_without_running_tex(tmp_path):
    result=audit.audit_source(archive(tmp_path,[('main.tex',r'\input unbraced \import{dir}{file} \epsfig{file=plot.eps}')]),work_id=WORK)
    assert len(result['unsupported_dependency_tokens'])==3
    assert 'unsupported_tex_dependency_syntax' in result['hold_codes']


def test_duplicate_archive_paths_and_identical_members_remain_distinct_entries(tmp_path):
    result=audit.audit_source(archive(tmp_path,[('main.tex',MAIN),('./main.tex',MAIN),('copy.tex',MAIN)]),work_id=WORK)
    assert result['duplicate_member_paths']==['main.tex'] and len(result['members'])==3
    assert result['identical_text_member_groups'][0]['member_indices']==[0,1,2]
    assert 'duplicate_archive_member_path' in result['hold_codes']


def test_paths_and_links_cannot_escape_or_be_read_as_members(tmp_path):
    path=archive(tmp_path,[('../outside.tex','Unexpected'),('/absolute.tex','Unexpected'),('good.tex',MAIN)])
    with tarfile.open(tmp_path/'links.tar','w') as file:
        link=tarfile.TarInfo('symbolic.tex');link.type=tarfile.SYMTYPE;link.linkname='/etc/passwd';file.addfile(link)
    result=audit.audit_source(path,work_id=WORK)
    assert 'unsafe_archive_path' in result['hold_codes']
    assert all('sha256' not in m for m in result['members'][:2])
    links=audit.audit_source(tmp_path/'links.tar',work_id=WORK)
    assert links['members'][0]['link'] and not links['members'][0]['regular_file']
    assert 'archive_link_requires_review' in links['hold_codes']
    assert not (tmp_path.parent/'outside.tex').exists()


def test_bad_encoding_is_retained_as_an_explicit_hold_without_replacement_decoding(tmp_path):
    result=audit.audit_source(archive(tmp_path,[('main.tex',b'bad\xffencoding')]),work_id=WORK)
    assert result['members'][0]['utf8_decodable'] is False
    assert 'text_encoding_requires_explicit_review' in result['hold_codes']
    assert result['members'][0]['sha256']==sha(b'bad\xffencoding')


@pytest.mark.parametrize('compressed',[True,False])
def test_single_gzip_or_text_preserves_identity_tokens_as_unverified_candidates(tmp_path,compressed):
    text=MAIN+'\narXiv:2401.00001v2\narXiv:2301.01120v1 (bibliography example).'
    path=tmp_path/'original';path.write_bytes(gzip.compress(text.encode()) if compressed else text.encode())
    result=audit.audit_source(path,work_id=WORK)
    tokens=result['identity_token_candidates']
    assert [t['matches_expected_work'] for t in tokens]==[True,False]
    assert tokens[0]['version_candidate']=='v2' and not result['publication_version_verified']
    assert all(not t['publication_version_verified'] for t in tokens)


@pytest.mark.parametrize('limit',['source','member','text','archive'])
def test_size_and_count_limits_fail_before_unbounded_processing(tmp_path,monkeypatch,limit):
    path=archive(tmp_path,[('main.tex',MAIN),('extra.tex',MAIN)])
    if limit=='source':monkeypatch.setattr(audit,'MAX_SOURCE_BYTES',8)
    elif limit=='member':monkeypatch.setattr(audit,'MAX_MEMBERS',1)
    elif limit=='text':monkeypatch.setattr(audit,'MAX_TEXT_MEMBER',8)
    else:monkeypatch.setattr(audit,'MAX_ARCHIVE_BYTES',8)
    with pytest.raises(ValueError,match='source_audit_'):audit.audit_source(path,work_id=WORK)


def test_supplied_bundle_is_hash_bound_and_never_rewritten(tmp_path):
    path=archive(tmp_path,[('main.tex',MAIN)])
    bundle=parse_local(path,work_id=WORK,title='SYNTHETIC',source_uri='synthetic:fixture')
    before=deepcopy(bundle.model_dump());result=audit.audit_source(path,work_id=WORK,bundle=bundle)
    assert result['bundle']['sha256']==digest(before) and bundle.model_dump()==before
    bundle.documents[0].source_sha256='0'*64
    with pytest.raises(ValueError,match='bundle_binding'):audit.audit_source(path,work_id=WORK,bundle=bundle)


def test_standalone_pdf_inventory_does_not_claim_text_or_visual_coverage(tmp_path):
    path=tmp_path/'synthetic.pdf';writer=PdfWriter();writer.add_blank_page(width=400,height=500).rotate(90)
    with path.open('wb') as file:writer.write(file)
    result=audit.audit_source(path,work_id=WORK)
    assert result['pages'][0]['rotation']==90 and result['pages'][0]['extracted_characters'] is None
    assert result['pages'][0]['visual_review_completed'] is False
    assert 'pdf_rotation_requires_visual_review' in result['hold_codes']


def test_pdf_wrapper_cannot_masquerade_as_recovered_paper_text(tmp_path):
    text=r'\documentclass{article}\begin{document}\includepdf[pages={1-6},lastpage=6]{paper.pdf}\end{document}'
    path=archive(tmp_path,[('wrapper.tex',text),('paper.pdf',b'%PDF-synthetic-original')])
    bundle=parse_local(path,work_id=WORK,title='Synthetic wrapper',source_uri='synthetic:wrapper')
    result=audit.audit_source(path,work_id=WORK,bundle=bundle)
    edge=result['dependency_candidates'][0]
    assert edge['command']=='includepdf' and edge['target_candidates']==['paper.pdf']
    assert text[edge['start_char']:edge['end_char']]==edge['literal']
    assert 'embedded_pdf_requires_page_extraction_and_role_review' in result['hold_codes']
    assert len(bundle.blocks)==1 and bundle.blocks[0].text==text
    assert not result['roles_auto_assigned'] and not result['full_paper_coverage_verified']


@pytest.mark.parametrize('reference',[r'\includepdf{missing.pdf}',r'\includepdf{\dynamic}',r'\includepdf unbraced'])
def test_unresolved_embedded_pdf_is_never_treated_as_absent_content(tmp_path,reference):
    result=audit.audit_source(archive(tmp_path,[('main.tex',reference)]),work_id=WORK)
    assert 'embedded_pdf_requires_page_extraction_and_role_review' in result['hold_codes']
    assert not result['full_paper_coverage_verified']


def test_ordinary_figure_or_commented_pdf_does_not_claim_embedded_document(tmp_path):
    text='\\includegraphics{plot.pdf}\n% \\includepdf{paper.pdf}'
    result=audit.audit_source(archive(tmp_path,[('main.tex',text),('plot.pdf',b'%PDF-synthetic')]),work_id=WORK)
    assert 'embedded_pdf_requires_page_extraction_and_role_review' not in result['hold_codes']


def test_audit_cli_is_offline_does_not_create_queue_and_refuses_overwrite(tmp_path,capsys):
    path=archive(tmp_path,[('main.tex',MAIN)]);out=tmp_path/'audit.json';root=tmp_path/'unused-queue'
    args=['--root',str(root),'audit-source','--source',str(path),'--work-id',WORK,'--out',str(out)]
    assert main(args)==0
    result=json.loads(out.read_text());notice=json.loads(capsys.readouterr().out)
    assert notice['audit_sha256']==digest(result) and not root.exists()
    before=out.read_bytes()
    with pytest.raises(ValueError,match='already exists'):main(args)
    assert out.read_bytes()==before and not root.exists()


def test_explicit_latin9_preserves_its_distinct_characters_without_changing_default_decoding(tmp_path):
    # Source-declared Latin-9 differs from Latin-1 at these code points. Silent
    # fallback to Latin-1 would produce different source text.
    text='SYNTHETIC \\usepackage[latin9]{inputenc}\nSymbols: € Š Œ.'
    raw=text.encode('iso-8859-15');path=archive(tmp_path,[('main.tex',raw)])
    original=path.read_bytes()
    with pytest.raises(UnicodeDecodeError):parse_local(path,work_id=WORK,title='Synthetic',source_uri='synthetic:latin9')
    bundle=parse_local(path,work_id=WORK,title='Synthetic',source_uri='synthetic:latin9',text_encoding='iso-8859-15')
    assert bundle.blocks[0].text==text and bundle.blocks[0].text.encode('iso-8859-15')==raw
    assert bundle.documents[0].parser.endswith(':iso-8859-15')
    assert path.read_bytes()==original and bundle.documents[0].source_sha256==sha(original)
    assert bundle.documents[0].version_status=='unresolved' and bundle.source_status=='unresolved'
    assert raw.decode('iso-8859-1')!=bundle.blocks[0].text


@pytest.mark.parametrize('encoding',['utf-16','automatic','guess'])
def test_encoding_must_be_explicit_supported_choice(tmp_path,encoding):
    path=archive(tmp_path,[('main.tex',MAIN)])
    with pytest.raises(ValueError,match='explicit supported decoder'):
        parse_local(path,work_id=WORK,title='Synthetic',source_uri='synthetic:test',text_encoding=encoding)
