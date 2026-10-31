"""Prepare bounded, resumable source batches from the frozen arXiv denominator.

Local GCS originals are reused where possible; new originals are fetched from
the exact official version without a mandatory preceding GCS transfer.
TeX requiring unresolved includes uses a version-pinned PDF fallback. This
prepares text for extraction, never claims full-paper scientific coverage.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import sqlite3
import time

import httpx

from ingestion.materials_ner import reviewed_reader as rr, source_audit
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.planning import diverse_order, load_plan
from ingestion.materials_ner.sources import load_bundle, parse_local, save_bundle, sha, private_write
from ingestion.materials_ner.source_metadata import metadata_url, parse_metadata


def latest_version(html, aid):
    if not re.search(r'name=["\']citation_arxiv_id["\'][^>]*content=["\']'+re.escape(aid)+r'(?:v\d+)?["\']',html):
        raise ValueError('official_metadata_identity_mismatch')
    versions={int(v) for v in re.findall(re.escape(aid)+r'v([1-9]\d*)',html)}
    versions.update(int(v) for v in re.findall(r'\[v([1-9]\d*)\]',html))
    if not versions:raise ValueError('official_version_history_missing')
    return 'v'+str(max(versions))


def needs_pdf(bundle):
    if any(d.source_kind=='original_pdf' for d in bundle.documents):return False
    roots=[]
    for block in bundle.blocks:
        text=source_audit._mask_comments(block.text)
        begin=list(re.finditer(r'\\begin\{document\}',text));end=list(re.finditer(r'\\end\{document\}',text))
        if len(begin)==len(end)==1 and begin[0].end()<end[0].start():
            roots.append(text[begin[0].end():end[0].start()])
    if len(roots)!=1:return True
    return bool(re.search(r'\\(?:input|include)\s*\{|\\(?:if(?:false|true|defined|x)?\b|else\b|fi\b)',roots[0]))


def select_papers(plan,queue_root,limit,work_ids=None):
    with sqlite3.connect(queue_root/'corpus.sqlite3') as db:
        rows=db.execute('SELECT work_id,state,source_disposition FROM papers').fetchall()
    denominator={r[0] for r in rows}
    with sqlite3.connect(queue_root/'queue.sqlite3') as db:
        dispatched={r[0] for r in db.execute('SELECT DISTINCT work_id FROM jobs')}
    if work_ids and not set(work_ids)<=denominator:raise ValueError('work_outside_frozen_denominator')
    eligible=set(work_ids) if work_ids else {r[0] for r in rows if r[1]=='queued'}-dispatched
    gcs_pending={r[0] for r in rows if r[2]=='gcs_acquisition_required'}
    candidates=[p for p in plan['papers'] if p['source']=='arxiv' and p['id'] in eligible]
    # Prefer uncached originals; never redispatch a paper because the derived
    # corpus summary has not yet caught up with the authoritative job queue.
    papers=diverse_order([p for p in candidates if p['id'] in gcs_pending])
    papers+=diverse_order([p for p in candidates if p['id'] not in gcs_pending])
    return papers[:limit],len(denominator),dispatched


def write_progress(path,value):
    """Progress is mutable; source receipts and the cohort remain immutable."""
    temporary=path.with_suffix('.writing')
    temporary.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    temporary.replace(path)


class OfficialReader:
    def __init__(self):
        self.last=0.0
        self.batch_metadata={}
        self.batch_metadata_pin=None
        self.client=httpx.Client(follow_redirects=True,timeout=35,
            headers={'User-Agent':'SCLib-Production90/1.0 (research source provenance)'})

    def prepare_metadata(self,papers,directory):
        """One rate-limited request; unavailable entries retain the HTML route."""
        ids=[paper['id'].removeprefix('arxiv:') for paper in papers]
        if not ids:return
        response,pin=self.fetch(metadata_url(ids),directory/'metadata.atom')
        report=dict(schema='materials-official-batch-metadata/1',request=pin,requested_ids=ids,
            entries={},fallback_ids=ids,rate_limit_seconds=3.1)
        if response.get('status')==200:
            # A changed captured artifact is an integrity error, not an HTTP fallback.
            raw=rr.checked(response['artifact']).read_bytes()
            try:entries=parse_metadata(response,raw)
            except ValueError as exc:report['fallback_reason']=str(exc)
            else:
                self.batch_metadata=entries;self.batch_metadata_pin=pin
                report.update(entries=entries,fallback_ids=sorted(set(ids)-set(entries)))
        else:report['fallback_reason']='official_batch_metadata_unavailable'
        rr.put(directory/'BATCH_METADATA.json',report)

    def fetch(self,url,path):
        receipt=path.with_suffix(path.suffix+'.receipt.json')
        if receipt.exists():
            result=json.loads(receipt.read_bytes())
            if result['requested_url']!=url:raise ValueError('source_request_identity_changed')
            if result.get('artifact'):rr.checked(result['artifact'])
            return result,rr.reference(receipt)
        time.sleep(max(0,3.1-(time.monotonic()-self.last)));self.last=time.monotonic()
        result=dict(requested_url=url,requested_at=datetime.now(timezone.utc).isoformat())
        try:
            with self.client.stream('GET',url) as response:
                result.update(status=response.status_code,final_url=str(response.url),content_type=response.headers.get('content-type'))
                data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>64*1024**2:raise ValueError('source_response_byte_bound')
            rr.immutable(path,bytes(data));result['artifact']=rr.reference(path)
        except Exception as exc:result['error_class']=type(exc).__name__
        rr.put(receipt,result)
        return result,rr.reference(receipt)


class OfficialVersionUnavailable(ValueError):
    """A remote version response is unusable; verified PDF fallback is allowed."""


def preflight(paper,folder,cache,plan_hash,official):
    work=paper['id'];aid=work.removeprefix('arxiv:');folder.mkdir(parents=True,exist_ok=True)
    existing=folder/'PREFLIGHT.json'
    if existing.exists():
        pin=rr.reference(existing);saved,bundle,_=rr.source_input(pin)
        if saved['work_id']!=work:raise ValueError('source_resume_identity_changed')
        return dict(work_id=work,state='source_ready',preflight=pin,profile='core',
            route=saved['route'],version=saved['latest_version_observed'],blocks=len(bundle.blocks),
            characters=sum(len(b.text) for b in bundle.blocks))
    acquisition=cache/'acquisitions'/plan_hash/(digest(work)+'.json');bundle=None;gcs_pin=None
    if acquisition.exists():
        gcs_pin=rr.reference(acquisition);captured=json.loads(acquisition.read_bytes())
        if captured['state']=='bundled':bundle=load_bundle(cache/'bundles'/(captured['bundle_sha256']+'.json'))
    metadata_entry=getattr(official,'batch_metadata',{}).get(aid)
    metadata_format='abs_html'
    if metadata_entry is not None:
        if metadata_entry['withdrawn']:raise ValueError('reader_source_advisory_hold')
        metadata_pin=official.batch_metadata_pin
        version=metadata_entry['version'];metadata_format='arxiv_atom_batch'
    else:
        meta,metadata_pin=official.fetch('https://arxiv.org/abs/'+aid,folder/'abstract.html')
        if meta.get('status')!=200:raise ValueError('official_metadata_unavailable')
        version=latest_version(rr.checked(meta['artifact']).read_text(errors='replace'),aid)
    if bundle is None:
        kind='src' if any(c['source_kind']=='archive' for c in paper.get('candidates',[])) else 'pdf'
    else:
        kind='pdf' if needs_pdf(bundle) or any(d.source_kind=='original_pdf' for d in bundle.documents) else 'src'
    version_requests=[];fallback_reason=None

    def version_bytes(request_kind):
        url=f'https://arxiv.org/{request_kind}/{aid}{version}'
        source,pin=official.fetch(url,folder/(version+'.'+request_kind))
        version_requests.append(source)
        if source.get('status')!=200 or source.get('final_url')!=url or not source.get('artifact'):
            raise OfficialVersionUnavailable('official_version_unavailable')
        # Receipt/hash failures are not caught as remote or parser failures.
        raw=rr.checked(source['artifact']).read_bytes()
        if request_kind=='pdf' and not raw.startswith(b'%PDF-'):
            raise OfficialVersionUnavailable('official_pdf_content_required')
        source_hash=sha(raw);cached=cache/'sources'/source_hash
        if cached.exists():
            if cached.read_bytes()!=raw:raise ValueError('source_cache_collision')
        else:private_write(cached,raw)
        return url,source,pin,source_hash,cached

    def parsed(cached,url,source_hash):
        reused=bool(bundle and {d.source_sha256 for d in bundle.documents}=={source_hash})
        if reused and any(d.source_kind=='original_pdf' and d.parser!='pypdf-plain' for d in bundle.documents):
            reused=False
        selected=bundle if reused else parse_local(cached,work_id=work,title=paper['title'],source_uri=url,
            publication_version=version,family=paper.get('material_family'),processing_permission='allowed',pdf_text_mode='plain')
        return selected,reused

    selected=None;reused=False
    try:
        url,source,source_pin,source_hash,cached=version_bytes(kind)
    except OfficialVersionUnavailable as exc:
        if kind=='pdf':raise
        fallback_reason=dict(stage='archive_response',error_class=type(exc).__name__)
    else:
        try:selected,reused=parsed(cached,url,source_hash)
        except Exception as exc:
            if kind=='pdf':raise
            fallback_reason=dict(stage='archive_parse',error_class=type(exc).__name__)
        if selected is not None and needs_pdf(selected):
            fallback_reason=dict(stage='archive_structure',reason='unresolved_document_structure')
    if fallback_reason is not None:
        url,source,source_pin,source_hash,cached=version_bytes('pdf')
        selected,reused=parsed(cached,url,source_hash)
    bundle=selected
    bh,bpath=save_bundle(cache,bundle)
    structure=source_audit.audit_source(cached,work_id=work,bundle=bundle)
    rr.put(folder/'STRUCTURE.json',structure)
    holds=sorted(set(structure['hold_codes'])-{'publication_version_unverified'})
    result=dict(schema='materials-source-preflight/1',work_id=work,route='gcs_verified' if reused else 'official_arxiv_version',
        bundle=rr.reference(bpath),bundle_sha256=bh,original=rr.reference(cached),structure=rr.reference(folder/'STRUCTURE.json'),
        official_metadata_receipt=metadata_pin,official_metadata_format=metadata_format,
        official_identity_verified=True,latest_version_observed=version,
        exact_version_binding=dict(publication_version=version,source_sha256=source_hash,
            official_bytes=source['artifact'],request_receipt=source_pin),
        version_requests=version_requests,hold_codes=holds,permits_bounded_passage_reading=True,
        permits_full_paper_ner=False,whole_paper_coverage_verified=False,scientific_acceptance=False,
        gcs_acquisition=gcs_pin,gcs_original_reused=reused,
        acquisition_policy='official-first-local-cache/1',pdf_fallback_reason=fallback_reason)
    rr.put(folder/'PREFLIGHT.json',result)
    pin=rr.reference(folder/'PREFLIGHT.json');rr.source_input(pin)
    return dict(work_id=work,state='source_ready',preflight=pin,profile='core',
        route=result['route'],version=version,blocks=len(bundle.blocks),characters=sum(len(b.text) for b in bundle.blocks))


def run(plan_path,queue_root,directory,cache,limit,ssh_host,work_ids=None,*,retry_held=False):
    try:import pypdf  # noqa: F401 -- fail before any network or ledger mutation
    except ImportError as exc:raise RuntimeError('Run source acquisition with runtime/materials-ner-venv/bin/python (PDF parser required).') from exc
    if not 1<=limit<=60:raise ValueError('source_batch_limit_must_be_1_to_60')
    plan,plan_hash=load_plan(plan_path);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        selected,denominator,dispatched=select_papers(plan,queue_root,limit,work_ids)
        cohort_path=directory/'COHORT.json'
        if cohort_path.exists():
            cohort=json.loads(cohort_path.read_bytes())
            if cohort['source_plan']['sha256']!=rr.reference(plan_path)['sha256']:raise ValueError('source_plan_changed')
        else:
            cohort=dict(schema='production90-source-cohort/1',source_plan=rr.reference(plan_path),
                source_plan_sha256=plan_hash,created_at=datetime.now(timezone.utc).isoformat(),papers=selected,
                selection='Frozen family-stratified deterministic order; no previous NER values used.',
                full_corpus_denominator=denominator,max_download_bytes=256*1024**2)
            rr.put(cohort_path,cohort)
        rr.put(directory/'ACQUISITION_POLICY.json',dict(
            schema='materials-source-acquisition-policy/1',policy='official-first-local-cache/1',
            cohort=rr.reference(cohort_path),new_gcs_transfers=0,
            local_gcs_receipts_reused=True,exact_official_version_required=True,
            archive_then_pdf_fallback=True,source_selection_changed=False))
        official=OfficialReader();rows=[]
        try:
            unfinished=False
            for paper in cohort['papers']:
                folder=directory/paper['id'][6:].replace('/','_')
                result=folder/'RESULT_RETRY.json'
                if not result.exists():result=folder/'RESULT.json'
                if (not result.exists() or (retry_held and result.name=='RESULT.json'
                        and json.loads(result.read_bytes())['state']=='source_route_held')):
                    unfinished=True;break
            if unfinished:official.prepare_metadata(cohort['papers'],directory)
            for paper in cohort['papers']:
                folder=directory/paper['id'][6:].replace('/','_');folder.mkdir(exist_ok=True)
                result_path=folder/'RESULT.json'
                retry_path=folder/'RESULT_RETRY.json'
                if retry_path.exists():result_path=retry_path
                row=json.loads(result_path.read_bytes()) if result_path.exists() else None
                if row is None or (retry_held and row['state']=='source_route_held' and not retry_path.exists()):
                    if row is not None:result_path=retry_path
                    try:row=preflight(paper,folder,cache,plan_hash,official)
                    except Exception as exc:row=dict(work_id=paper['id'],state='source_route_held',error_class=type(exc).__name__,reason=str(exc)[:300] if isinstance(exc,ValueError) else type(exc).__name__)
                    rr.put(result_path,row)
                rows.append(row)
                if paper['id'] not in dispatched:
                    with sqlite3.connect(queue_root/'corpus.sqlite3') as db:
                        db.execute('UPDATE papers SET state=?,last_receipt=? WHERE work_id=? AND full_ner_done=0 AND retained_rows=0',
                            (row['state'],str(result_path),paper['id']))
                write_progress(directory/'SOURCE_PROGRESS.json',dict(rows=rows,selected=len(cohort['papers']),
                    ready=sum(r['state']=='source_ready' for r in rows)))
                print(json.dumps(row),flush=True)
        finally:official.client.close()
        ready=[{k:r[k] for k in ('work_id','preflight','profile')} for r in rows if r['state']=='source_ready']
        rr.put(directory/('NER_SOURCES_RETRY.json' if retry_held else 'NER_SOURCES.json'),ready)
        return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','queue-root','directory','cache'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--limit',type=int,default=12);parser.add_argument('--ssh-host')
    parser.add_argument('--works-file',type=Path)
    parser.add_argument('--retry-held',action='store_true',help='One explicit recovery attempt; retain each original failure receipt.')
    a=parser.parse_args();run(a.plan,a.queue_root,a.directory,a.cache,a.limit,a.ssh_host,
        json.loads(a.works_file.read_bytes()) if a.works_file else None,retry_held=a.retry_held)
