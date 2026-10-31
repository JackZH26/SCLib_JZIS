"""Read canonical admissions without rebuilding legacy material JSON rows."""
import re
from collections import defaultdict
from urllib.parse import quote

from sqlalchemy import text

from models.materials_vnext import AdmittedTcPage, AdmittedTcResult, TcEvidenceLocation
from models.ml_foundation import ProductionAdmissionResponse
from services.materials_admission_scope import CURRENT_ADMISSION_WHERE


FROM = '''FROM material_claims c
    JOIN research_events ev ON ev.id=c.event_id
    JOIN material_states s ON s.id=ev.state_id
    JOIN research_samples rs ON rs.id=s.sample_id
    JOIN research_protocols rp ON rp.id::text=ev.context->'materials_context'->>'protocol_id'
    JOIN materials m ON m.id=c.material_id
    JOIN papers p ON p.id=c.paper_id
    JOIN works w ON w.id=c.work_id'''

BASE_WHERE = CURRENT_ADMISSION_WHERE


async def admitted_tc_page(db, *, query=None, material_id=None, pressure=None, criterion=None, limit=50, offset=0):
    clauses=[BASE_WHERE];params=dict(limit=limit,offset=offset)
    if material_id:
        params['material_id']=material_id;clauses.append('c.material_id=:material_id')
    if query:
        params['query']='%'+query.replace('\\','\\\\').replace('%',r'\%').replace('_',r'\_')+'%'
        clauses.append('(m.formula ILIKE :query OR c.paper_id ILIKE :query OR EXISTS '
            "(SELECT 1 FROM sample_compositions sc WHERE sc.sample_id=rs.id "
            "AND sc.id::text IN (SELECT jsonb_array_elements_text(ev.context->'materials_context'->'composition_ids')) "
            'AND sc.formula_raw ILIKE :query))')
    if pressure:
        params['pressure']=pressure;clauses.append("s.conditions->'pressure'->>'regime'=:pressure")
    if criterion:
        params['criterion']=criterion;clauses.append('c.tc_definition=:criterion')
    where=' WHERE '+' AND '.join(clauses)
    counts=dict((await db.execute(text('SELECT count(*) AS total,count(DISTINCT c.material_id) AS material_count,'
        'count(DISTINCT c.paper_id) AS paper_count '+FROM+where),params)).mappings().one())
    rows=(await db.execute(text('''SELECT c.id::text,c.material_id,c.paper_id,c.event_id::text,
        c.value_kelvin,c.value_lower_kelvin,c.value_upper_kelvin,c.value_relation,c.tc_definition,
        c.measurement_method,c.pressure_gpa,c.validity_status,c.extraction_metadata,m.formula,p.title,
        s.conditions,rs.sample_label,rs.composition_context,rp.method_raw,rp.details_raw,
        (SELECT jsonb_agg(jsonb_build_object('formula',sc.formula_raw,'basis',sc.composition_basis) ORDER BY sc.id)
         FROM sample_compositions sc WHERE sc.sample_id=rs.id
           AND sc.id::text IN (SELECT jsonb_array_elements_text(ev.context->'materials_context'->'composition_ids'))) AS compositions
        '''+FROM+where+' ORDER BY c.paper_id,c.id LIMIT :limit OFFSET :offset'),params)).mappings().all()
    evidence=defaultdict(list);versions=defaultdict(set)
    if rows:
        links=(await db.execute(text("SELECT event_id::text,locator FROM event_evidence WHERE event_id::text=ANY(:ids) AND link_type='source' ORDER BY id"),dict(ids=[r['event_id'] for r in rows]))).mappings()
        for link in links:
            locator=link['locator'];label=locator.get('original_locator','Original source')
            # Return source coordinates and hashes, never local cache paths.
            if not isinstance(label,str) or label.startswith(('/', 'file:')):label='Original source'
            page=re.search(r'(?:^|:)pdf_page:([1-9]\d*)(?=:|$)',label)
            evidence[link['event_id']].append(TcEvidenceLocation(locator=label,
                page=int(page[1]) if page else None,quote_sha256=locator['quote_sha256'],
                field_paths=locator.get('field_paths',[])))
        links=(await db.execute(text('''SELECT o.claim_id::text,r.provider_revision FROM claim_source_occurrences o
            JOIN source_revisions r ON r.id=o.source_revision_id WHERE o.claim_id::text=ANY(:ids)'''),dict(ids=[r['id'] for r in rows]))).all()
        for claim,revision in links:
            if revision:versions[claim].add(revision)
    items=[]
    for row in rows:
        metadata=row['extraction_metadata'];review=ProductionAdmissionResponse.from_extraction_metadata(metadata)
        if review is None:raise ValueError('Invalid canonical admission provenance')
        pressure_context=row['conditions']['pressure'];condition_id=pressure_context.get('condition_id')
        measured=next((x for x in row['conditions']['items'] if x['id']==condition_id),None)
        pressure_raw=measured['quantity']['raw'] if measured else pressure_context.get('basis_raw')
        source_versions=sorted(versions[row['id']]);version=source_versions[0] if len(source_versions)==1 else ''
        version=version if re.fullmatch(r'v[1-9]\d*',version) else ''
        aid=row['paper_id'].removeprefix('arxiv:')
        source_url='https://arxiv.org/pdf/'+quote(aid,safe='/')+version
        context=row['composition_context']
        definition=metadata.get('result_semantics',{}).get('definition',{})
        items.append(AdmittedTcResult(id=row['id'],material_id=row['material_id'],formula=row['formula'],
            compositions=row['compositions'] or [],sample_label=row['sample_label'],
            sample_form=context.get('form_raw') or context.get('target_kind'),substrate=context.get('substrate_raw'),
            value_kelvin=row['value_kelvin'],value_lower_kelvin=row['value_lower_kelvin'],
            value_upper_kelvin=row['value_upper_kelvin'],value_relation=row['value_relation'],
            quantity=metadata['materials_outcome']['quantity'],criterion=row['tc_definition'],
            criterion_raw=definition.get('criterion_raw'),
            method=row['measurement_method'] or 'unspecified',method_raw=row['method_raw'],
            measurement_context=row['details_raw'],pressure_regime=pressure_context['regime'],
            pressure_gpa=row['pressure_gpa'],pressure_raw=pressure_raw,paper_id=row['paper_id'],
            paper_title=row['title'],source_url=source_url,source_versions=source_versions,
            evidence=evidence[row['event_id']],validity_status=row['validity_status'],review=review))
    return AdmittedTcPage(items=items,**counts,limit=limit,offset=offset)
