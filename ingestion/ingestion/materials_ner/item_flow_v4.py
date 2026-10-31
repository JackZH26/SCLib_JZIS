"""Replay the separately frozen catalog/owner selection stages, including failures."""
from pydantic import ValidationError
from . import frozen_owner_stages as adapter, item_stages as items


def replay(transcript,bundle,inventory,config):
    from .item_worker import diagnostic
    from .item_flow_v2 import interfaces
    adapter, _, _, _ = interfaces(config)
    if (config.get('workflow')!=adapter.WORKFLOW or config.get('field_generation_policy')!=adapter.POLICY
            or transcript.get('schema')!=adapter.OUTPUT_FORMAT or transcript.get('work_id')!=bundle.work_id
            or transcript.get('parent_run_id')!=config['parent_run_id']):
        raise ValueError('staged_transcript_binding_mismatch')
    entries=transcript['entries'];declarations=declared=catalog=links=proof=audit=None
    owned=relations=selection=owner_plan=owner_projection=None
    decisions={};plans=[];errors=[];outcomes=[]
    context_selection=context_projection=None
    for index,entry in enumerate(entries):
        expected=('declarations' if index==0 else 'catalog-relations' if index==1 else 'item-owners' if index==2
            else f'items-{index-2}' if index<=len(plans)+2 else 'contexts')
        if entry['name']!=expected or index>len(plans)+3:
            raise ValueError('staged_transcript_order_invalid')
        if entry['raw_output'] is None:
            if index!=len(entries)-1:raise ValueError('staged_calls_after_provider_failure')
            errors.append(dict(stage=entry['name'],code='staged_provider_stage_incomplete'));break
        try:
            if index==0:
                declarations=items.parse_response(adapter.Declarations,entry['raw_output'])
                declared=adapter.check_declarations(declarations,inventory,bundle,config['max_source_items'],
                    strict_field_owner=config.get('catalog_evidence_mode','strict')=='strict')
            elif index==1:
                relations=items.parse_response(adapter.Relations,entry['raw_output'])
                candidate,candidate_proof=adapter.project(declarations,relations,bundle)
                all_items=items.check_catalog(candidate,inventory,bundle,config['max_source_items'])
                candidate_audit=adapter.audit_catalog(candidate,inventory,bundle)
                catalog,proof,audit=candidate,candidate_proof,candidate_audit
                requested = adapter.requested_items(all_items) if hasattr(adapter, 'requested_items') else all_items
                plans=items.groups(requested,config['group_size'])
            elif index==2:
                candidate=items.parse_response(adapter.OwnerBindings,entry['raw_output'])
                derived_owned,derived_plan,derived_projection=adapter.bind(candidate,declarations,relations,inventory,bundle)
                selection,owned,owner_plan,owner_projection=candidate,derived_owned,derived_plan,derived_projection
            elif index<=len(plans)+2:
                group=items.parse_response(items.ItemGroup,entry['raw_output'])
                items.check_group(group,plans[index-3],catalog,bundle.work_id)
                adapter.Ownership.check_group(group,owner_plan)
                if hasattr(adapter, 'check_group'):
                    adapter.check_group(group,catalog,inventory,bundle,owner_plan)
                decisions.update(group.decisions)
                outcomes.append(dict(stage=entry['name'],item_ids=plans[index-3],valid_decision_objects=True))
            else:
                graph=(adapter.context_graph(catalog,decisions,bundle) if hasattr(adapter,'context_graph')
                    else items.graph_objects(catalog,decisions))
                if hasattr(adapter,'ContextSelections'):
                    selected=items.parse_response(adapter.ContextSelections,entry['raw_output'])
                    candidate,selected_proof=adapter.project_contexts(selected,bundle,inventory,graph)
                    context_selection,context_projection=selected,selected_proof
                else:
                    candidate=items.parse_response(items.ContextLinks,entry['raw_output'])
                items.check_links(candidate,inventory,graph)
                if hasattr(adapter, 'check_links'):
                    adapter.check_links(candidate,inventory,graph,bundle)
                links=candidate
        except (ValidationError,ValueError,KeyError) as error:
            errors.append(dict(stage=entry['name'],**diagnostic(error)))
            if index<=2:
                if index==0:declared=None
                if len(entries)!=index+1:raise ValueError('staged_calls_after_invalid_catalog')
                break
            if index<=len(plans)+2:
                outcomes.append(dict(stage=entry['name'],item_ids=plans[index-3],valid_decision_objects=False))
    result=dict(declarations=declarations,declared_catalog=declared,catalog=catalog,plans=plans,
        decisions=decisions,links=links,errors=errors,group_outcomes=outcomes,
        catalog_projection=proof,catalog_diagnostic=audit,item_owner_plan=owner_plan,
        owner_declarations=owned,catalog_relations=relations,owner_bindings=selection,
        owner_selection_projection=owner_projection)

    if hasattr(adapter,'ContextSelections'):
        result.update(context_selection=context_selection,context_projection=context_projection)
    return result
