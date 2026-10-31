"""Typed audit questions over the existing /13 graph, not scientific DB fields.

Every entity property has an explicit policy disposition. Null/default categories
are reviewed for omissions, while evidence/IDs remain operational metadata.
"""
from copy import deepcopy
from .contract import canonical, digest, parse_extraction
from . import projection_binding as binding

VERSION = 'materials-semantic-claims/1'
FACETS = {
 'raw_literal': 'Check only fidelity of the proposed source expression at its own source occurrence, allowing layout whitespace. A literal does not assert exactness, origin or provenance. If absent/null but explicitly reported, mark needs_completion. Do not reject a literal solely because a separate approximation flag is wrong.',
 'sample_identity': 'Check the proposed sample identity, label and resolution against the source, including missing formula handling. Same nominal formula or phase does not establish specimen identity.',
 'composition': 'Check the composition basis, alternate formula assertion, substitution site, isotope or variable and its source ownership. Nominal, measured, refined and calculation input remain distinct. Missing entries can need completion.',
 'sample_kind': 'Check the source-supported sample form, substrate and bulk/film/interface/device/component classification. Do not infer these merely from conventional material behavior.',
 'owner': 'Check that the proposed sample/state/protocol or condition reference belongs to this particular assertion. A valid foreign key is not scientific ownership.',
 'condition': 'Check the entire condition including kind, numerical shape, role, orientation, source basis and scan/fit-window direction. Measurement, synthesis, simulation, study extent and fit window are distinct.',
 'pressure_regime': 'Check the pressure declaration or its regime independently against the original condition: explicit_ambient requires explicit source support; missing pressure is unknown. Do not equate preparation pressure with measurement pressure.',
 'method': 'Check the proposed measurement/calculation/fitting method, observable and parameters. A shared method applies only where source ownership is supported.',
 'applicability': 'Check general applicability of a procedure to the stated condition. context_uses does not assert that the procedure measured or calibrated the condition.',
 'kind': 'Check which physical quantity the result denotes; measurement temperature and model temperature scales are not automatically Tc. Keep an unmapped source quantity rather than coercing it.',
 'origin': 'Check observed (directly measured), computed (calculation), model_derived (fit/extrapolation/derivation), or unknown. This axis is independent of primary/cited provenance. A primary result may be fitted or computed.',
 'source_role': 'Check primary (reported by this work), cited (reused from another work), or unknown. Do not base this decision on whether a number is directly measured, fitted or calculated. Origin uncertainty alone does not make primary provenance unknown.',
 'criterion': 'Check the result-specific definition and parameters. Include unspecified/not_applicable: if the original supplies a missing criterion use needs_completion, not supported merely because the candidate is unspecified. Keep 90-percent resistance, onset and zero resistance distinct.',
 'value_shape': 'Check status, scalar versus range/bound, signed value/endpoints and source ownership. exact is a scalar relation code; approximation is a separate flag. Do not average a range or replace omitted values with zero.',
 'unit': 'Check the source unit and convention, including header context. H, B and mu0H are not interchangeable merely because a source uses tesla.',
 'qualification': 'Check approximation and uncertainty independently of literal fidelity and provenance. Resolve qualifier scope and preserve discrepancies between table and body; never silently correct reported values.',
 'availability': 'Check whether a missing/ambiguous/conflicted/unavailable assignment adequately represents the supplied original. If the source explicitly provides the missing fact, use needs_completion with a witness. Unknown is not proof of source absence.',
 'derived_parent': 'Check each actual dependency relation and the exact parent result with sample/state/criterion ownership. Also check empty dependency inventories for explicitly stated omitted inputs. Do not impose a universal same-state rule: some derivations legitimately combine states.',
 'qualifier': 'Check transition stage, conditional existence, temperature role or target-specific non-detection, including window and sensitivity. No observed signal is not a universal zero or proof of absence. Inspect omitted qualifiers too.',
 'sample_relation': 'Check source-supported component containment and the identities of both endpoints. A common formula does not prove containment.',
 'condition_measurement': 'Check the explicit measures relation from a result to a condition, including ownership. General procedure applicability alone is insufficient.',
 'interpretation': 'Check the source-supported interpretation or component assignment without importing outside knowledge.',
 'source_completeness': 'Assess whether the supplied source establishes the proposed completeness claim. Missing external supplements or unread source cannot be filled by inference. This diagnostic does not provide an independent whole-paper result census.',
}
# Every top-level native entity field (except local ID and witnesses) is listed.
GROUP_FIELDS = {
 'samples': {'sample_identity':['label','identity_resolution','formula_unavailability'],
   'composition':['composition_basis','isotopes','variables','additional_formula_assertions'],
   'sample_kind':['target_kind','form_raw','substrate_raw'], 'raw_literal':['formula_raw']},
 'states': {'owner':['sample_id'], 'sample_identity':['label'], 'condition':['conditions'],
   'raw_literal':['preparation_raw'], 'pressure_regime':['pressure']},
 'protocols': {'method':['method','method_class','observable','details_raw','parameters'], 'applicability':['context_uses']},
 'results': {'owner':['sample_id','state_id','protocol_id'], 'kind':['quantity_kind','quantity_name_raw'],
   'value_shape':['quantity'], 'origin':['origin'], 'source_role':['source_role','cited_source_raw'],
   'criterion':['definition'], 'derived_parent':['dependencies'], 'qualifier':['qualifiers'],
   'interpretation':['component_raw','interpretation_raw']},
 'sample_relations': {'sample_relation':['from_sample_id','to_sample_id','relation','relation_raw']},
 'condition_supports': {'condition_measurement':['result_id','state_id','condition_id','relation','relation_raw']},
}


def get(body, pointer):
    for key in pointer.lstrip('/').split('/'):
        body = body[int(key)] if isinstance(body,list) else body[key.replace('~1','/').replace('~0','~')]
    return body


def replace(body,pointer,value):
    parts=pointer.lstrip('/').split('/');parent=body
    for key in parts[:-1]:parent=parent[int(key)] if isinstance(parent,list) else parent[key.replace('~1','/').replace('~0','~')]
    key=parts[-1];parent[int(key) if isinstance(parent,list) else key.replace('~1','/').replace('~0','~')]=deepcopy(value)


def leaves(value,path):
    if isinstance(value,dict) and value:
        for key,item in value.items():yield from leaves(item,path+'/'+key.replace('~','~0').replace('/','~1'))
    elif isinstance(value,list) and value:
        for n,item in enumerate(value):yield from leaves(item,path+'/'+str(n))
    else:yield path


def generate(graph):
    parse_extraction(graph)
    if graph['schema_version']!='materials-ner/13':raise ValueError('semantic_native_13_required')
    targets=[];all_paths=[];absent=[]
    def add(group,index,entity,facet,paths,candidate=None,requires_target=False):
        prefix=f'/{group}/{index}';paths=[prefix+path for path in paths]
        if candidate is None:candidate={path:get(graph,path) for path in paths}
        targets.append(dict(id=f'S{len(targets)+1:04}',entity_group=group,entity_id=entity['id'],
            facet=facet,paths=paths,candidate_value=candidate,requires_target=requires_target))
    def extras(group,index,entity,item,path):
        if isinstance(item,dict):
            # Quantity shape and qualification are distinct questions, even
            # inside sparse non-detection/parameter/composition structures.
            if {'status','raw','relation','value','lower','upper','unit','approximate','uncertainty'} <= set(item):
                if item['status']!='reported':
                    add(group,index,entity,'availability',[path])
                    return
                add(group,index,entity,'availability',[path+'/status'])
                add(group,index,entity,'value_shape',[path+'/'+k for k in ['relation','value','lower','upper']],
                    requires_target=group=='results' and path=='/quantity' and item['status']=='reported')
                add(group,index,entity,'unit',[path+'/unit'])
                add(group,index,entity,'qualification',[path+'/approximate',path+'/uncertainty'])
            for key,value in item.items():
                next_path=path+'/'+key
                if (key=='raw' or key.endswith('_raw')) and value is not None:
                    add(group,index,entity,'raw_literal',[next_path],
                        requires_target=group=='results' and next_path=='/quantity/raw' and value is not None)
                extras(group,index,entity,value,next_path)
        elif isinstance(item,list):
            for n,value in enumerate(item):extras(group,index,entity,value,path+'/'+str(n))
    for group in binding.GROUPS:
        mapping=GROUP_FIELDS[group];declared={x for fields in mapping.values() for x in fields}
        for index,entity in enumerate(graph[group]):
            actual=set(entity)-{'id','evidence'}
            if declared!=actual:raise ValueError('semantic_entity_fields_unclassified:'+group)
            for key in sorted(actual):all_paths.extend(leaves(entity[key],f'/{group}/{index}/{key}'))
            for facet,fields in mapping.items():
                for field in fields:
                    item=entity[field]
                    # Null optional descriptions are missing features, not
                    # positive absence claims. Their omissions remain visible
                    # in the ledger and source-inventory work. Core criterion,
                    # pressure, quantity and dependency checks are never skipped.
                    if item is None and field!='formula_raw':
                        absent.append(dict(path=f'/{group}/{index}/{field}',
                            reason='Optional null field: no asserted scientific fact; source-result completeness is a separate obligation.'))
                        continue
                    # Quantities are split below; a parent quantity verdict
                    # would recombine literal fidelity and approximation.
                    if group=='results' and field=='quantity':continue
                    if isinstance(item,list) and item:
                        for n,_ in enumerate(item):add(group,index,entity,facet,[f'/{field}/{n}'])
                    else:add(group,index,entity,facet,['/'+field])
            for key in sorted(actual):
                if key.endswith('_raw') and entity[key] is not None:
                    add(group,index,entity,'raw_literal',['/'+key])
                extras(group,index,entity,entity[key],'/'+key)
    # Suppress duplicate questions for top-level raw fields already listed.
    unique=[];seen=set()
    for target in targets:
        key=(target['facet'],tuple(target['paths']))
        if key not in seen:seen.add(key);target['id']=f'S{len(unique)+1:04}';unique.append(target)
    covered={leaf for leaf in all_paths if any(leaf==path or leaf.startswith(path+'/') for t in unique for path in t['paths'])}
    unasserted={entry['path'] for entry in absent}
    if set(all_paths)-covered-unasserted:raise ValueError('semantic_claim_coverage_gap')
    return dict(policy_version=VERSION,targets=unique,entity_leaf_paths=sorted(set(all_paths)),
        covered_entity_leaf_paths=sorted(covered),sparse_optional_absences=absent,uncovered_entity_leaf_paths=[],
        graph_sha256=digest(graph),scientific_payload_sha256=digest(binding.scientific_payload(graph)),
        metadata_exclusions=['Top-level extraction bookkeeping','Local entity IDs','Existing evidence addresses'],
        scope='All populated native entity claims and core missing/default assignments. Optional null descriptors have an explicit non-assertion disposition. This is not an independent source-result census.',
        independent_scientific_claim_census=False,scientific_acceptance=False)


def render():
    return canonical(dict(version=VERSION,facets=FACETS))
