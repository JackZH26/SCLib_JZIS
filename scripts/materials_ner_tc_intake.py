"""Admit source-audited native Tc projections into the existing canonical schema.

The immutable provider packet, deterministic projection and source audit remain
distinct. This path creates no editorial amendment and grants no expert review.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from ingestion.materials_ner.contract import parse_extraction
from ingestion.materials_ner.quantities import normalize
from materials_ner_canonical_bridge import TABLES, _catalogue, _put, require
from materials_ner_db_bridge_v2 import apply_packet
from materials_ner_production90 import POLICY, digest, read_pin, qualify
from materials_ner_tc_projection import project
from materials_ner_tc_sampling import (draw, random_draw, verify as verify_sampling, retained,
    METHOD as SAMPLING_METHOD, RANDOM_METHOD, BATCH_ROUTE, RECORD_ROUTE)
from services.source_registry import SOURCE_REGISTRY_VERSION, import_source_provenance_bundle

VERSION = 'materials-native-tc-intake/1'
KEY = ('work_id', 'result_id', 'run_id', 'projection_sha256')


def sha_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def uid(*parts):
    return str(uuid5(NAMESPACE_URL, json.dumps([VERSION, *parts], sort_keys=True)))


def scoped_records(entry, projection):
    """Keep an explicit recovery population separate from unaffected siblings."""
    included=entry.get('included_result_ids')
    if included is None:return projection['records']
    require(isinstance(included,list) and included and all(isinstance(r,str) for r in included),
        'invalid_result_scope')
    require(len(set(included))==len(included),'duplicate_result_scope')
    require(set(included)<={r['result_id'] for r in projection['records']},'unknown_result_scope')
    return [r for r in projection['records'] if r['result_id'] in set(included)]


def checked_projection(entry):
    packet, projection = read_pin(entry['packet']), read_pin(entry['projection'])
    if packet.get('schema')=='materials-core-tc-packet/1':
        from ingestion.materials_ner.core_tc import project as compile_core
        actual=compile_core(packet,schema=projection['schema'])
    else:actual=project(packet)
    require(actual == projection, 'native_projection_changed')
    scoped_records(entry,projection)
    return packet, projection


def source_provenance(packet):
    return packet['receipt'].get('core_provenance',packet['receipt'].get('projector_provenance'))


def canonical_method(packet, protocol, result_id, audit):
    """Keep a literal method when available; omit unsupported optional metadata.

    This does not infer a synonym, alter the extraction graph, or change Tc,
    material, criterion, or conditions. Existing literal bindings stay stable.
    """
    method_class, method_raw = protocol['method_class'], protocol['method']
    if method_raw is not None or method_class == 'unspecified':
        return method_class, method_raw, [], []
    literals=[]
    if packet.get('schema')=='materials-core-tc-packet/1':
        fact=json.loads(packet['raw_output'])['results'][int(result_id[1:])-1]
        if fact.get('method_raw'):literals.append(fact['method_raw'])
    literals.append(method_class)
    witnesses=list(protocol['evidence'])
    reviewed=next((a for a in audit['records'] if a['run_id']==packet['run_id']
        and a['result_id']==result_id and a['verdict']=='correct'),None)
    if reviewed:witnesses.extend(reviewed['source_evidence'])
    bound=next(((method_class,e) for e in protocol['evidence'] if method_class in e['quote']),None)
    if bound is None:
        bound=next(((word,e) for word in literals for e in witnesses if word in e['quote']),None)
    if bound is None:
        omission=dict(path='/protocols/0/method_class',before=method_class,after='unspecified',
            reason='optional_method_without_source_bound_literal',stage='canonical_intake')
        return 'unspecified', None, [], [omission]
    literal,witness=bound
    block=next(b for b in packet['bundle']['blocks'] if b['id']==witness['block_id'])
    start=witness['start_char']+witness['quote'].index(literal)
    require(block['text'][start:start+len(literal)]==literal,'method_rebinding_mismatch')
    evidence=dict(path='/protocols/0/method',block_id=block['id'],document_id=block['document_id'],
        block_sha256=block['sha256'],locator=block['locator'],start_char=start,
        end_char=start+len(literal),quote_sha256=sha_text(literal))
    return method_class, literal, [evidence], []


def freeze(entries, *, seed, sampling_method=None):
    population = []
    for entry in entries:
        packet, projection = checked_projection(entry)
        for r in scoped_records(entry,projection):
            population.append(dict(work_id=r['work_id'], result_id=r['result_id'], run_id=r['run_id'],
                projection_sha256=projection['projection_sha256'], status=r['status'], holds=r['holds']))
    eligible = [r for r in population if r['status'] == 'eligible_for_source_audit']
    require(len(eligible)>0, 'native_audit_requires_eligible_records')
    require(len({tuple(r[k] for k in KEY) for r in population}) == len(population), 'duplicate_population_record')
    selected = sorted(eligible, key=lambda r:digest([seed, *[r[k] for k in KEY]]))
    body = dict(schema='materials-native-tc-sample/1', policy=POLICY, seed=seed,
        method='census_of_retained_records', created_at=datetime.now(timezone.utc).isoformat(),
        source_entries=entries, population=population, population_sha256=digest(population),
        input_results=len(population), eligible_results=len(eligible), held_results=len(population)-len(eligible),
        records=[{k:r[k] for k in KEY} for r in selected], independent_gold=False,
        prior_source_exposure=True, source_exposure_note='Development tranche; source inspected during triage. Not a blind benchmark.')
    if sampling_method is not None and sampling_method!=RANDOM_METHOD:
        raise ValueError('unsupported_native_sampling_method')
    if sampling_method==RANDOM_METHOD:
        body.update(random_draw(eligible,seed),prior_source_exposure=False,
            source_exposure_note='Prospective window membership and seed registered before source-audit verdicts.')
    elif len(eligible)>50:body.update(draw(eligible,seed))
    return {**body, 'selection_sha256':digest(body)}


def quality(selection, audit):
    report = qualify(selection, audit)
    packets = {}
    eligible = set()
    for entry in selection['source_entries']:
        packet, projection = checked_projection(entry)
        packets[packet['run_id']] = packet
        for r in scoped_records(entry,projection):
            if r['status'] == 'eligible_for_source_audit':
                eligible.add((r['work_id'],r['result_id'],r['run_id'],projection['projection_sha256']))
    if selection.get('method') in {SAMPLING_METHOD,RANDOM_METHOD}:
        require(eligible=={tuple(r[k] for k in KEY) for r in selection['population'] if r['status']=='eligible_for_source_audit'},
            'native_sampling_population_changed')
        verify_sampling(selection)
    else:require(eligible == {tuple(r[k] for k in KEY) for r in selection['records']}, 'native_census_population_changed')
    for row in audit['records']:
        packet = packets[row['run_id']]
        preflight = json.loads(source_provenance(packet)['preflight_json'])
        blocks = {b['id']:b for b in packet['bundle']['blocks']}
        for e in row['source_evidence']:
            require(e['original_source']['sha256'] == preflight['bundle']['sha256'], 'audit_source_not_from_run')
            require(e['block_id'] in blocks and blocks[e['block_id']]['text'][e['start_char']:e['end_char']] == e['quote'], 'audit_source_not_from_run')
    return report


def admission_quality(selection,audit,admission_route=BATCH_ROUTE):
    """Retain the original score; individual admission never turns a failed batch green."""
    report=quality(selection,audit)
    require(admission_route in {BATCH_ROUTE,RECORD_ROUTE},'unknown_admission_route')
    if admission_route==BATCH_ROUTE:
        require(report['qualified'],'production90_batch_below_threshold')
        return report
    correct=[r for r in audit['records'] if r['verdict']=='correct' and r.get('review_completed') is True]
    require(correct,'no_individually_source_checked_results')
    receipts={}
    for row in correct:
        pin=row.get('source_audit_receipt')
        require(pin is not None,'individual_source_audit_receipt_required')
        identity=(pin['path'],pin['sha256'])
        if identity not in receipts:receipts[identity]=read_pin(pin)
        source=receipts[identity]
        require(source.get('reviewer_kind')=='model','individual_source_audit_authorship_required')
        original=next((r for r in source['records'] if all(r[k]==row[k] for k in KEY)),None)
        fields=(*KEY,'verdict','review_completed','rationale','source_evidence')
        require(original is not None and all(original.get(k)==row.get(k) for k in fields),
            'individual_source_audit_verdict_changed')
    return report


@dataclass(frozen=True)
class AdmissionValidation:
    """One immutable quality validation reused within a single admission call."""
    selection_sha256: str
    audit_sha256: str
    admission_route: str
    report_json: str

    @classmethod
    def build(cls,selection,audit,admission_route=BATCH_ROUTE):
        report=admission_quality(selection,audit,admission_route)
        return cls(selection['selection_sha256'],digest(audit),admission_route,json.dumps(report,sort_keys=True))

    def report(self,selection,audit,admission_route):
        require(self.selection_sha256==selection['selection_sha256']
            and self.selection_sha256==digest({k:v for k,v in selection.items() if k!='selection_sha256'})
            and self.audit_sha256==digest(audit) and self.admission_route==admission_route,
            'admission_validation_scope_changed')
        return json.loads(self.report_json)


def prepare(entry, *, bindings, captured_at, selection, audit, excluded_result_ids=(),admission_route=BATCH_ROUTE,validation=None):
    packet, projection = checked_projection(entry)
    # The full window was validated once by admit(); every source projection and
    # original byte binding below is still checked when its rows are prepared.
    report = (admission_quality(selection,audit,admission_route) if validation is None
        else validation.report(selection,audit,admission_route))
    require(datetime.fromisoformat(captured_at).tzinfo is not None, 'capture_timezone_required')
    verdicts = {tuple(r[k] for k in KEY):r['verdict'] for r in audit['records']}
    selected = [r for r in retained(projection,selection,audit,admission_route=admission_route) if r['result_id'] not in excluded_result_ids]
    require(selected, 'no_source_checked_native_results')
    pv=source_provenance(packet); pre=json.loads(pv['preflight_json'])
    version=pre['exact_version_binding']['publication_version']; source=pre['original']
    require(hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()==source['sha256'], 'original_source_changed')
    original=read_pin(pre['bundle']); original=original.get('bundle',original)
    require(original==packet['bundle'], 'source_bundle_changed')
    require(set(bindings['samples'])=={r['graph']['samples'][0]['id'] for r in selected}, 'sample_bindings_required')
    require(bindings['purpose']=='pending_candidates', 'native_intake_purpose')
    rows={name:[] for name in TABLES}
    registry=dict(version=SOURCE_REGISTRY_VERSION, source_revisions=[],source_captures=[],claim_source_occurrences=[])
    scope=[packet['run_id'],projection['projection_sha256'],bindings['paper']['id'],bindings['snapshot']['id']]
    target=lambda group,key:uid(scope,group,key)
    origin=dict(run_id=packet['run_id'],packet_hash=packet['packet_hash'],projection_sha256=projection['projection_sha256'],
        extraction_model=pv['config']['model'],model_version=pv['config'].get('model_version'),
        model_version_status='provider_identifier_only' if not pv['config'].get('model_version') else 'reported',
        extraction_configuration_sha256=digest(pv['config']),terminal_pin=pv['terminal_pin'],
        identity_binding_sha256=digest(bindings),independent_expert_review=False)
    if packet.get('schema')=='materials-core-tc-packet/1':
        origin.update(extraction_date=pv['extraction_date'],model_output_contract='materials-core-tc-output/1',
            native_graph_author='deterministic_core_tc_compiler')
        packet_id=uid(scope,'core-provider-packet') if projection['schema'] in {'production90-core-tc-projection/4','production90-core-tc-projection/5','production90-core-tc-projection/6','production90-core-tc-projection/7','production90-core-tc-projection/8'} else uid(packet['run_id'],'core-provider-packet')
        rows['evidence_artifacts'].append(dict(id=packet_id,kind='literature_locator',
            schema_version=packet['schema'],source='luna_core_tc_model_output',record_sha256=packet['packet_hash'],
            bytes_sha256=entry['packet']['sha256'],hash_status='verified',access='restricted',uri=entry['packet']['path'],
            metadata={**origin,'is_original_paper':False,'provider_raw_output_sha256':sha_text(packet['raw_output'])}))
    projection_id=uid(projection['projection_sha256'],'projection-artifact')
    rows['evidence_artifacts'].append(dict(id=projection_id,kind='literature_locator',schema_version=projection['schema'],
        source='deterministic_native_tc_projection',record_sha256=projection['projection_sha256'],
        bytes_sha256=entry['projection']['sha256'],hash_status='verified',access='restricted',uri=entry['projection']['path'],
        metadata={**origin,'is_original_paper':False,'scientific_values_modified':False,'original_packet':entry['packet']}))
    source_ids={}
    for doc in packet['bundle']['documents']:
        require(doc['source_sha256']==source['sha256'], 'multiple_original_source_route_required')
        representation={'original_pdf':'pdf','original_tex':'arxiv_source'}.get(doc['source_kind'])
        require(representation is not None, 'unsupported_original_representation')
        revision=uid(bindings['paper']['id'],version,'source-revision')
        capture=uid(revision,source['sha256'],captured_at,'capture')
        artifact=uid(packet['work_id'],version,source['sha256'],'original-source')
        source_ids[doc['id']]=(revision,capture,artifact,doc)
        registry['source_revisions'].append(dict(id=revision,paper_id=bindings['paper']['id'],work_id=bindings['work']['id'],
            revision_key='arxiv:'+version,provider_revision=version,version_status='pinned',source_version_public_at=None,
            availability_status='unknown',availability_basis='unknown',
            metadata_sha256=digest(dict(source_work_id=packet['work_id'],provider_revision=version))))
        registry['source_captures'].append(dict(id=capture,source_revision_id=revision,
            capture_key=digest(dict(bytes=source['sha256'],local_verification_at=captured_at)),
            captured_at=captured_at,bytes_sha256=source['sha256'],representation=representation))
        metadata=dict(source_work_id=packet['work_id'],provider_revision=version,source_kind=doc['source_kind'],
            redistribution_permission=doc['redistribution_permission'])
        rows['evidence_artifacts'].append(dict(id=artifact,kind='literature_locator',schema_version='original-source/1',
            source=packet['work_id'],source_version=version,bytes_sha256=source['sha256'],record_sha256=digest(metadata),
            hash_status='verified',access='restricted',uri=source['path'],metadata=metadata))
    results=[]
    for item in selected:
        graph=item['graph']; parsed=parse_extraction(graph)
        extra_evidence=[]
        s,st,p,r=[graph[g][0] for g in ['samples','states','protocols','results']]
        require(s['formula_raw'] is not None and s['identity_resolution']=='source_scoped','unresolved_native_material_identity')
        require(not s['additional_formula_assertions'], 'multiple_formula_assertions_require_mapping')
        material=bindings['samples'][s['id']]['id']; sid=target('sample',s['id']); state=target('state',st['id'])
        protocol=target('protocol',p['id']); composition=target('composition',s['id'])
        context={k:deepcopy(s[k]) for k in ['identity_resolution','target_kind','form_raw','substrate_raw','additional_formula_assertions','formula_unavailability']}
        rows['research_samples'].append(dict(id=sid,material_id=material,work_id=bindings['work']['id'],sample_label=s['label'],
            preparation={},composition_context=context,source_artifact_id=projection_id))
        rows['sample_compositions'].append(dict(id=composition,sample_id=sid,formula_raw=s['formula_raw'],composition_basis=s['composition_basis'],
            composition_schema_version='materials-composition/1',composition_payload=dict(variables=s['variables'],isotopes=s['isotopes']),
            source_artifact_id=projection_id,record_sha256='0'*64))
        rows['material_states'].append(dict(id=state,material_id=material,sample_id=sid,resolution='source_scoped',
            condition_schema_version='materials-conditions/2',pressure_status='not_reported',temperature_role='unknown',context_sha256='0'*64,
            conditions=dict(items=st['conditions'],pressure=st['pressure'],temperature_condition_id=None),source_artifact_id=projection_id))
        method_class,method_raw,method_evidence,canonical_omissions=canonical_method(packet,p,r['id'],audit)
        extra_evidence.extend(method_evidence)
        rows['research_protocols'].append(dict(id=protocol,work_id=bindings['work']['id'],method_class=method_class,method_raw=method_raw,
            observable=p['observable'],details_raw=p['details_raw'],parameters=p['parameters'],protocol_schema_version='materials-protocol/1',
            source_artifact_id=projection_id,record_sha256='0'*64))
        event=target('event',r['id']);claim=target('claim',r['id'])
        context=dict(materials_context=dict(version='materials-context/1',composition_ids=[composition],protocol_id=protocol,relation_ids=[]),
            native_origin={**origin,'source_result_id':r['id'],'physical_event_identity':'unresolved','independent_measurement_count':None,
                'state_label':st['label'],'preparation_raw':st['preparation_raw'],'limitations':graph['limitations']})
        rows['research_events'].append(dict(id=event,material_id=material,state_id=state,event_type='measurement',knowledge_origin='Observed',
            record_sha256=digest(context),review_status='pending',validity_status='pending',decision_artifact_id=None,context=context))
        normalized=normalize('tc',parsed.results[0].quantity)['normalized']
        qualifiers=[q for q in r['qualifiers'] if q['kind']=='transition_stage']
        require(len(qualifiers)==len(r['qualifiers']), 'unsupported_native_qualifier')
        raw={k:v for k,v in r.items() if k!='evidence'}
        checked=verdicts.get((item['work_id'],item['result_id'],item['run_id'],projection['projection_sha256']))=='correct'
        admission=dict(policy=POLICY,quality_status='model_source_checked' if checked else 'batch_sampled',batch_qualified=report['qualified'],per_record_checked=checked,reviewer_kind='model',
            independent_expert_review=False,selection_sha256=report['selection_sha256'],audit_sha256=report['audit_sha256'],
            source_scope='selected_source_assertion',complete_paper=False)
        if admission_route==RECORD_ROUTE:
            require(checked,'individual_admission_requires_correct_verdict')
            admission['admission_route']=RECORD_ROUTE
        definition=deepcopy(r['definition'])
        if definition['criterion'] not in {'unspecified','not_applicable'} and definition['criterion_raw'] is None:
            # The canonical contract requires raw wording for a known criterion.
            # A catalog window may have missed that wording. Rebind only the
            # original model string found verbatim in audited original context.
            source_result=next(x for x in json.loads(packet['raw_output'])['results'] if x['id']==r['id'])
            literal=source_result['definition']['criterion_raw']
            reviewed=next(x for x in audit['records'] if x['run_id']==packet['run_id'] and x['result_id']==r['id'])
            witness=next((e for e in reviewed['source_evidence'] if literal and literal in e['quote']),None)
            require(witness is not None,'known_criterion_literal_requires_source_binding')
            start=witness['start_char']+witness['quote'].index(literal)
            block=next(b for b in packet['bundle']['blocks'] if b['id']==witness['block_id'])
            require(block['text'][start:start+len(literal)]==literal,'criterion_rebinding_mismatch')
            definition['criterion_raw']=literal
            extra_evidence.append(dict(path='/results/0/definition/criterion_raw',block_id=block['id'],
                document_id=block['document_id'],block_sha256=block['sha256'],locator=block['locator'],
                start_char=start,end_char=start+len(literal),quote_sha256=hashlib.sha256(literal.encode()).hexdigest()))
        native_origin={**origin,'omitted_fields':[*item['omitted_fields'],*canonical_omissions],'limitations':graph['limitations']}
        if canonical_omissions:native_origin['canonical_optional_omission_policy']='production90-method-omission/1'
        if packet.get('schema')=='materials-core-tc-packet/1':
            native_origin.update(structural_normalizations=item.get('structural_normalizations',[]),
                sample_context_authorship='model_extracted_description_checked_against_original_source')
            for key in ('evidence_binding_notes','quantity_evidence_bindings'):
                if item.get(key):native_origin[key]=item[key]
        if extra_evidence:native_origin['canonical_literal_rebindings']=extra_evidence
        meta=dict(materials_outcome=dict(version='materials-claim-outcome/1',kind='tc',quantity=r['quantity']),
            result_semantics=dict(version='materials-result-semantics/1',definition=definition,qualifiers=qualifiers),
            state_semantics=dict(version='materials-state-link/1'),production_admission=admission,
            native_origin=native_origin)
        rows['material_claims'].append(dict(id=claim,event_id=event,result_key=r['id'],interpretation_revision=1,material_id=material,
            paper_id=bindings['paper']['id'],work_id=bindings['work']['id'],source_snapshot_id=bindings['snapshot']['id'],
            property_type='tc',result_status='observed',evidence_role='primary_experimental',value_relation=normalized['relation'],
            value_kelvin=normalized.get('value'),value_lower_kelvin=normalized.get('lower'),value_upper_kelvin=normalized.get('upper'),
            tc_definition=r['definition']['criterion'],measurement_method=None if method_class=='unspecified' else method_class,
            validity_status='pending',magnetic_field_t=None,minimum_temperature_k=None,source_kind='prose',
            source_locator=dict(run_id=packet['run_id'],projection_sha256=projection['projection_sha256'],source_result_id=r['id']),
            raw_record=raw,extraction_metadata=meta,source_record_hash=digest(raw),extractor_version=VERSION))
        links={};seen=set()
        for e in [*item['validation']['resolved_evidence'],*extra_evidence]:
            revision,capture,artifact,doc=source_ids[e['document_id']]
            coordinate=dict(section_path='parsed-block:'+pre['bundle']['sha256']+'#'+e['block_id'],char_start=e['start_char'],char_end=e['end_char'])
            page=re.search(r'pdf_page:(\d+)',e['locator'])
            if page:coordinate['page']=int(page.group(1))
            locator={**coordinate,'block_sha256':e['block_sha256'],'quote_sha256':e['quote_sha256'],
                'original_locator':e['locator'],'representation_input':pre['bundle'],'parser':doc['parser'],
                'projection_sha256':projection['projection_sha256']}
            lid=target('evidence',[r['id'],artifact,digest(locator)])
            links.setdefault(lid,dict(id=lid,event_id=event,artifact_id=artifact,link_type='source',locator={**locator,'field_paths':[]}))
            links[lid]['locator']['field_paths'].append(e['path'])
            if e['path'].startswith('/results/0/') and (capture,digest(coordinate)) not in seen:
                seen.add((capture,digest(coordinate)))
                registry['claim_source_occurrences'].append(dict(id=target('occurrence',[r['id'],capture,digest(coordinate)]),
                    claim_id=claim,work_id=bindings['work']['id'],source_revision_id=revision,capture_id=capture,
                    occurrence_key=digest(coordinate),locator=coordinate,binding_status='pending',review_artifact_id=None,review_artifact_sha256=None))
        require(seen,'result_occurrence_required')
        for link in links.values():
            link['locator']['field_paths']=sorted(set(link['locator']['field_paths']))
            rows['event_evidence'].append(link)
        results.append(dict(source_result_id=r['id'],claim_id=claim,event_id=event,quality_status=admission['quality_status']))
    for group in [rows,registry]:
        for name,values in group.items():
            if not isinstance(values,list):continue
            unique={}
            for row in values:
                require(row['id'] not in unique or unique[row['id']]==row,'planned_native_identity_conflict')
                unique[row['id']]=row
            group[name]=list(unique.values())
    return dict(version=VERSION,run_id=packet['run_id'],packet_hash=packet['packet_hash'],source_work_id=packet['work_id'],
        bindings=bindings,rows=rows,source_registry=registry,results=results,production_admission=report)


async def apply(db, entry, *, bindings, captured_at, selection, audit, dry_run=True, excluded_result_ids=(),admission_route=BATCH_ROUTE,validation=None):
    plan=prepare(entry,bindings=bindings,captured_at=captured_at,selection=selection,audit=audit,
        excluded_result_ids=excluded_result_ids,admission_route=admission_route,validation=validation)
    packet=read_pin(entry['packet'])
    transaction=await db.begin_nested()
    try:
        await db.execute(sa.text('SELECT pg_advisory_xact_lock(1002401)'))
        await _catalogue(db,plan)
        if packet.get('schema')!='materials-core-tc-packet/1':
            await apply_packet(db,packet)
        counts=Counter();readback={}
        for name in TABLES:
            readback[name]=[]
            for row in plan['rows'][name]:
                inserted,actual=await _put(db,name,row)
                counts['inserted' if inserted else 'verified_existing']+=1
                readback[name].append(actual)
        registry=await import_source_provenance_bundle(db,plan['source_registry'],dry_run=False)
        result=dict(version=VERSION,plan_sha256=digest(plan),dry_run=dry_run,committed=False,**counts,
            registry=registry,results=plan['results'],readback=readback,scientific_expert_review=False)
        if dry_run:await transaction.rollback()
        else:await transaction.commit()
        return result
    except BaseException:
        if transaction.is_active:await transaction.rollback()
        raise
