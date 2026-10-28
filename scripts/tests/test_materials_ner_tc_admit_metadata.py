"""Canonical paper metadata must come from the matching captured arXiv entry."""
import json
from datetime import date

import pytest

from ingestion.materials_ner import reviewed_reader as rr
from ingestion.materials_ner.source_metadata import metadata_url
from materials_ner_tc_admit import paper_metadata
import materials_ner_tc_admit as admission


def captured(tmp_path, *, published='2025-08-07T12:00:00Z', version='v2', summary='Measured transition.'):
    raw=tmp_path/'metadata.atom'
    raw.write_text(f'''<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>http://arxiv.org/abs/2508.00001v1</id><title>Other paper</title>
        <published>2025-08-01T00:00:00Z</published><author><name>Other Author</name></author>
        <summary>Other result.</summary></entry>
      <entry><id>https://arxiv.org/abs/cond-mat/9907183{version}</id><title>Selected\n paper</title>
        <published>{published}</published><updated>2026-10-28T00:00:00Z</updated>
        <author><name>A. Researcher</name></author><author><name>B. Scientist</name></author>
        <summary>{summary}</summary></entry></feed>''')
    url=metadata_url(['2508.00001','cond-mat/9907183'])
    receipt=tmp_path/'metadata.receipt.json'
    receipt.write_text(json.dumps(dict(status=200,requested_url=url,final_url=url,artifact=rr.reference(raw))))
    return dict(official_metadata_receipt=rr.reference(receipt),official_metadata_format='arxiv_atom_batch',
        latest_version_observed='v2'),raw


def test_selected_paper_keeps_authors_abstract_and_original_submission_date(tmp_path):
    pre,_=captured(tmp_path)
    assert paper_metadata(pre,'arxiv:cond-mat/9907183')=={
        'citation_title':['Selected paper'],'citation_author':['A. Researcher','B. Scientist'],
        'description':['Measured transition.'],'citation_date':['2025-08-07']}


@pytest.mark.asyncio
async def test_new_canonical_paper_receives_the_selected_atom_fields(tmp_path,monkeypatch):
    pre,_=captured(tmp_path);captured_rows={}
    class EmptyResult:
        def mappings(self):return self
        def one_or_none(self):return None
    class Database:
        async def execute(self,*_):return EmptyResult()
    async def put(_db,table,row):captured_rows[table]=row
    async def anchor(_db,_table,key):return dict(id=key,row_sha256='synthetic-anchor')
    monkeypatch.setattr(admission,'source_provenance',lambda _:dict(preflight_json=json.dumps(pre)))
    monkeypatch.setattr(admission,'retained',lambda *_args,**_kwargs:[])
    monkeypatch.setattr(admission,'_put',put)
    monkeypatch.setattr(admission,'anchor',anchor)
    await admission.identities(Database(),dict(work_id='arxiv:cond-mat/9907183',bundle=dict(title='Fallback title')),
        {},{},{},dict(id='snapshot'))
    paper=captured_rows['papers']
    assert paper['id']=='arxiv:cond-mat/9907183'
    assert paper['title']=='Selected paper'
    assert paper['authors']==['A. Researcher','B. Scientist']
    assert paper['date_submitted']==date(2025,8,7)
    assert paper['abstract']=='Measured transition.'


@pytest.mark.parametrize('published',['','not a date','2025-99-01T00:00:00Z'])
def test_missing_or_invalid_date_stays_missing_instead_of_using_updated_date(tmp_path,published):
    pre,_=captured(tmp_path,published=published)
    result=paper_metadata(pre,'arxiv:cond-mat/9907183')
    assert 'citation_date' not in result
    assert result['citation_title']==['Selected paper']


@pytest.mark.parametrize('change,message',[
    ('different_work','official_metadata_work_missing'),
    ('different_version','official_metadata_version_mismatch'),
    ('withdrawn','official_metadata_source_withdrawn'),
    ('changed_bytes','official_metadata_changed'),
])
def test_wrong_identity_version_withdrawal_or_changed_capture_is_rejected(tmp_path,change,message):
    pre,raw=captured(tmp_path,summary='This paper has been withdrawn.' if change=='withdrawn' else 'Measured transition.')
    work='arxiv:cond-mat/9907183'
    if change=='different_work':work='arxiv:2508.99999'
    if change=='different_version':pre['latest_version_observed']='v3'
    if change=='changed_bytes':raw.write_text(raw.read_text().replace('Selected','Changed'))
    with pytest.raises(ValueError,match=message):paper_metadata(pre,work)


def test_legacy_html_receipt_keeps_existing_metadata(tmp_path):
    raw=tmp_path/'abstract.html'
    raw.write_text('<meta name="citation_title" content="Legacy title">'
        '<meta name="citation_date" content="2024/01/02">'
        '<meta name="citation_author" content="A. Researcher">')
    receipt=tmp_path/'metadata.receipt.json';receipt.write_text(json.dumps(dict(artifact=rr.reference(raw))))
    pre=dict(official_metadata_receipt=rr.reference(receipt))
    assert paper_metadata(pre,'arxiv:2401.00001')=={
        'citation_title':['Legacy title'],'citation_date':['2024/01/02'],'citation_author':['A. Researcher']}
