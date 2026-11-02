"""Explicit owned-restore corpus preparation; no acceptance or activation.

The host runner must independently verify the network-none container, signed
PG image, volume ownership, disk/RAM/CPU budgets and primary health. This CLI
adds database-name/marker/builder/source checks; it accepts no DSN argument.
It never serves requests, starts the app lifespan, calls a provider or loads
pytest. Default execution only previews the requested phase.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import math
import re
import time
from uuid import UUID

import sqlalchemy as sa

from config import get_settings
from models.db import get_engine,get_session_factory
from services import retrieval_backend,retrieval_content

DATABASE='sclib_restore_drill'
PHASES=('inspect','content','copy-content','seal-content','projection','copy-vectors','graph','seal-projection','validate')


class CorpusOperatorError(ValueError):pass


@dataclass(frozen=True)
class Request:
    phase: str
    generation_id: str
    manifest_sha256: str
    expected_members: int
    build_id: str
    image_digest: str
    implementation_revision: str
    apply: bool=False
    validation_id: str|None=None
    host_graph_budget: bool=False

    def __post_init__(self):
        if (self.phase not in PHASES or type(self.apply) is not bool or type(self.host_graph_budget) is not bool
                or type(self.expected_members) is not int or not 1<=self.expected_members<=5000000
                or not re.fullmatch('[0-9a-f]{64}',self.manifest_sha256)
                or not re.fullmatch('sha256:[0-9a-f]{64}',self.image_digest)
                or not re.fullmatch('[0-9a-f]{40}',self.implementation_revision)):
            raise CorpusOperatorError('Exact bounded operator request required')
        for value in (self.generation_id,self.build_id,self.validation_id):
            if value is not None and str(UUID(value))!=value:raise CorpusOperatorError('Canonical operator UUID required')
        if self.phase=='validate' and self.validation_id is None:raise CorpusOperatorError('Explicit validation identity required')


async def inspect_source(db,request):
    if get_settings().environment=='production':raise CorpusOperatorError('Owned rehearsal environment required')
    current=await db.scalar(sa.text('SELECT current_database()'))
    if current!=DATABASE:raise CorpusOperatorError('Owned restore database name required')
    marker=(await db.execute(sa.text('SELECT generation_id,manifest FROM sclib_pgvector_rehearsal.source WHERE singleton'))).one()
    if str(marker[0])!=request.generation_id or marker[1]!=request.manifest_sha256:
        raise CorpusOperatorError('Owned restored source marker mismatch')
    builder=await db.scalar(sa.text("SELECT pg_has_role(current_user,'sclib_retrieval_builder','member')"))
    if builder is not True:raise CorpusOperatorError('Separate builder role required')
    source=(await db.execute(sa.text("SELECT expected_member_count,manifest_sha256,"
        "record_sha256=public.sclib_index_record_hash_v1(to_jsonb(g)) AS intact "
        "FROM index_generations g WHERE id=:id"),{'id':UUID(request.generation_id)})).mappings().one()
    if source['intact'] is not True or source['expected_member_count']!=request.expected_members or source['manifest_sha256']!=request.manifest_sha256:
        raise CorpusOperatorError('Exact immutable source header required')
    observed=(await db.execute(sa.text("SELECT current_setting('server_version_num')::integer,extversion "
        "FROM pg_extension WHERE extname='vector'"))).one()
    if not 160000<=observed[0]<170000 or observed[1]!='0.8.7':raise CorpusOperatorError('Compatible actual PG16/vector0.8.7 required')
    return {'source_generation':request.generation_id,'source_manifest':request.manifest_sha256,
        'expected_members':request.expected_members,'partitions':math.ceil(request.expected_members/1000),
        'raw_vector_bytes':request.expected_members*3072,'postgres_version_num':observed[0],'pgvector':observed[1]}


async def _content(db,request):
    return await retrieval_content.stage_legacy_content(db,generation_id=request.generation_id,dry_run=True)


async def _build(db,request,content):
    build,spec=await retrieval_backend._build(db,UUID(request.build_id))
    if (str(build['content_id'])!=content['content_id'] or build['expected_member_count']!=request.expected_members
            or build['image_digest']!=request.image_digest or build['implementation_revision']!=request.implementation_revision):
        raise CorpusOperatorError('Exact declared backend/source/artifact binding required')
    return build,spec


async def graph(db,request,content):
    if not request.host_graph_budget:raise CorpusOperatorError('Separately guarded host graph budget required')
    build,spec=await _build(db,request,content)
    async with retrieval_backend._phase(db,False,{'maintenance_work_mem':'6GB',
            'max_parallel_maintenance_workers':'5','statement_timeout':'0','lock_timeout':'5s',
            'application_name':'sclib_corpus_graph_'+UUID(request.build_id).hex}) as operation:
        await retrieval_backend._fence(db,UUID(request.build_id))
        sealed=await retrieval_backend._existing(db,'retrieval_projection_seals_v2',{'build_id':UUID(request.build_id)})
        if sealed is not None:return {'graph':'sealed_no_rebuild','build_id':request.build_id}
        name='hnsw_b_'+UUID(request.build_id).hex
        exists=await db.scalar(sa.text('SELECT to_regclass(:name) IS NOT NULL'),{'name':'retrieval_projection.'+name})
        if exists:return {'graph':'existing_unsealed_requires_seal_validation','build_id':request.build_id}
        count=await db.scalar(sa.text(f'SELECT count(*) FROM {spec.table}'))
        toast=await db.scalar(sa.text('SELECT CASE WHEN reltoastrelid=0 THEN 0 ELSE pg_relation_size(reltoastrelid) END '
            'FROM pg_class WHERE oid=to_regclass(:name)'),{'name':spec.table})
        if count!=request.expected_members or toast!=0:raise CorpusOperatorError('Complete inline projection required before graph')
        await db.execute(sa.text(f'CREATE INDEX {name} ON {spec.table} USING hnsw '
            '(embedding vector_cosine_ops) WITH(m=32,ef_construction=200)'))
        await db.execute(sa.text(f'ANALYZE {spec.table}'))
        operation['changed']=True
    return {'graph':'constructed_not_accepted','build_id':request.build_id,'members':count}


async def execute(request,*,session_factory=None,progress=None):
    if type(request) is not Request:raise CorpusOperatorError('Exact operator request required')
    factory=session_factory or get_session_factory();started=time.monotonic()
    async with factory() as db:
        source=await inspect_source(db,request)
        content=await _content(db,request)
        await db.rollback()
        base={'version':'owned-corpus-preparation/1.0.0','scope':'owned_restore_engineering_only',
            'phase':request.phase,'apply':request.apply,'source':source,'content_id':content['content_id'],
            'build_id':request.build_id,'activation_performed':False,'quality_acceptance_created':False}
        if not request.apply or request.phase=='inspect':
            return {**base,'status':'preview_no_work','seconds':time.monotonic()-started}
        if request.phase=='content':
            result=await retrieval_content.stage_legacy_content(db,generation_id=request.generation_id,dry_run=False)
            await db.commit()
        elif request.phase=='copy-content':
            cursor='';partition=0;total=0
            while True:
                page=await retrieval_content.source_reference_page(db,content_id=content['content_id'],after=cursor)
                if not page:break
                result=await retrieval_content.append_content_partition(db,content_id=content['content_id'],
                    partition_id=partition,references=page,dry_run=False)
                await db.commit()
                cursor=page[-1]['vector_id'];total+=len(page);partition+=1
                if progress and partition%25==0:progress({'phase':request.phase,'members':total,'partitions':partition})
            if total!=request.expected_members:raise CorpusOperatorError('Complete content source enumeration required')
            result={'members':total,'partitions':partition}
        elif request.phase=='seal-content':
            result=await retrieval_content.seal_content(db,content_id=content['content_id'],dry_run=False);await db.commit()
        elif request.phase=='projection':
            result=await retrieval_backend.stage_build(db,build_id=request.build_id,content_id=content['content_id'],
                image_digest=request.image_digest,implementation_revision=request.implementation_revision,dry_run=False)
            await retrieval_backend.create_projection(db,build_id=request.build_id,dry_run=False);await db.commit()
        else:
            await _build(db,request,content)
            if request.phase=='copy-vectors':
                parts=list((await db.execute(sa.text('SELECT partition_id FROM retrieval_content_partitions_v2 '
                    'WHERE content_id=:id ORDER BY partition_id'),{'id':UUID(content['content_id'])})).scalars())
                if parts!=list(range(source['partitions'])):raise CorpusOperatorError('Complete contiguous sealed partitions required')
                await db.rollback();total=0
                for partition in parts:
                    result=await retrieval_backend.copy_partition(db,build_id=request.build_id,partition_id=partition,dry_run=False)
                    await db.commit();total+=result['members']
                    if progress and (partition+1)%25==0:progress({'phase':request.phase,'members':total,'partitions':partition+1})
                if total!=request.expected_members:raise CorpusOperatorError('Complete projection inventory required')
                result={'members':total,'partitions':len(parts)}
            elif request.phase=='graph':result=await graph(db,request,content);await db.commit()
            elif request.phase=='seal-projection':result=await retrieval_backend.seal_projection(db,build_id=request.build_id,dry_run=False);await db.commit()
            else:
                result=await retrieval_backend.validate_projection(db,build_id=request.build_id,validation_id=request.validation_id,dry_run=False)
                await db.commit()
        return {**base,'status':'phase_completed','result':result,'seconds':time.monotonic()-started}


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--phase',choices=PHASES,default='inspect')
    for name in ('generation-id','manifest-sha256','build-id','image-digest','implementation-revision'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--expected-members',type=int,required=True)
    parser.add_argument('--validation-id')
    parser.add_argument('--apply',action='store_true');parser.add_argument('--host-graph-budget',action='store_true')
    request=Request(**vars(parser.parse_args()))
    async def run():
        from services.schema_lifecycle import check_application_schema
        if get_settings().environment=='production':raise CorpusOperatorError('Owned rehearsal environment required')
        engine=get_engine()
        try:
            await check_application_schema(engine)
            return await execute(request,progress=lambda value:print(json.dumps(value),flush=True))
        finally:await engine.dispose()
    try:print(json.dumps(asyncio.run(run())),flush=True)
    except Exception as error:
        raise SystemExit('Owned corpus preparation refused or failed ('+type(error).__name__+'); no activation was attempted.') from None


if __name__=='__main__':main()
