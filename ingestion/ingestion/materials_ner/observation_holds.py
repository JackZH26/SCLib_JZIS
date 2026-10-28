"""Explicit false-positive/owner holds; original model results remain in ancestry."""
from copy import deepcopy
import re
from pydantic import Field
from .contract import StrictModel,digest
from .wire_v2 import UnextractedItem
from .evidence import source_catalog,selected_quotes,equivalent_location_spans

POLICY='source_bound_observation_hold_v1'


class HoldDecision(StrictModel):
    reason: UnextractedItem.model_fields['reason'].annotation
    explanation: str = Field(min_length=1,max_length=3000)


def target(graph,inventory,bundle,path,span_ids):
    match=re.fullmatch(r'/observations/(0|[1-9][0-9]*)',path)
    if not match:raise ValueError('staged_observation_hold_scope_invalid')
    observation=graph.model_dump()['observations'][int(match[1])]
    identifiers=observation['inventory_item_ids']
    if not identifiers or len(set(identifiers))!=len(identifiers):
        raise ValueError('staged_observation_hold_inventory_invalid')
    others=[o for o in graph.observations if o.id!=observation['id']]
    if any(set(identifiers)&set(o.inventory_item_ids) for o in others):
        raise ValueError('staged_observation_hold_item_still_emitted')
    if set(identifiers)&{i.item_id for i in graph.unextracted_items}:
        raise ValueError('staged_observation_hold_already_held')
    items={i.id:i for i in [*inventory.items,*graph.additional_items]}
    catalog=source_catalog(bundle);selected_quotes(catalog,span_ids)
    witness=equivalent_location_spans(catalog,span_ids)
    for identifier in identifiers:
        if identifier not in items or not witness & equivalent_location_spans(catalog,items[identifier].source_span_ids):
            raise ValueError('staged_observation_hold_source_disconnected')
    return dict(policy=POLICY,observation_id=observation['id'],inventory_item_ids=identifiers,
        observation_sha256=digest(observation),source_span_ids=span_ids,
        original_source_items=[items[i].model_dump() for i in identifiers],
        scientific_exclusion_approved=False,independent_review=False)


def apply(data,holds):
    """Reject dangling relations; never silently delete evidence or dependencies."""
    if not holds:return None
    ids={h['observation_id'] for h in holds}
    if len(ids)!=len(holds):raise ValueError('staged_observation_hold_duplicate')
    for observation in data['observations']:
        if observation['id'] not in ids and any(d['result_id'] in ids for d in observation['result']['dependencies']):
            raise ValueError('staged_observation_hold_has_live_dependency')
    if any(s['result_id'] in ids for s in data['condition_supports']):
        raise ValueError('staged_observation_hold_has_live_support')
    if any(b['entity'] in {'result','definition'} and b['entity_id'] in ids
           for c in data['context_dispositions'] for b in c['bindings']):
        raise ValueError('staged_observation_hold_has_live_context_binding')
    before_completion=deepcopy(data['completion'])
    data['observations']=[o for o in data['observations'] if o['id'] not in ids]
    entries=[entry for h in holds for entry in h['unextracted_items']]
    known={i['item_id'] for i in data['unextracted_items']}
    if any(e['item_id'] in known for e in entries) or len({e['item_id'] for e in entries})!=len(entries):
        raise ValueError('staged_observation_hold_duplicate_inventory_disposition')
    data['unextracted_items']+=deepcopy(entries)
    data['completion']={'outcome':'incomplete','empty_reason':None}
    return dict(policy=POLICY,retired_observation_ids=sorted(ids),added_unextracted_items=entries,
        previous_completion=before_completion,current_completion=deepcopy(data['completion']),
        original_observations_retained_in_parent_and_change_audit=True,source_facts_deleted=False,
        scientific_exclusion_approved=False,independent_review=False,scientific_acceptance=False)
