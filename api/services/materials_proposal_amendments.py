"""Private retained editorial views using the existing review access boundary."""
from copy import deepcopy
from sqlalchemy import text
from models import materials_ner_amendments_v1 as schema
from services import materials_proposal_review as review
from services.materials_proposal_storage import canonical, digest
from services.materials_proposal_export import csv_files

COLUMNS = (
    'paper_id', 'parent_run_id', 'amendment_id', 'result_id', 'sample_id', 'state_id',
    'formula_as_written', 'composition_basis', 'tc_value', 'tc_lower', 'tc_upper', 'tc_unit',
    'source_quantity_json', 'criterion', 'criterion_as_written', 'method', 'method_class',
    'pressure_json', 'conditions_json', 'formula_assertions_json', 'qualifiers_json',
    'field_dispositions_json', 'holds_json', 'review_status', 'author_json',
)
RESULT_MAPPING = 'materials-reviewed-result-mapping/1'
RESULT_COLUMNS = (
    'paper_id','parent_run_id','amendment_id','result_id','sample_id','state_id',
    'formula_as_written','composition_basis','quantity_kind','quantity_name_as_written','component_as_written',
    'origin','source_role','value','lower','upper','unit','relation','source_quantity_json','normalized_json',
    'definition_json','dependencies_json','method','method_class','pressure_json','conditions_json',
    'formula_assertions_json','qualifiers_json','field_dispositions_json','validation_issues_json','holds_json',
    'review_status','source_review_json','author_json',
)


def validate_result_mapping(amendment, mapping):
    """Check native field/pointer parity; import owns scientific replay."""
    graph_version = amendment.get('graph', {}).get('schema_version')
    review.require(graph_version in {'materials-ner/13', 'materials-ner/14', 'materials-ner/15'}, 'amendment_graph_version')
    if graph_version in {'materials-ner/14', 'materials-ner/15'}:
        validation = amendment.get('validation', {})
        validator, registry = ('materials-ner-validation/1.29.0', 'materials-quantities/4.0.0') if graph_version == 'materials-ner/15' else (
            'materials-ner-validation/1.26.0', 'materials-quantities/3.0.0')
        review.require(validation.get('validator_version') == validator
            and validation.get('registry_version') == registry
            and mapping.get('schema') == RESULT_MAPPING, 'amendment_semantic_version_mismatch')
    semantics = 'materials-result-semantics/2' if graph_version == 'materials-ner/15' else 'materials-result-semantics/1'
    if mapping.get('schema') != RESULT_MAPPING:
        review.require(mapping.get('schema') == 'materials-reviewed-tc-mapping/1','amendment_mapping_version')
        return
    try:
        graph=amendment['graph']; records=mapping['records']; reviews=amendment['reviews']
        review.require(mapping['amendment_id']==amendment['amendment_id']
            and len(records)==len(reviews) and len({m['source_result_id'] for m in records})==len(records),
            'amendment_mapping_selection')
        for m,r in zip(records,reviews):
            index=next(i for i,x in enumerate(graph['results']) if x['id']==r['result_id'])
            result=graph['results'][index]; prefix=f'/results/{index}/'
            expected_normalized={key:value for key,value in amendment['validation'].get('normalized',{}).items() if key.startswith(prefix)}
            review.require(m['source_result_id']==r['result_id'] and m['parent_run_id']==amendment['parent_run_id']
                and m['amendment_id']==amendment['amendment_id'] and m['target_table'] is None and m['target_id'] is None
                and m['result_pointer']==f'/graph/results/{index}' and m['source_evidence_pointer']==f'/graph/results/{index}/evidence'
                and m['review_pointer']==f'/reviews/{reviews.index(r)}'
                and m['quantity_kind']==result['quantity_kind'] and m['source_quantity']==result['quantity']
                and m['dependencies']==result['dependencies'] and m['normalized']==expected_normalized
                and m['result_semantics']==dict(version=semantics,definition=result['definition'],qualifiers=result['qualifiers'])
                and m['review_status'] in {'quarantined','pending_review'} and isinstance(m['validation_issues'],list)
                and isinstance(m['holds'],list) and set(m['validation_issues']+r['holds']).issubset(m['holds'])
                and 'canonical_result_mapping_required' in m['holds']
                and all(m[key] is False for key in ['ready_for_canonical_insert','scientific_acceptance','ml_training_eligible']),
                'amendment_result_mapping_mismatch')
            for group,singular in [('samples','sample'),('states','state'),('protocols','protocol')]:
                owner=next(i for i,x in enumerate(graph[group]) if x['id']==result[singular+'_id'])
                review.require(m['source_'+singular+'_id']==result[singular+'_id']
                    and m[singular+'_pointer']==f'/graph/{group}/{owner}','amendment_mapping_owner')
    except review.ProposalIntegrityError:
        raise
    except (KeyError,TypeError,ValueError,StopIteration) as error:
        raise review.ProposalIntegrityError('amendment_result_mapping_invalid') from error


def storage_hash(amendment, mapping):
    return digest(dict(amendment=amendment, mapping=mapping))


async def ready(db):
    await review.schema_ready(db)
    value=(await db.execute(text('SELECT fingerprint FROM materials_ner_v1.schema_version WHERE version=:v'),
                           dict(v=schema.VERSION))).scalar_one_or_none()
    if value is None: raise review.ProposalUnavailable('amendment_storage_unavailable')
    review.require(value==schema.FINGERPRINT,'amendment_storage_version_mismatch')


async def list_for_run(db, actor, run_id):
    await review.admit(db,actor); await ready(db); review.identifier(run_id)
    rows=(await db.execute(text("""SELECT id,parent_run_id,parent_packet_hash,created_at,
      payload->'author' AS author,payload->'selected_result_ids' AS selected_result_ids
      FROM materials_ner_v1.amendments WHERE parent_run_id=:r ORDER BY id LIMIT 101"""),
      dict(r=run_id))).mappings().all()
    if len(rows)>100: raise review.ProposalUnavailable('amendment_list_size_limit')
    return dict(version=schema.VERSION, items=[dict(r,created_at=r['created_at'].isoformat()) for r in rows],
                authority=review.AUTHORITY)


async def detail(db, actor, run_id, amendment_id):
    await review.admit(db,actor); await ready(db)
    review.identifier(run_id); review.identifier(amendment_id)
    size=(await db.execute(text("""SELECT octet_length(payload::text)+octet_length(mapping::text)
      FROM materials_ner_v1.amendments WHERE parent_run_id=:r AND id=:i"""),
      dict(r=run_id,i=amendment_id))).scalar_one_or_none()
    if size is None: raise review.ProposalUnavailable('amendment_unavailable')
    if size>review.MAX_RESPONSE_BYTES: raise review.ProposalUnavailable('amendment_response_size_limit')
    row=(await db.execute(text("""SELECT a.payload,a.mapping,a.storage_hash,a.parent_packet_hash,
      r.packet_hash FROM materials_ner_v1.amendments a JOIN materials_ner_v1.runs r ON r.id=a.parent_run_id
      WHERE a.parent_run_id=:r AND a.id=:i"""),dict(r=run_id,i=amendment_id))).mappings().one()
    amendment,mapping=row['payload'],row['mapping']; body=deepcopy(amendment); body.pop('amendment_id')
    review.require(digest(body)==amendment_id and row['packet_hash']==row['parent_packet_hash']
                   and row['parent_packet_hash']==amendment['parent_packet_hash']
                   and amendment['parent_run_id']==run_id and mapping['amendment_id']==amendment_id
                   and storage_hash(amendment,mapping)==row['storage_hash'],'amendment_readback_mismatch')
    validate_result_mapping(amendment,mapping)
    return dict(amendment=amendment,mapping=mapping,storage_hash=row['storage_hash'],authority=review.AUTHORITY)


async def canonical_targets(db, actor, run_id, amendment_id, result_id):
    """Discover existing candidates; an immutable amendment never acquires an ID.

    Multiple retained interpretations are returned explicitly. Formula similarity,
    latest-row selection and disposable rehearsal anchors are not identity rules.
    The existing exact-result review endpoint owns source-version reads.
    """
    value = await detail(db, actor, run_id, amendment_id)
    if value['mapping']['schema'] == RESULT_MAPPING:
        raise review.ProposalUnavailable('canonical_result_mapping_unavailable')
    a = value['amendment']
    if result_id not in a['selected_result_ids']:
        raise review.ProposalUnavailable('amendment_result_not_selected')
    selected = next(x for x in a['graph']['results'] if x['id'] == result_id)
    expected = {k:v for k,v in selected.items() if k != 'evidence'}
    expected['amendment_id'] = amendment_id
    rows = (await db.execute(text("""SELECT c.id,c.event_id,c.material_id,c.work_id,
      c.source_snapshot_id,c.interpretation_revision,c.source_record_hash,
      c.raw_record=CAST(:raw AS jsonb) AS original_result_matches,
      c.extraction_metadata->'editorial_origin' AS origin,
      c.source_locator->>'result_pointer' AS result_pointer,
      e.context->'editorial_origin' AS event_origin,e.state_id,
      e.material_id AS event_material,s.material_id AS state_material,s.sample_id,
      p.material_id AS sample_material,p.work_id AS sample_work
      FROM material_claims c LEFT JOIN research_events e ON e.id=c.event_id
      LEFT JOIN material_states s ON s.id=e.state_id
      LEFT JOIN research_samples p ON p.id=s.sample_id
      WHERE c.paper_id=:paper AND c.source_locator->>'amendment_id'=:amendment
        AND c.result_key=:result
        AND e.context->'editorial_origin'->>'purpose'='pending_candidates'
      ORDER BY c.id LIMIT 11"""),dict(paper=a['work_id'],amendment=amendment_id,
          result=result_id,raw=canonical(expected)))).mappings().all()
    if len(rows)>10:
        raise review.ProposalUnavailable('amendment_target_size_limit')
    items=[]
    for row in rows:
        origin,event_origin=row['origin'],row['event_origin']
        review.require(row['original_result_matches'] and row['source_record_hash']==digest(expected)
            and isinstance(origin,dict) and origin.get('amendment_id')==amendment_id
            and origin.get('parent_run_id')==run_id and origin.get('author')==a['author']
            and isinstance(event_origin,dict) and event_origin.get('amendment_id')==amendment_id
            and event_origin.get('source_result_id')==result_id
            and row['result_pointer']==f"/graph/results/{a['graph']['results'].index(selected)}"
            and row['material_id']==row['event_material']==row['state_material']==row['sample_material']
            and row['work_id']==row['sample_work'] and row['sample_id'] is not None
            and row['source_snapshot_id'] is not None,'amendment_target_ownership_mismatch')
        items.append({k:str(row[k]) for k in ('id','event_id','state_id','sample_id',
            'material_id','work_id','source_snapshot_id')} | {
            'interpretation_revision':row['interpretation_revision'],
            'source_record_hash':row['source_record_hash'],
            'identity_status':'candidate_requires_independent_identity_review'})
    return dict(version='materials-amendment-targets/1',parent_run_id=run_id,
        amendment_id=amendment_id,storage_hash=value['storage_hash'],result_id=result_id,
        items=items,authority=review.AUTHORITY)


def export_rows(amendment,mapping):
    validate_result_mapping(amendment,mapping)
    def pointed(path):
        value=amendment
        for token in path.lstrip('/').split('/'):
            value=value[int(token)] if isinstance(value,list) else value[token]
        return value
    rows=[]
    for m in mapping['records']:
        q=m['source_quantity']; s=pointed(m['sample_pointer']); st=pointed(m['state_pointer'])
        p=pointed(m['protocol_pointer']); disposition=pointed(m['review_pointer'])
        if mapping['schema'] == RESULT_MAPPING:
            result=pointed(m['result_pointer'])
            rows.append(dict(paper_id=amendment['work_id'],parent_run_id=amendment['parent_run_id'],
                amendment_id=amendment['amendment_id'],result_id=m['source_result_id'],sample_id=m['source_sample_id'],state_id=m['source_state_id'],
                formula_as_written=s['formula_raw'],composition_basis=s['composition_basis'],quantity_kind=result['quantity_kind'],
                quantity_name_as_written=result['quantity_name_raw'],component_as_written=result['component_raw'],
                origin=result['origin'],source_role=result['source_role'],value=q['value'],lower=q['lower'],upper=q['upper'],unit=q['unit'],relation=q['relation'],
                source_quantity_json=q,normalized_json=m['normalized'],definition_json=result['definition'],dependencies_json=result['dependencies'],
                method=p['method'],method_class=p['method_class'],pressure_json=st['pressure'],conditions_json=st['conditions'],
                formula_assertions_json=s['additional_formula_assertions'],qualifiers_json=result['qualifiers'],
                field_dispositions_json=disposition['fields'],validation_issues_json=m['validation_issues'],holds_json=m['holds'],
                review_status=m['review_status'],source_review_json=amendment.get('source_review'),author_json=amendment['author']))
            continue
        rows.append(dict(paper_id=amendment['work_id'],parent_run_id=amendment['parent_run_id'],
            amendment_id=amendment['amendment_id'],result_id=m['source_result_id'],
            sample_id=m['source_sample_id'],state_id=m['source_state_id'],
            formula_as_written=s['formula_raw'],composition_basis=s['composition_basis'],
            tc_value=q['value'],tc_lower=q['lower'],tc_upper=q['upper'],tc_unit=q['unit'],
            source_quantity_json=q,criterion=m['result_semantics']['definition']['criterion'],
            criterion_as_written=m['result_semantics']['definition']['criterion_raw'],
            method=p['method'],method_class=p['method_class'],pressure_json=st['pressure'],
            conditions_json=st['conditions'],formula_assertions_json=s['additional_formula_assertions'],
            qualifiers_json=m['result_semantics']['qualifiers']+m['unmapped_qualifiers'],
            field_dispositions_json=disposition['fields'],holds_json=m['holds'],
            review_status='assistant_amendment_independent_review_pending',author_json=amendment['author']))
    return rows


def export(amendment,mapping):
    raw,contract=csv_files(export_rows(amendment,mapping),columns=RESULT_COLUMNS if mapping.get('schema')==RESULT_MAPPING else COLUMNS)
    if mapping.get('schema') == RESULT_MAPPING:
        for column in contract['columns']:
            if column['name'].endswith('_json'): column['type']='json_or_null'
    # Use the established reversible CSV escaping; JSON remains the lossless view.
    return raw,contract
