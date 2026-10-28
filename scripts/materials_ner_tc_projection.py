"""Result-level production projection, retaining the complete immutable attempt.

A bad secondary result cannot remove a structurally usable primary Tc. This
adapter only selects existing entities and records optional-field omissions;
it never changes a material, quantity, pressure, origin or controlled criterion.
"""
from copy import deepcopy
import json
import re

from ingestion.materials_ner import projection_binding, scoped_evidence, reviewed_proposals
from ingestion.materials_ner.contract import parse_extraction, digest
from ingestion.materials_ner.proposals import verify_packet
from ingestion.materials_ner.sources import Bundle

VERSION='production90-tc-projection/2'
INFORMATIONAL={'incomplete_extraction','coverage_inventory_mismatch'}
OPTIONAL_FIELDS={'/quantity_name_raw','/interpretation_raw','/definition/criterion_raw'}


def subset(model, result):
    graph=deepcopy(model)
    graph['results']=[deepcopy(result)]
    for group,key in [('samples','sample_id'),('states','state_id'),('protocols','protocol_id')]:
        graph[group]=[deepcopy(x) for x in model[group] if x['id']==result[key]]
        if len(graph[group])!=1:raise ValueError('result_parent_missing_or_ambiguous')
    if result['dependencies']:raise ValueError('dependent_result_outside_initial_scope')
    sample_id=result['sample_id'];state_id=result['state_id']
    if any(x['from_sample_id']==sample_id or x['to_sample_id']==sample_id for x in model['sample_relations']):
        raise ValueError('sample_relation_requires_separate_projection')
    if graph['protocols'][0]['context_uses']:
        raise ValueError('protocol_context_requires_separate_projection')
    if any(x['state_id']==state_id or x['result_id']==result['id'] for x in model['condition_supports']):
        raise ValueError('condition_support_requires_separate_projection')
    graph['sample_relations']=[];graph['condition_supports']=[]
    parse_extraction(projection_binding.native_graph(graph))
    return graph


def project(packet):
    verify_packet(packet)
    provenance=packet['receipt']['projector_provenance']
    bundle=Bundle.model_validate(packet['bundle'])
    model=json.loads(packet['raw_output'])
    scope=json.loads(provenance['scope_json']);coverage=json.loads(provenance['coverage_json'])
    config=provenance['config']
    request=json.loads(provenance.get('projector_request_json',provenance['request_json']))
    catalog=(scoped_evidence.build(bundle,scope,version=request.get('source_catalog_version',scoped_evidence.VERSION))
        if config.get('evidence_transport')=='source_catalog' else None)
    records=[]
    for result in model['results']:
        item=dict(work_id=packet['work_id'],run_id=packet['run_id'],packet_hash=packet['packet_hash'],
            result_id=result['id'],status='held',holds=[],omitted_fields=[],source_result_sha256=digest(result))
        if result['quantity_kind']!='tc' or result['quantity']['status']!='reported':
            item['holds']=['outside_explicit_reported_tc_scope']
        elif result['origin']!='observed' or result['source_role']!='primary':
            item['holds']=['outside_initial_primary_experimental_scope']
        else:
            try:
                selected=subset(model,result)
                binding=(projection_binding.compile_catalog_bindings(selected,bundle,scope,coverage,catalog)
                    if catalog is not None else projection_binding.compile_bindings(selected,bundle,scope,coverage))
                graph=parse_extraction(binding['graph']).model_dump()
                # A written chemical formula does not establish a nominal
                # composition. Keep the original basis in the omission log.
                sample=graph['samples'][0]
                basis_quotes=' '.join(e['quote'] for e in sample['evidence'] if e['field']=='/composition_basis')
                if sample['composition_basis']=='nominal' and not re.search(r'\bnominal(?:ly)?\b',basis_quotes,re.I):
                    item['omitted_fields'].append(dict(path='/samples/0/composition_basis',before='nominal',after='unresolved',reason='nominal_basis_not_explicit_in_bound_source'))
                    sample['composition_basis']='unresolved'
                    sample['evidence']=[e for e in sample['evidence'] if e['field']!='/composition_basis']
                _,validation=reviewed_proposals.validate_graph(graph,bundle,scope,coverage,
                    allowed_contracts=(graph['schema_version'],),consistency_version=config.get('consistency_version'))
                # Drop only unsupported optional prose, retaining controlled
                # criterion, quantities, origins and all interpretive conditions.
                to_drop={i['path'][len('/results/0'):] for i in validation['issues']
                    if i['path'].startswith('/results/0/') and i['path'][len('/results/0'):] in OPTIONAL_FIELDS}
                for pointer in sorted(to_drop):
                    owner=graph['results'][0];parts=pointer.strip('/').split('/')
                    for key in parts[:-1]:owner=owner[key]
                    before=owner[parts[-1]]
                    if before is not None:
                        owner[parts[-1]]=None
                        item['omitted_fields'].append(dict(path='/results/0'+pointer,before=before,after=None,reason='unsupported_optional_literal'))
                        graph['results'][0]['evidence']=[e for e in graph['results'][0]['evidence'] if e['field']!=pointer]
                if any(i['path']=='/protocols/0/details_raw' and i['code']=='source_literal_evidence_missing' for i in validation['issues']):
                    protocol=graph['protocols'][0]
                    item['omitted_fields'].append(dict(path='/protocols/0/details_raw',before=protocol['details_raw'],after=None,reason='unsupported_optional_literal'))
                    protocol['details_raw']=None
                    protocol['evidence']=[e for e in protocol['evidence'] if e['field']!='/details_raw']
                if item['omitted_fields']:
                    _,validation=reviewed_proposals.validate_graph(graph,bundle,scope,coverage,
                        allowed_contracts=(graph['schema_version'],),consistency_version=config.get('consistency_version'))
                issues=[i for i in validation['issues'] if not(i['path']=='/' and i['code'] in INFORMATIONAL)]
                item.update(graph=graph,validation=validation,binding=binding,
                    selected_model_sha256=digest(selected),holds=sorted({i['code'] for i in issues}),
                    status='held' if issues else 'eligible_for_source_audit')
            except ValueError as exc:
                item['holds']=[str(exc)]
        records.append(item)
    body=dict(schema=VERSION,work_id=packet['work_id'],run_id=packet['run_id'],packet_hash=packet['packet_hash'],
        raw_results=len(model['results']),records=records,
        original_attempt_modified=False,source_text_modified=False,scientific_values_modified=False,
        policy='production90/1',primary_scope_only=True)
    return {**body,'projection_sha256':digest(body)}
