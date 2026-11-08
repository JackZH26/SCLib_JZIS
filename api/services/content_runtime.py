"""One process-owned reader, shared by all public retrieval routes."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine

from config import get_settings
from models.db import get_engine,get_session_factory
from services.content_retrieval import ContentRetriever
from services.pgvector_query import PgvectorQueries
from services.similar_frontier_release import SimilarFrontiers
from services.similar_live_carrier import LiveSimilarCarrier


def selected_reader(request):
    if get_settings().retrieval_backend=='google':return None
    reader=getattr(getattr(getattr(request,'app',None),'state',None),'content_reader',None)
    if type(reader) is not ContentRetriever:
        raise HTTPException(503,'Retrieval content is not ready')
    return reader


async def check_ready(request):
    async with asyncio.timeout(2):
        reader=selected_reader(request)
        if reader is None:raise ValueError('Content backend was not selected')
        pin=await reader.pin(logical_index=get_settings().retrieval_logical_index)
        if not await reader._readiness.ready(pin):raise ValueError('Content projection is not prepared')
        await reader.check_candidate_sources(pin)


@asynccontextmanager
async def managed_reader(*,source_engine=None,session_factory=None):
    """No schema/grant/provider setup. Failure closes only the owned ANN pool."""
    source_engine=source_engine or get_engine()
    ann=create_async_engine(source_engine.url,pool_size=4,max_overflow=0,pool_timeout=3,pool_pre_ping=True)
    from services.metrics import instrument_sqlalchemy
    instrument_sqlalchemy(ann)
    reader=ContentRetriever(session_factory or get_session_factory(),PgvectorQueries(ann))
    try:
        settings=get_settings()
        if settings.retrieval_use_similar_frontiers:
            reader.similar_frontiers=await asyncio.to_thread(SimilarFrontiers.from_release,reader._transport)
            if reader.similar_frontiers.needs_live_carrier and not settings.retrieval_use_similar_carrier:
                raise ValueError('A paper subset requires the signed live Similar carrier')
        if settings.retrieval_use_similar_carrier:
            reader.similar_carrier=LiveSimilarCarrier.from_release(reader._transport)
        pin=await reader.pin(logical_index=get_settings().retrieval_logical_index)
        await reader.prepare(pin)
        yield reader
    finally:
        try:await reader.close()
        finally:await ann.dispose()
