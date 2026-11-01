"""Read canonical admissions without rebuilding legacy material JSON rows."""
import re
from collections import defaultdict
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import text

from models.materials_vnext import AdmittedTcPage, AdmittedTcResult, TcEvidenceLocation
from models.ml_foundation import ProductionAdmissionResponse
from services.materials_admission_scope import CURRENT_ADMISSION_WHERE
from services.materials_display_policy import PUBLIC_TC_DISPLAY_WHERE
from services.materials_context_sql import COMPOSITION_IDS, PROTOCOL_ID
from services.materials_display import display_projection
from services.materials_family import FAMILIES, FAMILY_SQL, current_family


FROM = f'''FROM material_claims c
    JOIN research_events ev ON ev.id=c.event_id
    JOIN material_states s ON s.id=ev.state_id
    JOIN research_samples rs ON rs.id=s.sample_id
    JOIN research_protocols rp ON rp.id=({PROTOCOL_ID})
    JOIN materials m ON m.id=c.material_id
    JOIN papers p ON p.id=c.paper_id
    JOIN works w ON w.id=c.work_id'''

BASE_WHERE = f'({CURRENT_ADMISSION_WHERE}) AND ({PUBLIC_TC_DISPLAY_WHERE})'


async def admitted_tc_page(db, *, query=None, material_id=None, family=None, pressure=None, criterion=None, limit=50, offset=0):
    clauses=[BASE_WHERE];params=dict(limit=limit,offset=offset)
    if material_id:
        params['material_id']=material_id;clauses.append('c.material_id=:material_id')
    if query:
        params['query']='%'+query.replace('\\','\\\\').replace('%',r'\%').replace('_',r'\_')+'%'
        clauses.append('(m.formula ILIKE :query OR c.paper_id ILIKE :query OR '
            "(m.material_semantics->'source_notation'->>'version'='materials-source-display/1' "
            "AND m.material_semantics->'source_notation'->>'formula_sha256'=encode(sha256(convert_to(m.formula,'UTF8')),'hex') "
            "AND m.material_semantics->'source_notation'->>'text' ILIKE :query) OR EXISTS "
            "(SELECT 1 FROM sample_compositions sc WHERE sc.sample_id=rs.id "
            f"AND sc.id = ANY({COMPOSITION_IDS}) "
            'AND sc.formula_raw ILIKE :query))')
    if pressure:
        params['pressure']=pressure;clauses.append("s.conditions->'pressure'->>'regime'=:pressure")
    if criterion:
        params['criterion']=criterion;clauses.append('c.tc_definition=:criterion')
    if family:
        if family not in FAMILIES:raise ValueError('Unknown material family')
        params['family']=family;clauses.append(f'({FAMILY_SQL})=:family')
    where=' WHERE '+' AND '.join(clauses)
    counts=dict((await db.execute(text('SELECT count(*) AS total,count(DISTINCT c.material_id) AS material_count,'
        'count(DISTINCT c.paper_id) AS paper_count '+FROM+where),params)).mappings().one())
    rows=(await db.execute(text(f'''SELECT c.id::text,c.material_id,c.paper_id,c.event_id::text,
        c.value_kelvin,c.value_lower_kelvin,c.value_upper_kelvin,c.value_relation,c.tc_definition,
        c.measurement_method,c.pressure_gpa,c.validity_status,c.extraction_metadata,m.formula,m.family,m.material_semantics,p.title,
        s.conditions,rs.sample_label,rs.composition_context,rp.method_raw,rp.details_raw,
        (SELECT jsonb_agg(jsonb_build_object('formula',sc.formula_raw,'basis',sc.composition_basis) ORDER BY sc.id)
         FROM sample_compositions sc WHERE sc.sample_id=rs.id
           AND sc.id = ANY({COMPOSITION_IDS})) AS compositions
        '''+FROM+where+' ORDER BY c.paper_id,c.id LIMIT :limit OFFSET :offset'),params)).mappings().all()
    evidence=defaultdict(list);versions=defaultdict(set);source_pins=defaultdict(set)
    if rows:
        links=(await db.execute(text("SELECT event_id::text,locator FROM event_evidence WHERE event_id=ANY(:ids) AND link_type='source' ORDER BY id"),dict(ids=[UUID(r['event_id']) for r in rows]))).mappings()
        for link in links:
            locator=link['locator']
            pin=locator.get('representation_input',{}).get('sha256')
            if pin:source_pins[link['event_id']].add(pin)
            label=locator.get('original_locator','Original source')
            # Return source coordinates and hashes, never local cache paths.
            if not isinstance(label,str) or label.startswith(('/', 'file:')):label='Original source'
            page=re.search(r'(?:^|:)pdf_page:([1-9]\d*)(?=:|$)',label)
            evidence[link['event_id']].append(TcEvidenceLocation(locator=label,
                page=int(page[1]) if page else None,quote_sha256=locator['quote_sha256'],
                field_paths=locator.get('field_paths',[])))
        links=(await db.execute(text('''SELECT o.claim_id::text,r.provider_revision FROM claim_source_occurrences o
            JOIN source_revisions r ON r.id=o.source_revision_id WHERE o.claim_id=ANY(:ids)'''),dict(ids=[UUID(r['id']) for r in rows]))).all()
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
        item=AdmittedTcResult(id=row['id'],material_id=row['material_id'],formula=row['formula'],
            family=current_family(row['formula'],row['family'],row['material_semantics']),
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
            evidence=evidence[row['event_id']],validity_status=row['validity_status'],review=review)
        item.display=display_projection(item.model_dump(),source_pins[row['event_id']])
        items.append(item)
    return AdmittedTcPage(items=items,**counts,limit=limit,offset=offset)
