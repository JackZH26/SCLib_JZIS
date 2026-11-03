"""Private HTTP exercise of shared candidate pipelines, without public routes.

The owned operator starts this only on loopback in the restore's isolated
network namespace. There is no publication, saved history, acceptance endpoint,
fallback or provider-secret input in this application. Responses are explicitly
engineering candidates, and hybrid replay excludes provider latency.
"""
from fastapi import FastAPI,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field

from services.candidate_runtime import CandidateRetriever
from services.retrieval_candidate import EngineeringCandidatePin
from services.scientific_query import interpret_scientific_query
from services.candidate_context import CandidateContext
from models.search import SearchRequest,AskRequest
from routers.deps import Identity


class SimilarRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    paper_id:str=Field(min_length=1,max_length=100)
    top_k:int=Field(default=10,ge=1,le=50)


class HybridRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    query:str=Field(min_length=2,max_length=2000)
    top_k:int=Field(default=10,ge=1,le=100)
    year_min:int|None=Field(default=None,ge=1,le=9999)
    year_max:int|None=Field(default=None,ge=1,le=9999)


def create_private_app(reader,pin):
    if type(reader) is not CandidateRetriever or type(pin) is not EngineeringCandidatePin:
        raise ValueError('Explicit private engineering candidate required')
    reader._pin(pin)
    context=CandidateContext(reader,pin)
    app=FastAPI(openapi_url=None,docs_url=None,redoc_url=None)

    def envelope():
        return {'version':'sclib-private-candidate-http/1.0.0','scope':'owned_restore_not_activated',
            'candidate':pin.metadata(),'query_embedding_mode':reader.query_embedding_mode,
            'public_route_or_scientific_acceptance':False}

    @app.post('/candidate/search')
    async def search(body:SearchRequest):
        from services.content_search import search_candidate
        identity=Identity(user=None,guest_ip='127.0.0.1',guest_remaining=None)
        result=await search_candidate(reader,body,identity,context)
        return {**envelope(),'response':result.model_dump(mode='json'),'history_writes':False,'quota_consumed':False}

    @app.post('/candidate/ask')
    async def ask(body:AskRequest,request:Request):
        from routers.ask import _ask
        identity=Identity(user=None,guest_ip='127.0.0.1',guest_remaining=None)
        async with reader._sessions() as db:
            result=await _ask(body,request,identity,db,reader=reader,candidate_context=context)
        return {**envelope(),'response':result.model_dump(mode='json'),'history_writes':False,'quota_consumed':False}

    @app.get('/health')
    async def health():
        if not await reader._readiness.ready(pin):raise HTTPException(503,'Candidate not ready')
        return {**envelope(),'ready':True}

    @app.post('/candidate/similar')
    async def similar(request:SimilarRequest):
        try:
            result=await reader.similar(pin,request.paper_id,top_k=request.top_k)
            return {**envelope(),'source_paper_id':request.paper_id,'source_vector_count':result.source_vector_count,
                'results':[row.model_dump(mode='json') for row in result.results]}
        except Exception:raise HTTPException(503,'Complete engineering similarity unavailable') from None

    @app.post('/candidate/hybrid')
    async def hybrid(request:HybridRequest):
        interpretation=interpret_scientific_query(request.query)
        # This is the hybrid candidate phase. Numeric scientific filtering and
        # generated answers require their separate complete public-flow gates.
        if interpretation.status!='resolved' or interpretation.constraints or interpretation.evidence_constraints:
            raise HTTPException(422,'This private gate accepts resolved hybrid-only queries')
        try:
            result=await reader.hybrid(pin,request.query,interpretation,top_k=request.top_k,
                year_min=request.year_min,year_max=request.year_max)
            return {**envelope(),'rankings':[{'vector_id':row.chunk_id,'fusion_score':row.fusion_score,'rerank_score':row.rerank_score,
                'paper_id':result.chunks[row.chunk_id].paper_id} for row in result.rankings]}
        except Exception:raise HTTPException(503,'Complete engineering hybrid unavailable') from None

    return app
