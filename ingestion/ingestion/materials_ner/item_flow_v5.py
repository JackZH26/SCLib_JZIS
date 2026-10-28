"""Replay source selections and one append-only completion before frozen owners."""
from pydantic import ValidationError
from . import selected_catalog_stages as adapter, item_stages as items


def replay(transcript,bundle,inventory,config):
    from .item_worker import diagnostic
    if (config.get('workflow')!=adapter.WORKFLOW or config.get('field_generation_policy')!=adapter.POLICY
            or transcript.get('schema')!=adapter.OUTPUT_FORMAT or transcript.get('work_id')!=bundle.work_id
            or transcript.get('parent_run_id')!=config['parent_run_id']):
        raise ValueError('staged_transcript_binding_mismatch')
    entries=transcript['entries'];declarations=declared=catalog=links=proof=audit=None
    initial=selection_proof=completion=completion_proof=None
    owned=relations=selection=owner_plan=owner_projection=None
    decisions={};plans=[];errors=[];outcomes=[]
    for index,entry in enumerate(entries):
        expected=('declarations' if index==0 else 'catalog-completion' if index==1
            else 'catalog-relations' if index==2 else 'item-owners' if index==3
            else f'items-{index-3}' if index<=len(plans)+3 else 'contexts')
        if entry['name']!=expected or index>len(plans)+4:
            raise ValueError('staged_transcript_order_invalid')
        if entry['raw_output'] is None:
            if index!=len(entries)-1:raise ValueError('staged_calls_after_provider_failure')
            errors.append(dict(stage=entry['name'],code='staged_provider_stage_incomplete'));break
        try:
            if index==0:
                initial=items.parse_response(adapter.Declarations,entry['raw_output'])
                candidate,candidate_proof=adapter.project_declarations(initial,bundle)
                declared=adapter.check_declarations(candidate,inventory,bundle,config['max_source_items'],
                    strict_field_owner=config.get('catalog_evidence_mode','strict')=='strict')
                declarations,selection_proof=candidate,candidate_proof
            elif index==1:
                candidate=items.parse_response(adapter.CatalogCompletion,entry['raw_output'])
                augmented,augmented_catalog,candidate_proof=adapter.complete(declarations,candidate,inventory,bundle,
                    config['max_source_items'],strict_field_owner=config.get('catalog_evidence_mode','strict')=='strict')
                completion,declarations,declared,completion_proof=candidate,augmented,augmented_catalog,candidate_proof
            elif index==2:
                relations=items.parse_response(adapter.Relations,entry['raw_output'])
                candidate,candidate_proof=adapter.project(declarations,relations,bundle)
                all_items=items.check_catalog(candidate,inventory,bundle,config['max_source_items'])
                candidate_audit=adapter.audit_catalog(candidate,inventory,bundle)
                catalog,proof,audit=candidate,candidate_proof,candidate_audit
                plans=items.groups(all_items,config['group_size'])
            elif index==3:
                candidate=items.parse_response(adapter.OwnerBindings,entry['raw_output'])
                derived_owned,derived_plan,derived_projection=adapter.bind(candidate,declarations,relations,inventory,bundle)
                selection,owned,owner_plan,owner_projection=candidate,derived_owned,derived_plan,derived_projection
            elif index<=len(plans)+3:
                group=items.parse_response(items.ItemGroup,entry['raw_output'])
                items.check_group(group,plans[index-4],catalog,bundle.work_id)
                adapter.Ownership.check_group(group,owner_plan)
                decisions.update(group.decisions)
                outcomes.append(dict(stage=entry['name'],item_ids=plans[index-4],valid_decision_objects=True))
            else:
                candidate=items.parse_response(items.ContextLinks,entry['raw_output'])
                items.check_links(candidate,inventory,items.graph_objects(catalog,decisions));links=candidate
        except (ValidationError,ValueError,KeyError) as error:
            errors.append(dict(stage=entry['name'],**diagnostic(error)))
            if index<=3:
                if index==0:declared=None
                if len(entries)!=index+1:raise ValueError('staged_calls_after_invalid_catalog')
                break
            if index<=len(plans)+3:
                outcomes.append(dict(stage=entry['name'],item_ids=plans[index-4],valid_decision_objects=False))
    return dict(declarations=declarations,declared_catalog=declared,catalog=catalog,plans=plans,
        decisions=decisions,links=links,errors=errors,group_outcomes=outcomes,
        catalog_projection=proof,catalog_diagnostic=audit,item_owner_plan=owner_plan,
        owner_declarations=owned,catalog_relations=relations,owner_bindings=selection,
        owner_selection_projection=owner_projection,initial_source_declarations=initial,
        source_selection_projection=selection_proof,catalog_completion=completion,
        catalog_completion_projection=completion_proof)
