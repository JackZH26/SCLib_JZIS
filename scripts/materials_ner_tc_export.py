"""Export admitted canonical claims and reconcile the frozen corpus ledger."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from collections import Counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ingestion.materials_ner import reviewed_reader as rr
from ingestion.materials_ner.contract import Quantity
from ingestion.materials_ner.quantities import normalize
from materials_ner_production90 import read_pin
from services.materials_admission_scope import (
    ADMISSION_POLICY_WHERE, CURRENT_ADMISSION_WHERE, EXCLUSION_REASON_SQL, SCOPE_VERSION,
)


def read_source_representation(pin,evidence_root=None):
    """Read a verified source from its capture or a portable hash-addressed copy.

    An explicit evidence directory is authoritative. Missing or altered copies
    must fail rather than silently falling back to the original host's paths.
    """
    if evidence_root is None:return read_pin(pin)
    digest=pin['sha256']
    if not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
        raise ValueError('export_evidence_hash_invalid')
    root=Path(evidence_root).expanduser().resolve()
    path=root/(digest+'.json')
    if not path.resolve().is_relative_to(root):
        raise ValueError('export_evidence_path_outside_bundle')
    return read_pin(dict(pin,path=str(path)))


async def export(database_url,output,*,evidence_root=None):
    if evidence_root is not None:
        evidence_root=Path(evidence_root).expanduser().resolve()
        if not evidence_root.is_dir():raise ValueError('export_evidence_directory_missing')
    engine=create_async_engine(database_url,isolation_level='REPEATABLE READ');result=[];cache={}
    try:
        async with engine.connect() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            snapshot_at=(await db.execute(text('SELECT CURRENT_TIMESTAMP'))).scalar_one().isoformat()
            admissions=[dict(r) for r in (await db.execute(text(f'''SELECT c.id::text,c.paper_id,
                c.validity_status,p.status AS paper_status,w.publication_status,
                {EXCLUSION_REASON_SQL} AS exclusion_reason
                FROM material_claims c JOIN papers p ON p.id=c.paper_id JOIN works w ON w.id=c.work_id
                WHERE {ADMISSION_POLICY_WHERE} ORDER BY c.paper_id,c.id'''))).mappings()]
            excluded=[r for r in admissions if r['exclusion_reason'] is not None]
            eligible_ids={r['id'] for r in admissions if r['exclusion_reason'] is None}
            rows=(await db.execute(text('''SELECT c.id::text,c.paper_id,c.work_id::text,c.result_key,c.event_id::text,
                c.value_kelvin,c.value_lower_kelvin,c.value_upper_kelvin,c.value_relation,c.tc_definition,
                c.measurement_method,c.raw_record,c.extraction_metadata,c.magnetic_field_t,c.pressure_state,c.pressure_gpa,
                c.validity_status,p.status AS paper_status,w.publication_status,
                s.id::text AS state_id,s.conditions,s.pressure_status,rs.id::text AS sample_id,
                rs.sample_label,rs.composition_context,rp.id::text AS protocol_id,rp.method_raw,rp.details_raw,
                ev.context->'materials_context'->'composition_ids' AS composition_ids
                FROM material_claims c JOIN research_events ev ON ev.id=c.event_id
                JOIN material_states s ON s.id=ev.state_id JOIN research_samples rs ON rs.id=s.sample_id
                JOIN research_protocols rp ON rp.id::text=ev.context->'materials_context'->>'protocol_id'
                JOIN papers p ON p.id=c.paper_id JOIN works w ON w.id=c.work_id
                WHERE '''+CURRENT_ADMISSION_WHERE+' ORDER BY c.paper_id,c.result_key'))).mappings().all()
            for raw in rows:
                row=dict(raw)
                comp=(await db.execute(text('''SELECT id::text,formula_raw,composition_basis,composition_payload
                    FROM sample_compositions WHERE id::text=ANY(:ids) ORDER BY id'''),dict(ids=row.pop('composition_ids')))).mappings().all()
                row['compositions']=[dict(x) for x in comp]
                row['publication_versions']=sorted((await db.execute(text('''SELECT DISTINCT r.provider_revision
                    FROM claim_source_occurrences o JOIN source_revisions r ON r.id=o.source_revision_id
                    WHERE o.claim_id=CAST(:id AS uuid)'''),dict(id=row['id']))).scalars().all())
                links=(await db.execute(text("SELECT locator FROM event_evidence WHERE event_id=CAST(:id AS uuid) AND link_type='source' ORDER BY id"),dict(id=row['event_id']))).scalars().all()
                row['evidence']=[]
                for locator in links:
                    pin=locator['representation_input']
                    if pin['sha256'] not in cache:
                        original=read_source_representation(pin,evidence_root)
                        cache[pin['sha256']]={b['id']:b for b in original.get('bundle',original)['blocks']}
                    blockid=locator['section_path'].split('#',1)[1];block=cache[pin['sha256']][blockid]
                    quote=block['text'][locator['char_start']:locator['char_end']]
                    if hashlib.sha256(quote.encode()).hexdigest()!=locator['quote_sha256']:raise ValueError('export_source_quote_mismatch')
                    row['evidence'].append(dict(quote=quote,quote_location=locator['original_locator'],
                        block_id=blockid,start_char=locator['char_start'],end_char=locator['char_end'],
                        field_paths=locator['field_paths'],source_representation_sha256=pin['sha256']))
                if not row['evidence']:raise ValueError('admitted_claim_without_source_evidence')
                row['quality']=row['extraction_metadata']['production_admission']
                row['quantity']=row['extraction_metadata']['materials_outcome']['quantity']
                row['normalized_conditions']=[dict(condition_id=c['id'],kind=c['kind'],role=c['role'],
                    normalized=normalize(c['kind'],Quantity.model_validate(c['quantity']))['normalized'])
                    for c in row['conditions']['items']]
                row['legacy_magnetic_field_t']=row['magnetic_field_t']
                fields=[c['normalized']['value'] for c in row['normalized_conditions']
                    if c['role']=='measurement' and c['kind'] in {'magnetic_flux_density','mu0_h'}
                    and c['normalized'].get('relation')=='exact' and c['normalized'].get('value') is not None]
                row['magnetic_field_t']=fields[0] if len(set(fields))==1 else None
                row['magnetic_field_t_source']='typed_measurement_conditions' if row['magnetic_field_t'] is not None else None
                regime=row['conditions']['pressure']['regime']
                row['ambient']=True if regime=='explicit_ambient' else False if regime=='nonambient' else None
                row['split_group']=row['work_id'];row['sample_group']=row['sample_id']
                row['cross_paper_reused_sample_group']='unresolved'
                row['missing_fields']=[k for k in ['sample_label','method_raw'] if row[k] is None]
                if row['pressure_status']=='not_reported':row['missing_fields'].append('pressure')
                row['feature_scope']='As-written composition and explicit Tc with retained conditions; no measured-stoichiometry or full-paper recall claim.'
                result.append(row)
            if len({r['id'] for r in result})!=len(result):raise ValueError('duplicate_export_claim')
            if {r['id'] for r in result}!=eligible_ids:raise ValueError('canonical_export_join_loss')
            count=(await db.execute(text('SELECT count(*) FROM material_claims c WHERE '+ADMISSION_POLICY_WHERE))).scalar_one()
            if len(admissions)!=count:raise ValueError('canonical_admission_lifecycle_join_loss')
    finally:await engine.dispose()
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    path=output/'MATERIALS_TC_DATASET.jsonl'
    rr.immutable(path,''.join(json.dumps(r,sort_keys=True,ensure_ascii=False)+'\n' for r in result).encode())
    exclusions=output/'EXCLUDED_RESULTS.jsonl'
    rr.immutable(exclusions,''.join(json.dumps(r,sort_keys=True,ensure_ascii=False)+'\n' for r in excluded).encode())
    quality_counts=dict(Counter(r['quality']['quality_status'] for r in result))
    report=dict(schema='materials-production90-export/2',rows=len(result),papers=len({r['paper_id'] for r in result}),
        scope=SCOPE_VERSION,snapshot_at=snapshot_at,canonical_admitted_rows=len(admissions),
        canonical_counts_by_paper=dict(Counter(r['paper_id'] for r in admissions)),
        excluded_rows=len(excluded),exclusion_counts=dict(Counter(r['exclusion_reason'] for r in excluded)),
        exclusions=rr.reference(exclusions),
        dataset=rr.reference(path),quality=next(iter(quality_counts)) if len(quality_counts)==1 else 'mixed_record_review_states',
        quality_counts=quality_counts,independent_expert_review=False,
        evidence_read_mode='portable_hash_bundle' if evidence_root is not None else 'original_capture_paths',
        evidence_files_read=len(cache),
        whole_corpus_accuracy_measured=False,production_site_updated=False)
    rr.put(output/'EXPORT_REPORT.json',report)
    return report,result


def inventory(campaign,queue_root,rows,export_report):
    campaign=Path(campaign);queue_root=Path(queue_root);counts={}
    if 'canonical_counts_by_paper' in export_report:counts=export_report['canonical_counts_by_paper']
    else:
        for row in rows:counts[row['paper_id']]=counts.get(row['paper_id'],0)+1
    with sqlite3.connect(queue_root/'corpus.sqlite3') as ledger,sqlite3.connect(queue_root/'queue.sqlite3') as queue:
        queue.row_factory=sqlite3.Row
        for manifest in sorted(campaign.glob('batch-*/BATCH.json')):
            batch=json.loads(manifest.read_bytes())
            for held in batch.get('preparation_holds',[]):
                ledger.execute('UPDATE papers SET state=?,last_receipt=? WHERE work_id=?',('source_route_held',str(manifest),held['work_id']))
            for job in batch['jobs']:
                actual=queue.execute('SELECT state,attempts,result_path FROM jobs WHERE id=?',(job['job_id'],)).fetchone()
                if not actual:continue
                d=manifest.parent/job['work_id'][6:].replace('/','_');rp=d/'RESULT.json'
                result=json.loads(rp.read_bytes()) if rp.exists() else {}
                packet=d/'PACKET.json'
                candidates=len(json.loads(json.loads(packet.read_bytes())['raw_output'])['results']) if packet.exists() else None
                done=actual['state'] in {'succeeded','quarantined'} or result.get('error_code')=='production_tc_schema_invalid'
                if actual['state']=='running':state='running'
                elif counts.get(job['work_id']):state='tc_pass_partial_ingested'
                elif candidates==0:state='no_target_returned_unverified'
                elif candidates or actual['state']=='quarantined':state='candidates_held'
                elif actual['state']=='queued':state='queued'
                else:state='extraction_failed_or_uncertain'
                ledger.execute('UPDATE papers SET state=?,full_ner_done=?,retained_rows=?,last_receipt=? WHERE work_id=?',
                    (state,int(done),counts.get(job['work_id'],0),str(rp if rp.exists() else manifest),job['work_id']))
        for work,count in counts.items():
            ledger.execute('UPDATE papers SET retained_rows=? WHERE work_id=?',(count,work))
        report=dict(frozen_arxiv_works=ledger.execute('SELECT count(*) FROM papers').fetchone()[0],
            by_state=dict(ledger.execute('SELECT state,count(*) FROM papers GROUP BY state').fetchall()),
            new_tc_text_passes=ledger.execute('SELECT sum(full_ner_done) FROM papers').fetchone()[0],
            canonical_records=ledger.execute('SELECT sum(retained_rows) FROM papers').fetchone()[0],
            current_dataset_records=len(rows),excluded_from_current_dataset=export_report.get('excluded_rows',0),
            canonical_export=export_report['dataset'],updated_at=datetime.now(timezone.utc).isoformat(),
            coverage_scope='Available-text explicit Tc passes; neither whole-paper coverage nor full-paper recall.',
            full_corpus_complete=False,production_deployed=False)
        if report['canonical_records']!=sum(counts.values()):raise ValueError('ledger_canonical_count_mismatch')
        (campaign/'CORPUS_PROGRESS.json').write_text(json.dumps(report,indent=2)+'\n')
        return report


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--database-url',required=True);p.add_argument('--output',required=True)
    p.add_argument('--campaign');p.add_argument('--queue-root')
    p.add_argument('--evidence-root',type=Path,help='Directory of source representations named <sha256>.json; no original-path fallback.')
    p.add_argument('--export-only',action='store_true',help='Export from a read-only database snapshot without updating the corpus ledger.')
    a=p.parse_args(argv)
    if not a.export_only and (a.campaign is None or a.queue_root is None):
        p.error('--campaign and --queue-root are required unless --export-only is set')
    report,rows=asyncio.run(export(a.database_url,a.output,evidence_root=a.evidence_root))
    print(json.dumps(report if a.export_only else inventory(a.campaign,a.queue_root,rows,report),indent=2))


if __name__=='__main__':main()
