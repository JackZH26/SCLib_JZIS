"""Home topic search through actual SQL/API, including retraction and filters."""
from models.db import Chunk, Paper


async def test_home_topic_returns_real_lexical_chunks_and_excludes_retracted(client, db_session):
    for suffix, status in [('visible', 'published'), ('retracted', 'retracted')]:
        paper = Paper(id='synthetic:home-concept-'+suffix, source='arxiv',
            title='Synthetic Meissner effect fixture', authors=[], abstract='Synthetic only',
            status=status, materials_extracted=[])
        db_session.add_all([paper, Chunk(id='synthetic:home-concept-chunk-'+suffix,
            paper=paper, text='Synthetic Meissner effect passage; no scientific claim.',
            section='Synthetic test', materials_mentioned=[])])
    await db_session.commit()
    for query in ['Meissner', 'Meissner effect']:
        response = await client.post('/v1/search', json={'query': query, 'filters': {'exclude_retracted': True}})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['scientific_query']['status'] == 'resolved'
        assert body['scientific_lookup']['status'] == 'not_requested'
        assert [r['paper_id'] for r in body['results']] == ['synthetic:home-concept-visible']
        assert 'Synthetic Meissner effect passage' in body['results'][0]['matched_chunk']
        assert body['results'][0]['evidence_provenance']['scientific_acceptance'] is False


async def test_home_topic_with_numeric_ui_filter_does_not_use_legacy_chunks(client):
    response = await client.post('/v1/search', json={'query': 'Meissner', 'filters': {'tc_min': 20}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['scientific_query']['status'] == 'resolved'
    assert body['results'] == body['scientific_results'] == []
    assert body['scientific_lookup']['reason_codes'] == ['active_generation_required']
