"""Content-pinned Similar, with bounded batches and a fresh final snapshot."""
from __future__ import annotations

import asyncio,json,math,struct
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from models.db import Paper
from models.search import SimilarPaper
from services import index_retrieval,retrieval_currentness,retrieval_groups,retrieval_members
from services.pgvector_query import CandidateBatch,SqlNeighbor
from services.retrieval_activation import RetrievalPinV2
from services.retrieval_candidate import current_read_pin
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import source_visibility,project_source_occurrences

MAX_CANDIDATES=1000
BATCH=20


class ContentSimilarityUnavailable(ValueError):pass


@dataclass(frozen=True,slots=True)
class SimilarOutcome:
    pin: RetrievalPinV2
    source_paper_id: str
    results: tuple[SimilarPaper,...]


@dataclass(frozen=True,slots=True)
class Selection:
    pin: retrieval_currentness.SelectionPin
    # Keep only frozen public attribution across phases, not full target text.
    attribution_json: str


async def capture(db,pin,chunks):
    if len(chunks)>BATCH:raise ContentSimilarityUnavailable('Bounded similarity selection required')
    groups=[chunk.materials_mentioned for chunk in chunks]
    if any(type(group) is not list for group in groups) or sum(map(len,groups))>5000:
        raise ContentSimilarityUnavailable('Complete bounded occurrence inventory required')
    linked=await retrieval_currentness._bounded_materials(db,groups)
    statuses=await resolve_paper_lifecycle(db,{chunk.paper_id for chunk in chunks})
    grouping=await retrieval_groups.resolve_grouping_bindings(db,{chunk.paper_id for chunk in chunks})
    evidence=await retrieval_members.resolve_evidence(db,pin,chunks)
    result={}
    for chunk in chunks:
        status=statuses.get(chunk.paper_id);descriptor=evidence[chunk.id]
        visibility=source_visibility(status)
        if (not visibility['reported_claim_filter_eligible'] or descriptor['permission_status']=='restricted'
                or descriptor['currentness']=='stale'):continue
        occurrences,summary=project_source_occurrences(chunk.materials_mentioned,paper_status=status,
            linked_materials=linked,container_paper_id=chunk.paper_id)
        visibility['warning_codes']=sorted(set(visibility['warning_codes']+summary['warning_codes']))
        selected=retrieval_currentness.selection_pin(chunk,material_evidence=occurrences,
            source_review=visibility,evidence=descriptor,grouping_binding=grouping[chunk.paper_id])
        paper=index_retrieval.attribution(chunk)
        public={'paper_id':paper.id,'arxiv_id':paper.arxiv_id,'title':paper.title,'authors':list(paper.authors or []),
            'year':paper.date_submitted.year if paper.date_submitted else None}
        result[chunk.id]=Selection(selected,json.dumps(public,ensure_ascii=False,allow_nan=False,sort_keys=True))
    return result


async def similar(reader,pin,paper_id,*,top_k):
    """No provider embedding, Google fallback, partial batch or history write.

    Preserve the old <=20 source-vector, per-source candidate and mean-distance
    scoring behavior. Hydrate targets in batches so top_k=50 does not require a
    single unbounded full-text/vector transfer. Recheck every contributing
    winner and source in ONE new read-only snapshot before returning.
    """
    reader._pin(pin)
    if type(paper_id) is not str or not 1<=len(paper_id)<=100 or type(top_k) is not int or not 1<=top_k<=50:
        raise ContentSimilarityUnavailable('Exact bounded similarity request required')
    try:
        async with asyncio.timeout(20):
            if not await reader._readiness.ready(pin):
                raise ContentSimilarityUnavailable('Explicit projection preparation required')
            async def source(db):
                if await db.scalar(sa.select(Paper.id).where(Paper.id==paper_id)) is None:
                    raise ContentSimilarityUnavailable('Current source paper unavailable')
                ids=await retrieval_members.paper_member_ids(db,pin,paper_id,limit=20)
                chunks=await retrieval_members.hydrate(db,pin,ids)
                selected=await capture(db,pin,list(chunks.values()))
                rows=(await db.execute(sa.text('SELECT chunk_revision_sha256 FROM retrieval_content_members_v2 '
                    'WHERE content_id=:content AND paper_id=:paper ORDER BY chunk_revision_sha256 LIMIT 20001'),
                    {'content':UUID(pin.content_id),'paper':paper_id})).scalars().all()
                if len(rows)>20000 or len(rows)!=len(set(rows)):
                    raise ContentSimilarityUnavailable('Complete source revision exclusions unavailable')
                members=[chunks[identifier].member for identifier in ids if identifier in selected]
                if any(member['chunk_revision_sha256'] not in rows for member in members):
                    raise ContentSimilarityUnavailable('Source exclusion inventory mismatch')
                return members,selected,tuple(rows)
            async with asyncio.timeout(3):members,sources,excluded=await reader._read(source)
            batches=();per_source=0
            if members:
                vectors=[tuple(struct.unpack('!768f',member['vector_bytes'])) for member in members]
                per_source=min(top_k+5,MAX_CANDIDATES//len(members))
                batches=await reader._transport.query_many(pin.projection,vectors,
                    top_k=per_source,excluded_revisions=excluded)
                if type(batches) is not tuple or len(batches)!=len(members):
                    raise ContentSimilarityUnavailable('Complete ordered Similar batches required')
            unique={}
            for batch in batches:
                if (type(batch) is not CandidateBatch or batch.projection!=pin.projection
                        or type(batch.neighbors) is not tuple or len(batch.neighbors)>per_source):
                    raise ContentSimilarityUnavailable('Incompatible Similar backend batch')
                seen=set();previous_distance=-1.0
                for hit in batch.neighbors:
                    if (type(hit) is not SqlNeighbor or hit.vector_id in seen
                            or type(hit.distance) not in {int,float} or not math.isfinite(hit.distance)
                            or not 0<=hit.distance<=2 or hit.distance<previous_distance):
                        raise ContentSimilarityUnavailable('Invalid ordered Similar neighbors')
                    seen.add(hit.vector_id);previous_distance=hit.distance
                    previous=unique.get(hit.vector_id)
                    fields=('paper_id','content_sha256','vector_sha256','chunk_revision_sha256')
                    if previous is not None and any(getattr(previous,key)!=getattr(hit,key) for key in fields):
                        raise ContentSimilarityUnavailable('Conflicting Similar member binding')
                    unique[hit.vector_id]=hit
            if len(unique)>MAX_CANDIDATES:raise ContentSimilarityUnavailable('Complete bounded Similar cohort required')
            async def targets(db):
                selected={};identifiers=list(unique)
                for offset in range(0,len(identifiers),BATCH):
                    chunks=await retrieval_members.hydrate(db,pin,identifiers[offset:offset+BATCH])
                    for identifier,chunk in chunks.items():
                        hit=unique[identifier]
                        if any(getattr(hit,key)!=chunk.member[key] for key in
                                ('paper_id','content_sha256','vector_sha256','chunk_revision_sha256')):
                            raise ContentSimilarityUnavailable('Similar payload/source binding mismatch')
                    selected.update(await capture(db,pin,list(chunks.values())))
                await current_read_pin(db,pin)
                return selected
            async with asyncio.timeout(5):selected=await reader._read(targets)
            accumulated={};attributions={};contributors={}
            for batch in batches:
                for hit in batch.neighbors:
                    target=selected.get(hit.vector_id)
                    if target is None or hit.paper_id==paper_id:continue
                    accumulated.setdefault(hit.paper_id,[]).append(hit.distance)
                    attributions.setdefault(hit.paper_id,target.attribution_json)
                    contributors.setdefault(hit.paper_id,set()).add(hit.vector_id)
            scores=sorted(((identifier,sum(values)/len(values)) for identifier,values in accumulated.items()),
                key=lambda item:(item[1],item[0]))[:top_k]
            winning={identifier for paper,_ in scores for identifier in contributors[paper]}
            final_pins=[row.pin for row in sources.values()]+[selected[identifier].pin for identifier in sorted(winning)]
            if len(final_pins)>1020 or len({value.chunk_id for value in final_pins})!=len(final_pins):
                raise ContentSimilarityUnavailable('Complete unique Similar final selection required')
            async def final(db):
                await current_read_pin(db,pin)
                for offset in range(0,len(final_pins),BATCH):
                    async def resolve(session,chunks):return await retrieval_members.resolve_evidence(session,pin,chunks)
                    checked=await retrieval_currentness._check_snapshot(db,final_pins[offset:offset+BATCH],resolve,backend_pin=pin)
                    if checked.status!='unchanged':raise ContentSimilarityUnavailable('Similarity selected source changed')
            async with asyncio.timeout(10):await reader._read(final)
            results=tuple(SimilarPaper(**json.loads(attributions[identifier]),similarity=round(1.0-distance,6))
                for identifier,distance in scores)
            return SimilarOutcome(pin,paper_id,results)
    except Exception:
        raise ContentSimilarityUnavailable('Complete content-pinned similarity unavailable') from None
