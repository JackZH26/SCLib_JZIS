"""Local native-Tc batch admission using verified source-scoped identities."""
import argparse
import asyncio
from datetime import date, datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ingestion.materials_ner import reviewed_reader as rr
from materials_ner_tc_intake import uid, checked_projection, AdmissionValidation, prepare, apply, source_provenance
from materials_ner_tc_sampling import retained, BATCH_ROUTE, RECORD_ROUTE
from materials_ner_canonical_bridge import _put, require
from materials_ner_production90 import read_pin
from models.db import Base
from services.material_enrichment import normalize_formula
from services.source_registry import _json, provenance_sha256 as digest


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__();self.values={}
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='meta' and values.get('name') and values.get('content'):
            self.values.setdefault(values['name'],[]).append(values['content'])


def capture(path,value):
    """Keep first-write receipts; a replay is a new receipt, not an overwrite."""
    value=_json(value)
    if path.exists() and json.loads(path.read_bytes())!=value:
        path=path.with_name(path.stem+'-'+digest(value)[:16]+path.suffix)
    rr.put(path,value)
    return rr.reference(path)


async def anchor(db,name,key):
    table=Base.metadata.tables[name]
    key=UUID(key) if isinstance(table.c.id.type,sa.Uuid) else key
    row=(await db.execute(sa.select(table).where(table.c.id==key))).mappings().one()
    return dict(id=str(row['id']),row_sha256=digest(dict(row)))


async def existing_results(db,packet,projection,selection,audit,*,admission_route=BATCH_ROUTE):
    """A changed projection must not create a second claim for one provider result.

    Existing claims remain attached to their original audited projection. A
    changed scientific result needs an explicit revision, never another insert.
    """
    table=Base.metadata.tables['material_claims']
    previous=(await db.execute(sa.select(table).where(table.c.paper_id==packet['work_id'],
        table.c.source_locator['run_id'].astext==packet['run_id']))).mappings().all()
    candidates={r['result_id']:r for r in retained(projection,selection,audit,admission_route=admission_route)}
    found=set()
    for row in previous:
        rid=row['source_locator'].get('source_result_id')
        if rid not in candidates:continue
        require(rid not in found,'duplicate_existing_provider_result')
        require(row['extraction_metadata']['native_origin']['packet_hash']==packet['packet_hash'],
            'existing_provider_packet_conflict')
        result=candidates[rid]['graph']['results'][0]
        require(row['raw_record']=={k:v for k,v in result.items() if k!='evidence'},
            'existing_provider_result_requires_revision')
        found.add(rid)
    return found


async def identities(db,packet,projection,selection,audit,snapshot,excluded_result_ids=(),*,admission_route=BATCH_ROUTE):
    work=packet['work_id'];aid=work.removeprefix('arxiv:')
    pv=source_provenance(packet);pre=json.loads(pv['preflight_json'])
    receipt=read_pin(pre['official_metadata_receipt']);ref=receipt['artifact']
    raw=Path(ref['path']).read_bytes()
    require(hashlib.sha256(raw).hexdigest()==ref['sha256'],'official_metadata_changed')
    parser=Metadata();parser.feed(raw.decode());metadata=parser.values
    title=metadata.get('citation_title',[packet['bundle']['title']])[0]
    paper_table=Base.metadata.tables['papers'];work_table=Base.metadata.tables['works']
    existing=(await db.execute(sa.select(paper_table).where(paper_table.c.id==work))).mappings().one_or_none()
    if existing is None:
        submission=metadata.get('citation_date',[None])[0]
        try:submission=date.fromisoformat(submission.replace('/','-')) if submission else None
        except ValueError:submission=None
        await _put(db,'papers',dict(id=work,source='arxiv',arxiv_id=aid,external_id=aid,id_scheme='arxiv',title=title,
            authors=metadata.get('citation_author',[]),date_submitted=submission,
            abstract=metadata.get('description',[''])[0],status='published',citation_count=0,chunk_count=0,
            materials_extracted=[],quality_flags=['source_scoped_native_tc_intake','publication_review_status_unknown']))
    else:require(existing['source']=='arxiv' and existing['arxiv_id']==aid,'paper_identity_conflict')
    existing_work=(await db.execute(sa.select(work_table).where(work_table.c.canonical_arxiv_id==aid))).mappings().one_or_none()
    wid=str(existing_work['id']) if existing_work else uid(work,'work')
    if existing_work is None:
        await _put(db,'works',dict(id=wid,canonical_title=title,canonical_arxiv_id=aid,publication_status='unknown',
            identity_metadata=dict(identity_basis='exact_arxiv',metadata_receipt=pre['official_metadata_receipt'])))
    mapping=Base.metadata.tables['paper_work_map']
    previous=(await db.execute(sa.select(mapping).where(mapping.c.paper_id==work))).mappings().one_or_none()
    if previous:require(str(previous['work_id'])==wid,'paper_work_identity_conflict')
    else:await db.execute(insert(mapping).values(paper_id=work,work_id=UUID(wid),relation_type='preprint',match_method='exact_arxiv',match_score=1,review_status='accepted'))
    await _put(db,'source_snapshots',snapshot)
    samples={}
    for r in retained(projection,selection,audit,admission_route=admission_route):
        if r['result_id'] in excluded_result_ids:continue
        s=r['graph']['samples'][0];formula=s['formula_raw'];require(formula is not None,'source_formula_required')
        mid='source:'+uid(work,formula,'material')
        await _put(db,'materials',dict(id=mid,formula=formula,formula_normalized=normalize_formula(formula),
            total_papers=1,status='active_research',records=[],material_semantics=dict(identity_resolution='source_scoped',
                source_work_id=work,formula_normalization='formatting_only',cross_paper_composition_equivalence='unresolved')))
        samples[s['id']]=await anchor(db,'materials',mid)
    return dict(purpose='pending_candidates',paper=await anchor(db,'papers',work),work=await anchor(db,'works',wid),
        snapshot=await anchor(db,'source_snapshots',snapshot['id']),samples=samples)


async def admit(selection_path,audit_path,output,database_url,*,admission_route=BATCH_ROUTE):
    selection=json.loads(Path(selection_path).read_bytes());audit=json.loads(Path(audit_path).read_bytes())
    validation=AdmissionValidation.build(selection,audit,admission_route)
    report=validation.report(selection,audit,admission_route)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    epoch=output/'EPOCH.json'
    if not epoch.exists():rr.put(epoch,dict(captured_at=datetime.now(timezone.utc).isoformat()))
    captured_at=json.loads(epoch.read_bytes())['captured_at']
    admitted=[]
    for entry in selection['source_entries']:
        packet,projection=checked_projection(entry)
        admitted.extend(retained(projection,selection,audit,admission_route=admission_route))
    snapshot=dict(id=uid(selection['selection_sha256'],'snapshot'),dataset_version='materials-p90-'+selection['selection_sha256'][:16],
        schema_version='materials-production90/1',status='building',paper_count=len({r['work_id'] for r in admitted}),
        material_count=len(admitted),chunk_count=0,
        metadata=dict(admission_policy='production90/1',selection_sha256=selection['selection_sha256'],audit_sha256=report['audit_sha256'],
            scope='Native primary experimental Tc source assertions; not full-paper coverage.',independent_expert_review=False))
    if admission_route==RECORD_ROUTE:
        snapshot.update(id=uid(selection['selection_sha256'],RECORD_ROUTE,'snapshot'),
            dataset_version='materials-p90-individual-'+selection['selection_sha256'][:16])
        snapshot['metadata'].update(admission_route=RECORD_ROUTE,source_batch_qualified=report['qualified'])
    engine=create_async_engine(database_url,connect_args={'server_settings':{'timezone':'UTC'}});reports=[]
    try:
        for entry in selection['source_entries']:
            packet,projection=checked_projection(entry)
            if not retained(projection,selection,audit,admission_route=admission_route):continue
            committed=False
            try:
                async with AsyncSession(engine,expire_on_commit=False) as db:
                    await db.execute(sa.text('SELECT pg_advisory_xact_lock(1002401)'))
                    existing=await existing_results(db,packet,projection,selection,audit,admission_route=admission_route)
                    if len(existing)==len(retained(projection,selection,audit,admission_route=admission_route)):
                        reports.append(dict(work_id=packet['work_id'],claims=0,inserted=0,
                            already_admitted_result_ids=sorted(existing),status='verified_existing_provider_results'))
                        print(json.dumps(reports[-1]),flush=True)
                        continue
                    bindings=await identities(db,packet,projection,selection,audit,snapshot,existing,admission_route=admission_route)
                    kwargs=dict(bindings=bindings,captured_at=captured_at,selection=selection,audit=audit,
                        excluded_result_ids=existing,admission_route=admission_route,validation=validation)
                    plan=prepare(entry,**kwargs)
                    d=output/packet['work_id'][6:].replace('/','_');d.mkdir(exist_ok=True)
                    capture(d/'PLAN.json',plan)
                    first=await apply(db,entry,**kwargs,dry_run=False)
                    await db.commit();first['committed']=True;committed=True
                    readback_pin=capture(d/'READBACK.json',first)
                    replay=await apply(db,entry,**kwargs,dry_run=False)
                    require(replay.get('inserted',0)==0 and replay['registry']['inserted']==0,'native_replay_inserted_duplicates')
                    require(replay['readback']==first['readback'],'native_replay_readback_changed')
                    await db.commit()
                    reports.append(dict(work_id=packet['work_id'],claims=len(first['results']),inserted=first.get('inserted',0),
                        replay_inserted=0,readback_verified=True,committed=True,readback=readback_pin,
                        already_admitted_result_ids=sorted(existing)))
            except Exception as exc:
                failure=dict(work_id=packet['work_id'],stage='canonical_intake',committed=committed,
                    error_class=type(exc).__name__,error=str(exc).split('[SQL:')[0][:1500],
                    status='committed_verification_incomplete' if committed else 'held')
                capture(output/(packet['work_id'][6:].replace('/','_')+'-ERROR.json'),failure)
                reports.append(failure)
            print(json.dumps(reports[-1]),flush=True)
        capture(output/'DATABASE_READBACK.json',dict(reports=reports,quality_report=report,local_persistent=True,production_site_updated=False))
        return reports
    finally:await engine.dispose()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--selection',required=True);p.add_argument('--audit',required=True)
    p.add_argument('--output',required=True);p.add_argument('--database-url',required=True)
    p.add_argument('--admission-route',choices=[BATCH_ROUTE,RECORD_ROUTE],default=BATCH_ROUTE)
    args=p.parse_args();asyncio.run(admit(args.selection,args.audit,args.output,args.database_url,admission_route=args.admission_route))
