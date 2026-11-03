"""No services/providers: pgvector must not enter a legacy publication path."""
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from pydantic import ValidationError
from ingestion import config,pipeline,aps_pipeline
from ingestion.index import indexer

pytestmark=pytest.mark.asyncio


@pytest.fixture
def pgvector(monkeypatch):
    monkeypatch.setattr(config,'get_settings',lambda:SimpleNamespace(retrieval_backend='pgvector'))


async def test_backend_is_explicit_and_unknown_modes_are_rejected():
    assert config.IngestionSettings(_env_file=None,database_url='postgresql://unavailable@127.0.0.1:1/unavailable').retrieval_backend=='google'
    assert config.IngestionSettings(_env_file=None,database_url='postgresql://unavailable@127.0.0.1:1/unavailable',retrieval_backend='pgvector').retrieval_backend=='pgvector'
    with pytest.raises(ValidationError):
        config.IngestionSettings(_env_file=None,database_url='postgresql://unavailable@127.0.0.1:1/unavailable',retrieval_backend='unknown')


@pytest.mark.parametrize('writer',[indexer.upsert_chunks_to_vector_search,indexer.upsert_aps_chunks_to_vector_search])
@pytest.mark.parametrize('chunks',[[],[object()]])
async def test_every_google_write_is_refused_before_payload_or_cached_client(pgvector,monkeypatch,writer,chunks):
    cloud=Mock(side_effect=AssertionError('No cached or fresh cloud transport may be selected'))
    monkeypatch.setattr(indexer,'_index',cloud)
    with pytest.raises(config.NativePublicationRequired):writer(object(),chunks)
    cloud.assert_not_called()


async def test_fresh_google_client_initialization_is_refused(pgvector,monkeypatch):
    indexer._index.cache_clear()
    init=Mock(side_effect=AssertionError('No Google initialization allowed'))
    monkeypatch.setattr(indexer.aiplatform,'init',init)
    with pytest.raises(config.NativePublicationRequired):indexer._index()
    init.assert_not_called()


@pytest.mark.parametrize('strategy',['default','skip_vs','skip_ner','abstract_only','force_pdf'])
@pytest.mark.parametrize('skip_vector_search',[False,True])
async def test_arxiv_refused_before_download_prepare_ner_embedding_and_db(pgvector,monkeypatch,strategy,skip_vector_search):
    client=SimpleNamespace(download_source_capture=AsyncMock(side_effect=AssertionError('No download allowed')),
        download_pdf_capture=AsyncMock(side_effect=AssertionError('No download allowed')))
    persist=AsyncMock(side_effect=AssertionError('No source mutation allowed'))
    monkeypatch.setattr(pipeline,'upsert_paper_with_chunks',persist)
    with pytest.raises(config.NativePublicationRequired):
        await pipeline.process_paper(client,object(),strategy=strategy,skip_vector_search=skip_vector_search,skip_ner=True,skip_geo=True)
    client.download_source_capture.assert_not_awaited();client.download_pdf_capture.assert_not_awaited();persist.assert_not_awaited()


async def test_direct_finish_and_retry_entry_points_cannot_bypass_selection(pgvector):
    with pytest.raises(config.NativePublicationRequired):await pipeline._finish(object(),True,True,True,{})
    with pytest.raises(config.NativePublicationRequired):await pipeline._run_retry(limit=1)
    with pytest.raises(config.NativePublicationRequired):
        await pipeline.run(mode='smoke',from_date=None,until_date=None,limit=1,skip_vector_search=True,skip_ner=True,skip_geo=True)


@pytest.mark.parametrize('dry_run',[False,True])
async def test_legacy_aps_cannot_fetch_or_enter_delete_context(pgvector,monkeypatch,tmp_path,dry_run):
    archive=tmp_path/'retained-original.zip';archive.write_bytes(b'preserved synthetic original')
    before=archive.stat()
    def legacy_context(*args,**kwargs):
        raise AssertionError('The legacy transient archive/deletion flow must not start')
    monkeypatch.setattr(aps_pipeline,'TempBagit',legacy_context)
    client=SimpleNamespace(get_article=AsyncMock(side_effect=AssertionError('No harvest allowed')))
    with pytest.raises(config.NativePublicationRequired):
        await aps_pipeline.process_aps_paper(client,'10.1103/synthetic',skip_vector_search=True,skip_ner=True,dry_run=dry_run)
    client.get_article.assert_not_awaited()
    assert archive.read_bytes()==b'preserved synthetic original' and archive.stat().st_mtime_ns==before.st_mtime_ns
    constructor=Mock(side_effect=AssertionError('No legacy APS client may be created'))
    monkeypatch.setattr(aps_pipeline,'ApsClient',constructor)
    with pytest.raises(config.NativePublicationRequired):await aps_pipeline._run(['10.1103/synthetic'])
    constructor.assert_not_called()


async def test_existing_metadata_only_aggregation_remains_separate(pgvector,monkeypatch):
    aggregate=AsyncMock(return_value=5);monkeypatch.setattr(pipeline,'aggregate_from_papers',aggregate)
    result=await pipeline.run(mode='aggregate-materials',from_date=None,until_date=None,limit=1,
        skip_vector_search=True,skip_ner=True,skip_geo=True)
    assert result[0]['ok'] and result[0]['n_materials']==5
    aggregate.assert_awaited_once()
