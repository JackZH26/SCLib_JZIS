"""Release filtering checks; synthetic lifecycle cases are not scientific QA."""
import asyncio
from copy import deepcopy
import json
import os
import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from materials_ner_tc_export import inventory
from services.materials_admission_scope import CURRENT_ADMISSION_WHERE, EXCLUSION_REASON_SQL


def test_current_scope_on_postgres_preserves_unknowns_and_excludes_known_invalidity():
    url = os.environ.get('MATERIALS_READ_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set MATERIALS_READ_TEST_DATABASE_URL for read-only PostgreSQL contract checks')
    baseline = dict(extraction_metadata=dict(production_admission=dict(policy='production90/1', batch_qualified=True)),
        property_type='tc', result_status='observed', validity_status='pending', paper_status='published', publication_status='active')
    changes = [({}, None), ({'validity_status': 'accepted'}, None),
        ({'publication_status': 'unknown'}, None), ({'paper_status': None, 'publication_status': None}, None),
        ({'paper_status': 'retracted'}, 'paper_retracted'), ({'paper_status': 'withdrawn'}, 'paper_withdrawn'),
        ({'paper_status': 'refuted'}, 'paper_refuted'), ({'publication_status': 'retracted'}, 'work_retracted'),
        ({'publication_status': 'withdrawn'}, 'work_withdrawn'), ({'validity_status': 'rejected'}, 'claim_not_currently_usable'),
        ({'validity_status': 'superseded'}, 'claim_not_currently_usable'), ({'validity_status': None}, 'claim_not_currently_usable'),
        ({'property_type': 'non_transition'}, 'not_observed_tc'), ({'result_status': 'unknown'}, 'not_observed_tc'),
        ({'extraction_metadata': {'production_admission': {'policy': 'production90/1', 'batch_qualified': False}}}, 'batch_not_qualified'),
        ({'extraction_metadata': {}}, 'not_production90_admission')]
    individual=dict(policy='production90/1',batch_qualified=False,admission_route='individual_source_check',
        per_record_checked=True,quality_status='model_source_checked',reviewer_kind='model')
    changes.extend([
        ({'extraction_metadata': {'production_admission': individual}},None),
        ({'extraction_metadata': {'production_admission': {**individual,'per_record_checked': False}}},'batch_not_qualified'),
        ({'extraction_metadata': {'production_admission': {**individual,'reviewer_kind': None}}},'batch_not_qualified'),
        ({'extraction_metadata': {'production_admission': {**individual,'quality_status':'batch_sampled'}}},'batch_not_qualified'),
        ({'extraction_metadata': {'production_admission': individual},'validity_status':'rejected'},'claim_not_currently_usable')])
    records = [dict(deepcopy(baseline), id=str(i), **change) for i, (change, _) in enumerate(changes)]

    async def check():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                rows = (await db.execute(text(f'''SELECT c.id, {EXCLUSION_REASON_SQL} AS reason,
                    {CURRENT_ADMISSION_WHERE} AS included
                    FROM jsonb_to_recordset(CAST(:records AS jsonb)) AS c(id text,extraction_metadata jsonb,
                        property_type text,result_status text,validity_status text,paper_status text,publication_status text)
                    CROSS JOIN LATERAL (SELECT c.paper_status AS status) p
                    CROSS JOIN LATERAL (SELECT c.publication_status AS publication_status) w'''),
                    {'records': json.dumps(records)})).mappings().all()
                assert len(rows) == len(changes)
                for row in rows:
                    expected = changes[int(row['id'])][1]
                    assert row['reason'] == expected
                    assert row['included'] is (expected is None)
        finally:
            await engine.dispose()
    asyncio.run(check())


def test_filtered_export_keeps_admission_history_in_the_corpus_ledger(tmp_path):
    root = tmp_path / 'root'; root.mkdir()
    campaign = tmp_path / 'campaign'; campaign.mkdir()
    with sqlite3.connect(root / 'corpus.sqlite3') as db:
        db.execute('CREATE TABLE papers(work_id TEXT,state TEXT,full_ner_done INTEGER,retained_rows INTEGER,last_receipt TEXT)')
        db.execute("INSERT INTO papers VALUES('arxiv:synthetic','tc_pass_partial_ingested',1,1,'admission')")
    with sqlite3.connect(root / 'queue.sqlite3') as db:
        db.execute('CREATE TABLE jobs(id TEXT,state TEXT,attempts INTEGER,result_path TEXT)')
    report = inventory(campaign, root, [], dict(canonical_counts_by_paper={'arxiv:synthetic': 1}, excluded_rows=1, dataset={}))
    assert report['canonical_records'] == 1
    assert report['current_dataset_records'] == 0
    assert report['excluded_from_current_dataset'] == 1
    with sqlite3.connect(root / 'corpus.sqlite3') as db:
        assert db.execute('SELECT retained_rows,state FROM papers').fetchone() == (1, 'tc_pass_partial_ingested')
