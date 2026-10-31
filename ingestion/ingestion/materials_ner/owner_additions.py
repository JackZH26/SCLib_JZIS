"""Bounded typed owner additions for an explicitly rebound existing result."""
from typing import get_args
from .contract import digest

POLICY='source_bound_owner_addition_v1'
GROUPS={'/samples':('samples','sample_id','sample'),'/states':('states','state_id','state'),
        '/protocols':('protocols','protocol_id','protocol')}


def spec(graph,parent_run_id,target):
    if target.path not in GROUPS:raise ValueError('staged_owner_addition_scope_invalid')
    group,reference,kind=GROUPS[target.path]
    identifier='revision:'+kind+':'+digest(dict(parent_run_id=parent_run_id,target_id=target.id))[:20]
    if any(x.id==identifier for name in ('samples','states','protocols') for x in getattr(graph,name)):
        raise ValueError('staged_owner_addition_identity_exists')
    return dict(policy=POLICY,group=group,reference_field=reference,assigned_id=identifier,
        prior_collection_sha256=digest([x.model_dump() for x in getattr(graph,group)]),
        source_span_ids=target.source_span_ids,scientific_acceptance=False)


def model(graph,target):
    if target.path not in GROUPS:raise ValueError('staged_owner_addition_scope_invalid')
    return get_args(type(graph).model_fields[GROUPS[target.path][0]].annotation)[0]


def available_ids(graph,parent_run_id,targets):
    ids={name:[x.id for x in getattr(graph,name)] for name in ('samples','states','protocols')}
    for t in targets:
        if t.operation=='append_owner':
            s=spec(graph,parent_run_id,t);ids[s['group']].append(s['assigned_id'])
    return ids


def schema(graph,parent_run_id,target,targets,span_ids):
    value=model(graph,target).model_json_schema();s=spec(graph,parent_run_id,target)
    value['properties']['id']['enum']=[s['assigned_id']]
    ids=available_ids(graph,parent_run_id,targets)
    if 'sample_id' in value['properties']:value['properties']['sample_id']['enum']=ids['samples']
    for definition in value.get('$defs',{}).values():
        props=definition.get('properties',{})
        if 'span_ids' in props:props['span_ids']['items']['enum']=span_ids
        if 'state_id' in props:props['state_id']['enum']=ids['states']
    return value


def apply(data,graph,parent_run_id,target,value):
    s=spec(graph,parent_run_id,target);owner=model(graph,target).model_validate(value,strict=True).model_dump()
    if owner['id']!=s['assigned_id']:raise ValueError('staged_owner_addition_identity_mismatch')
    if any(x['id']==owner['id'] for x in data[s['group']]):raise ValueError('staged_owner_addition_identity_exists')
    data[s['group']].append(owner)
    return owner,s


def audit_usage(data,additions):
    if not additions:return None
    rows=[]
    for s in additions:
        observations=[o['id'] for o in data['observations'] if o[s['reference_field']]==s['assigned_id']]
        if not observations:raise ValueError('staged_owner_addition_has_no_result_binding')
        rows.append(dict(s,referenced_by_observations=observations))
    return dict(policy=POLICY,additions=rows,existing_owners_retained=True,
        scientific_acceptance=False,independent_review=False)
