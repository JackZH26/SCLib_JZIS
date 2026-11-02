"""Opt-in v2 hybrid candidate coordinator, still gated from public routes.

All SQL uses owned short read sessions. Returned candidates are not source-use
permission: the caller must apply live evidence/rights and final-currentness.
No Google ANN fallback, cache, history insertion, activation or DDL occurs here.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import sqlalchemy as sa

from config import get_settings
from models.retrieval_backend_v2 import POLICY_SHA256
from models.scientific_query import ScientificQueryInterpretation
from services import provider_resilience,query_embedding,retrieval,retrieval_members,retrieval_navigation
from services.pgvector_query import PgvectorQueries,QueryBudget
from services.retrieval_activation import RetrievalPinV2,assert_current_backend,load_active_backend


class ContentRetrievalUnavailable(ValueError):pass


@dataclass(frozen=True,slots=True)
class HybridCandidates:
    pin: RetrievalPinV2
    rankings: tuple[retrieval.RankedCandidate,...]
    chunks: dict


class ContentRetriever:
    """One coordinator per API loop, with a separately reserved ANN engine.

    Session construction is dependency-injected by the application. This
    component never accepts a caller DSN, table name or public pin mapping.
    """
    def __init__(self,session_factory,transport):
        if type(transport) is not PgvectorQueries or transport.budget!=QueryBudget():
            raise ContentRetrievalUnavailable('The frozen pgvector query budget is required')
        self._sessions=session_factory
        self._transport=transport
        self._embedding_workers=query_embedding.QueryEmbeddingWorkers()

    async def close(self):await self._embedding_workers.close()

    def _pin(self,pin):
        if (type(pin) is not RetrievalPinV2 or pin.policy_artifact_sha256!=POLICY_SHA256
                or self._transport.budget!=QueryBudget()):
            raise ContentRetrievalUnavailable('An exact current v2 identity and frozen SQL policy are required')

    async def _read(self,operation):
        async with self._sessions() as db:
            await db.execute(sa.text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            await db.execute(sa.text("SET LOCAL statement_timeout='3000ms'"))
            await db.execute(sa.text("SET LOCAL lock_timeout='250ms'"))
            return await operation(db)

    async def pin(self,*,logical_index='sclib-main'):
        async def resolve(db):
            pin=await load_active_backend(db,logical_index=logical_index)
            self._pin(pin)
            return pin
        async with asyncio.timeout(3):return await self._read(resolve)

    async def _semantic(self,pin,query,*,top_k,year_min,year_max):
        # Queue time is part of the embedding deadline. A bounded SDK timeout
        # prevents a cancelled worker from holding a provider call indefinitely.
        async with asyncio.timeout(6):
            settings=get_settings()
            vector=await provider_resilience.run_blocking('query_embedding',
                lambda:query_embedding.embed_query(json.loads(pin.profile_json),query),
                timeout_seconds=5,failure_threshold=settings.provider_circuit_failure_threshold,
                cooldown_seconds=settings.provider_circuit_cooldown_seconds,max_attempts=1,
                async_executor=self._embedding_workers.run)
        return await self._transport.query(pin.projection,vector,top_k=top_k,year_min=year_min,year_max=year_max)

    async def hybrid(self,pin,query,interpretation,*,top_k,year_min=None,year_max=None,exclude_retracted=True):
        self._pin(pin)
        if (type(top_k) is not int or not 1<=top_k<=100 or type(query) is not str
                or not 2<=len(query)<=2000 or type(interpretation) is not ScientificQueryInterpretation or interpretation.raw_query!=query
                or interpretation.status!='resolved' or type(exclude_retracted) is not bool):
            raise ContentRetrievalUnavailable('A resolved original query and bounded request are required')
        if (any(year is not None and (type(year) is not int or not 1<=year<=9999) for year in (year_min,year_max))
                or year_min is not None and year_max is not None and year_min>year_max):
            raise ContentRetrievalUnavailable('Exact ordered year bounds are required')
        candidate_limit=min(top_k*5,300)
        task=None
        try:
            async with asyncio.timeout(15):
                # Do not schedule any provider call for a forged/stale identity.
                async def current(db):await assert_current_backend(db,pin)
                await self._read(current)
                task=asyncio.create_task(self._semantic(pin,query,top_k=min(top_k*3,100),
                    year_min=year_min,year_max=year_max))
                async def navigation(db):
                    text=await retrieval_navigation.lexical_search(db,pin,interpretation.normalized_query,
                        limit=candidate_limit,year_min=year_min,year_max=year_max,exclude_retracted=exclude_retracted)
                    wanted={item.normalization.normalized_formula for item in interpretation.formulas}
                    formula=await retrieval_navigation.formula_search(db,pin,wanted,limit=candidate_limit,
                        year_min=year_min,year_max=year_max) if wanted and None not in wanted else []
                    return retrieval.combine_lexical_hits(formula,text,limit=candidate_limit)
                lexical=await self._read(navigation)
                # The navigation connection is returned before any provider wait.
                batch=await task
                async def hydrate(db):
                    semantic=await retrieval_members.verified_hits(db,pin,batch)
                    rankings=retrieval.fuse_rankings(semantic,lexical,limit=candidate_limit)
                    chunks=await retrieval_members.hydrate(db,pin,[row.chunk_id for row in rankings])
                    ranked=retrieval.rerank_candidates(query,rankings,chunks)
                    await assert_current_backend(db,pin)
                    return HybridCandidates(pin,tuple(ranked),chunks)
                return await self._read(hydrate)
        except Exception:
            # No partial lexical result silently replaces a failed semantic read.
            # Public orchestration must make any future degradation explicit.
            raise ContentRetrievalUnavailable('Complete content-pinned retrieval is unavailable') from None
        finally:
            if task is not None:
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)
