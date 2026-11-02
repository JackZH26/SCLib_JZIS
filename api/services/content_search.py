"""V2 Search orchestration behind the process-wide backend selector."""
import asyncio,time

from fastapi import HTTPException
from config import get_settings

from models.index_read import retrieval_read_metadata
from models.search import SearchRequest,SearchResponse
from models.scientific_lookup import ScientificLookupStatus
from routers.deps import Identity
from services import content_scientific_lookup,retrieval_currentness,retrieval_members
from services.content_retrieval import ContentRetriever
from services.retrieval_activation import assert_current_backend
from services.scientific_filters import ResultFilters
from services.scientific_query import interpret_scientific_query
from services.scientific_query_lookup import result_query


async def search(reader,body,identity):
    """Provider work uses no caller-owned DB session; presentation is fresh RR.

    The shared presenter preserves frozen bibliography, explicit material
    links, holds, restricted-text redaction, year predicates and date/Tc sorts.
    Only a complete immutable content/backend identity may label the response.
    """
    if type(reader) is not ContentRetriever or type(body) is not SearchRequest or type(identity) is not Identity:
        raise ValueError('Exact internal Search orchestration inputs required')
    started=time.perf_counter();query=interpret_scientific_query(body.query);f=body.filters
    filters=ResultFilters(families=tuple(f.material_family or []),tc_min=f.tc_min,pressure_min=f.pressure_min,
        pressure_max=f.pressure_max,ambient_only=f.ambient_only,include_unknown_pressure=f.include_unknown_pressure,
        origins=tuple(f.knowledge_origin or []),source_role=f.source_role,experimental_only=f.experimental_only)
    try:pin=await reader.pin(logical_index=get_settings().retrieval_logical_index)
    except Exception:raise HTTPException(503,'Retrieval content is unavailable') from None
    def response(status,results=()):
        return SearchResponse(total=0,results=[],query_time_ms=int((time.perf_counter()-started)*1000),
            guest_remaining=identity.guest_remaining,remaining=identity.guest_remaining if identity.is_guest else identity.user_remaining,
            retrieval_generation=retrieval_read_metadata(pin),scientific_query=query,scientific_lookup=status,
            scientific_results=list(results))
    scope='declared_content_derived_extractions'
    if query.status=='clarification_required':
        return response(ScientificLookupStatus(status='clarification_required',scope=scope,
            reason_codes=['unresolved_query_constraints']))
    if result_query(query) or filters.active:
        try:
            async with asyncio.timeout(15):
                async def prepare(db):
                    return (await content_scientific_lookup.prepare_content_scientific_lookup(db,pin,query,
                        limit=min(body.top_k,20),filters=filters,year_min=f.year_min,year_max=f.year_max,sort=body.sort)).consume()
                inputs=await reader._read(prepare);outcome=inputs.outcome
                if outcome.status.status=='completed' and inputs.selection_pins:
                    async def resolve(db,chunks):return await retrieval_members.resolve_evidence(db,pin,chunks)
                    checked=await retrieval_currentness.check_selected_sources(inputs.selection_pins,
                        backend_pin=pin,evidence_resolver=resolve)
                    if checked.status!='unchanged':
                        return response(ScientificLookupStatus(status='unavailable',scope=scope,
                            reason_codes=[checked.reason_code or 'scientific_lookup_currentness_unavailable']))
                async def current(db):await assert_current_backend(db,pin)
                await reader._read(current)
                return response(outcome.status,outcome.results)
        except Exception:
            return response(ScientificLookupStatus(status='unavailable',scope=scope,reason_codes=['scientific_lookup_unavailable']))
    try:
        selected=await reader.hybrid(pin,body.query,query,top_k=body.top_k,
            year_min=f.year_min,year_max=f.year_max,exclude_retracted=f.exclude_retracted)
        if selected.pin!=pin:raise ValueError('Search backend identity changed')
        from routers.search import _present_search
        async def present(db):
            return await _present_search(body,identity,db,started,pin,query,filters,list(selected.rankings))
        # Rehydrate sources and resolve current governance in one NEW snapshot
        # after all provider/ANN work. No old candidate object authorizes text.
        async with asyncio.timeout(10):return await reader._read(present)
    except Exception:
        raise HTTPException(503,'Complete content-pinned search is unavailable') from None
