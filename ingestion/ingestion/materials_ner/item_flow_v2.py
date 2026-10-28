"""Versioned split-catalog stage replay; historical v1 journals stay unchanged."""
from pydantic import ValidationError

from . import catalog_stages as catalogs, item_stages as items
from .contract import digest
from .validation import validate_extraction, training_exclusions

OUTPUT_FORMAT = 'materials-source-item-transcript/2'
WORKFLOW = 'source_item_stages_v2'
PROMPT_VERSION = 'materials-source-item-prompt/2.1.0'
PROMPT_HASH = digest({'version': PROMPT_VERSION, 'declarations': catalogs.DECLARATION_RULES,
    'relations': catalogs.RELATION_RULES, 'remaining_stages': items.PROMPT_HASH})


def interfaces(config):
    """Select immutable versioned adapters; no module state is patched."""
    if config['output_format'] == 'materials-source-item-transcript/5':
        from . import selected_catalog_stages as adapter, identity_stages
        if (config.get('workflow')!=adapter.WORKFLOW or config.get('field_generation_policy')!=adapter.POLICY
                or config.get('owner_binding_version')!=adapter.BINDING_VERSION
                or config.get('item_owner_policy')!=identity_stages.POLICY
                or config.get('source_selection_version')!=adapter.SELECTION_VERSION
                or config.get('catalog_completion_version')!=adapter.COMPLETION_VERSION
                or config.get('max_catalog_completions')!=1
                or config.get('max_catalog_added_entities')!=adapter.MAX_ADDED_ENTITIES):
            raise ValueError('staged_selected_catalog_configuration_mismatch')
        return adapter,adapter.Ownership,adapter.assemble,adapter.OUTPUT_FORMAT
    if config['output_format'] == 'materials-source-item-transcript/4':
        from . import frozen_owner_stages as adapter, identity_stages
        if config.get('field_generation_policy') == 'target_context_v1':
            from . import target_context_stages as adapter
        if config.get('field_generation_policy') in {'source_atoms_v1','row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
            from .source_atom_stages import Adapter
            context = config.get('source_atom_context')
            if (not isinstance(context, dict) or digest(context) != config.get('source_atom_context_sha256')
                    or config.get('native_output_schema') != ('materials-ner/11' if config['field_generation_policy'] in {'row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'} else 'materials-ner/10')):
                raise ValueError('staged_atom_context_hash_mismatch')
            adapter = Adapter(context)
            if config['field_generation_policy'] in {'row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
                from .row_catalog_stages import Adapter as RowAdapter
                if config['field_generation_policy'] == 'row_fields_v2':
                    from .scientific_row_stages import Adapter as RowAdapter
                if config['field_generation_policy'] in {'row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
                    from .positioned_row_stages import Adapter as RowAdapter
                    from .validation import POSITIONED_VALIDATOR_VERSION
                    from .source_quantity_audit import POSITIONED_POLICY
                    if config.get('validator_version') != POSITIONED_VALIDATOR_VERSION:
                        raise ValueError('staged_positioned_validator_version_mismatch')
                    if config.get('source_quantity_audit_policy') != POSITIONED_POLICY:
                        raise ValueError('staged_positioned_quantity_audit_policy_mismatch')
                if config['field_generation_policy'] in {'row_fields_v4','row_fields_v5','row_fields_v6'}:
                    from .scoped_row_stages import Adapter as RowAdapter
                    if config['field_generation_policy'] in {'row_fields_v5','row_fields_v6'}:
                        from .assertion_scope_stages import Adapter as RowAdapter
                    if config['field_generation_policy'] == 'row_fields_v6':
                        from .method_context_stages import Adapter as RowAdapter
                    from .compact_context import VERSION
                    if config.get('context_selection_version') != getattr(RowAdapter, 'CONTEXT_SELECTION_VERSION', VERSION):
                        raise ValueError('staged_compact_context_version_mismatch')
                scope = config.get('catalog_scope')
                if not isinstance(scope, dict) or digest(scope) != config.get('catalog_scope_sha256'):
                    raise ValueError('staged_row_scope_hash_mismatch')
                adapter = RowAdapter(context, scope)
        if (config.get('workflow') != adapter.WORKFLOW or config.get('field_generation_policy') != adapter.POLICY
                or config.get('owner_binding_version') != adapter.BINDING_VERSION
                or config.get('item_owner_policy') != identity_stages.POLICY):
            raise ValueError('staged_frozen_owner_configuration_mismatch')
        return adapter, adapter.Ownership, adapter.assemble, adapter.OUTPUT_FORMAT
    if config['output_format'] == 'materials-source-item-transcript/3':
        from . import identity_stages
        if (config.get('workflow') != identity_stages.WORKFLOW
                or config.get('item_owner_policy') != identity_stages.POLICY):
            raise ValueError('staged_identity_configuration_mismatch')
        field_policy = config.get('field_generation_policy')
        if field_policy is not None:
            from .item_worker import field_adapter
            adapter = field_adapter(field_policy)
            return adapter, adapter.Ownership, adapter.assemble, adapter.OUTPUT_FORMAT
        return identity_stages, identity_stages.Ownership, identity_stages.assemble, identity_stages.OUTPUT_FORMAT
    from . import item_ownership
    return catalogs, item_ownership, items.assemble, OUTPUT_FORMAT


def replay(transcript, bundle, inventory, config):
    if config['output_format'] == 'materials-source-item-transcript/5':
        interfaces(config)
        from .item_flow_v5 import replay as replay_v5
        return replay_v5(transcript,bundle,inventory,config)
    if config['output_format'] == 'materials-source-item-transcript/4':
        interfaces(config)
        from .item_flow_v4 import replay as replay_v4
        return replay_v4(transcript,bundle,inventory,config)
    from .item_worker import diagnostic
    catalogs, owners, _, output_format = interfaces(config)
    owner_policy = config.get('item_owner_policy'); owner_plan = None
    if owner_policy is not None:
        if owner_policy not in owners.POLICIES:raise ValueError('staged_item_owner_policy_unknown')
    if (transcript.get('schema') != output_format or transcript.get('work_id') != bundle.work_id
            or transcript.get('parent_run_id') != config['parent_run_id']):
        raise ValueError('staged_transcript_binding_mismatch')
    entries = transcript['entries']; declarations = declared = catalog = links = proof = audit = None
    owned = relations = None
    decisions = {}; plans = []; errors = []; outcomes = []
    for index, entry in enumerate(entries):
        expected = ('declarations' if index == 0 else 'catalog-relations' if index == 1
            else f'items-{index-1}' if index <= len(plans)+1 else 'contexts')
        if entry['name'] != expected or index > len(plans)+2:
            raise ValueError('staged_transcript_order_invalid')
        if entry['raw_output'] is None:
            if index != len(entries)-1: raise ValueError('staged_calls_after_provider_failure')
            errors.append({'stage': entry['name'], 'code': 'staged_provider_stage_incomplete'})
            break
        try:
            if index == 0:
                if owner_policy is not None:
                    owned = items.parse_response(getattr(owners, 'OwnedDeclarations', owners.Declarations),entry['raw_output'])
                    declarations = owners.body(owned)
                    owner_plan = owners.project(owned,inventory,bundle,policy=owner_policy)
                else:
                    declarations = items.parse_response(catalogs.Declarations, entry['raw_output'])
                declared = catalogs.check_declarations(declarations, inventory, bundle, config['max_source_items'],
                    strict_field_owner=config.get('catalog_evidence_mode', 'strict') == 'strict')
            elif index == 1:
                relations = items.parse_response(catalogs.Relations, entry['raw_output'])
                candidate, candidate_proof = catalogs.project(declarations, relations, bundle)
                source_items = items.check_catalog(candidate, inventory, bundle, config['max_source_items'])
                candidate_audit = catalogs.audit_catalog(candidate, inventory, bundle)
                plans = items.groups(source_items, config['group_size'])
                catalog, proof, audit = candidate, candidate_proof, candidate_audit
            elif index <= len(plans)+1:
                group = items.parse_response(items.ItemGroup, entry['raw_output'])
                items.check_group(group, plans[index-2], catalog, bundle.work_id)
                if owner_policy is not None:owners.check_group(group,owner_plan)
                decisions.update(group.decisions)
                outcomes.append({'stage': entry['name'], 'item_ids': plans[index-2], 'valid_decision_objects': True})
            else:
                candidate = items.parse_response(items.ContextLinks, entry['raw_output'])
                items.check_links(candidate, inventory, items.graph_objects(catalog, decisions))
                links = candidate
        except (ValidationError, ValueError, KeyError) as error:
            errors.append({'stage': entry['name'], **diagnostic(error)})
            if index <= 1:
                if index == 0: declared = None
                if len(entries) != index+1: raise ValueError('staged_calls_after_invalid_catalog')
                break
            if index <= len(plans)+1:
                outcomes.append({'stage': entry['name'], 'item_ids': plans[index-2], 'valid_decision_objects': False})
    return {'declarations': declarations, 'declared_catalog': declared, 'catalog': catalog, 'plans': plans,
        'decisions': decisions, 'links': links, 'errors': errors, 'group_outcomes': outcomes,
        'catalog_projection': proof, 'catalog_diagnostic': audit, 'item_owner_plan':owner_plan,
        'owner_declarations': owned, 'catalog_relations': relations}


def assembly_options(result, config):
    options = {'owner_plan': result['item_owner_plan']} if config['output_format'].endswith(('/3','/4','/5')) else {}
    if config.get('field_generation_policy') in {'source_fields_v2', 'source_fields_v3', 'source_fields_v4','source_fields_v5','target_context_v1','source_atoms_v1','row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
        options.update(owner_declarations=result['owner_declarations'], catalog_relations=result['catalog_relations'])
    if config['output_format'].endswith(('/4','/5')):
        options.update(source_declarations=result['declarations'],owner_bindings=result['owner_bindings'])
    if config['output_format'].endswith('/5'):
        options.update(initial_source_declarations=result['initial_source_declarations'],catalog_completion=result['catalog_completion'],
            max_source_items=config['max_source_items'])
    if config.get('field_generation_policy') in {'row_fields_v4','row_fields_v5','row_fields_v6'}:
        options.update(context_selection=result['context_selection'],context_projection=result['context_projection'])
    return options


def assembled_report(transcript, bundle, inventory, config):
    from .item_worker import diagnostic
    result = replay(transcript, bundle, inventory, config)
    _, _, assemble, output_format = interfaces(config)
    report = {key: result[key] for key in ('group_outcomes', 'catalog_projection', 'catalog_diagnostic')}
    report['staged_errors'] = result['errors']
    report['declared_catalog'] = result['declared_catalog'].model_dump() if result['declared_catalog'] else None
    if config.get('item_owner_policy') is not None:report['item_owner_plan']=result['item_owner_plan']
    if output_format.endswith('/5'):
        for key in ('source_selection_projection','catalog_completion_projection'):report[key]=result[key]
    if output_format.endswith(('/4','/5')):
        report['owner_selection_projection']=result['owner_selection_projection']
        if result['item_owner_plan'] is None:return report
    catalog = result['catalog']
    if catalog is None: return report
    all_items, _ = items.inventory_items(inventory, catalog)
    missing = [x.id for x in all_items if x.id not in result['decisions']]
    errors = list(result['errors'])
    if len(transcript['entries']) < len(result['plans'])+(5 if output_format.endswith('/5') else 4 if output_format.endswith('/4') else 3):
        errors.append({'stage': 'assembly', 'code': 'staged_operations_not_completed'})
    if result['catalog_projection']['unresolved_protocol_ids']:
        errors.append({'stage': 'catalog-relations', 'code': 'staged_catalog_relations_unresolved'})
    report['staged_errors'] = errors
    try:
        options = assembly_options(result, config)
        graph, coverage, proof = assemble(bundle, inventory, catalog, result['decisions'], result['links'],
            missing_item_ids=missing, stage_failures=errors, **options)
        extraction = graph.expand(bundle)
    except (ValidationError, ValueError, KeyError) as error:
        report['assembly_error'] = diagnostic(error)
        return report
    validation = validate_extraction(extraction, bundle)
    validation['issues'].extend(coverage['issues'])
    if errors: validation['issues'].append({'code': 'staged_operations_incomplete', 'path': '/'})
    validation['valid'] = not validation['issues']
    report.update(extraction=extraction.model_dump(), validation=validation, inventory_coverage=coverage,
        staged_assembly=proof, training_assessment=training_exclusions(extraction, bundle, validation))
    policy=config.get('source_quantity_audit_policy')
    if policy is not None:
        from .source_quantity_audit import audit
        report['source_quantity_audit']=audit(graph,bundle,policy=policy)
    return report
