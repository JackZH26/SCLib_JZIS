from types import SimpleNamespace
import json
import sqlite3

import pytest

from materials_ner_tc_sources import latest_version, needs_pdf, select_papers, write_progress


def bundle(text):
    return SimpleNamespace(documents=[SimpleNamespace(source_kind='original_tex')],
        blocks=[SimpleNamespace(text=text)])


def test_missing_tex_body_and_unexpanded_includes_use_pdf():
    assert needs_pdf(bundle('A detached section'))
    assert needs_pdf(bundle(r'\begin{document}\input{main}\end{document}'))
    assert not needs_pdf(bundle(r'\begin{document}Measured Tc. \includegraphics{figure}\end{document}'))
    assert not needs_pdf(bundle('\\begin{document}\n% \\input{discarded}\nMeasured Tc.\\end{document}'))


def test_official_version_requires_matching_identity():
    html='<meta name="citation_arxiv_id" content="1234.56789"> [v1] [v3]'
    assert latest_version(html,'1234.56789')=='v3'
    with pytest.raises(ValueError,match='identity'):latest_version(html,'1234.56788')
    with pytest.raises(ValueError,match='history'):latest_version(html.split('>')[0]+'>','1234.56789')


def test_selection_uses_actual_jobs_when_corpus_summary_is_stale(tmp_path):
    with sqlite3.connect(tmp_path/'corpus.sqlite3') as db:
        db.execute('CREATE TABLE papers(work_id,state,source_disposition)')
        db.executemany('INSERT INTO papers VALUES(?,?,?)',[
            ('arxiv:done','queued','gcs_acquisition_required'),
            ('arxiv:new','queued','gcs_acquisition_required')])
    with sqlite3.connect(tmp_path/'queue.sqlite3') as db:
        db.execute('CREATE TABLE jobs(work_id)');db.execute('INSERT INTO jobs VALUES(?)',('arxiv:done',))
    plan={'papers':[dict(id=w,source='arxiv') for w in ['arxiv:done','arxiv:new']]}
    papers,denominator,_=select_papers(plan,tmp_path,12)
    assert [p['id'] for p in papers]==['arxiv:new'] and denominator==2


def test_second_progress_update_and_resume_do_not_overwrite_source_receipt(tmp_path):
    receipt=tmp_path/'RESULT.json';receipt.write_text('{"state":"source_ready"}')
    before=receipt.read_bytes();progress=tmp_path/'SOURCE_PROGRESS.json'
    write_progress(progress,dict(ready=1));write_progress(progress,dict(ready=2))
    assert json.loads(progress.read_bytes())['ready']==2 and receipt.read_bytes()==before
