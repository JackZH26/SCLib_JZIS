"""Durable staged extraction from a verified, frozen source inventory.

The final output file is explicitly a transcript of real stage responses, not a
claimed single model response. Assembly is reproducible without further calls.
"""
from collections import Counter
import json
import time

from pydantic import ValidationError
import tiktoken

from . import item_stages as stages
from .contract import canonical, digest
from .inventory import Inventory, validate_inventory
from .providers import CodexProvider, ProviderFailure
from .sources import check_admission, private_write, sha, save_bundle, load_bundle
from .validation import validate_extraction, training_exclusions

OUTPUT_FORMAT = 'materials-source-item-transcript/1'
PARENT_FORMATS = {'materials-ner-shared/5', 'materials-ner-shared/6', 'materials-ner-shared/7'}


def verify_parent(parent, bundle=None, *, workflow="source_item_stages_v1"):
    from . import frozen_inventory
    if parent.get('schema') in frozen_inventory.FORMATS:
        return frozen_inventory.verify(parent, bundle)
    from .proposals import verify_packet
    verify_packet(parent)
    formats = PARENT_FORMATS | {'materials-ner-shared/8'} if workflow in {'source_item_stages_v3','source_item_stages_v4','source_item_stages_v5'} else PARENT_FORMATS
    if parent['receipt']['config']['output_format'] not in formats:
        raise ValueError('staged_inventory_parent_format_not_supported')
    inventory = Inventory.model_validate(parent['receipt']['inventory'])
    if bundle is None:
        from .sources import Bundle
        bundle = Bundle.model_validate(parent['bundle'])
    if digest(bundle.model_dump()) != parent['bundle_hash']:
        raise ValueError('staged_inventory_parent_source_mismatch')
    if not validate_inventory(inventory, bundle)['valid']:
        raise ValueError('staged_inventory_parent_invalid')
    return inventory


def field_adapter(policy, *, source_atom_context=None, catalog_scope=None):
    if policy == 'row_fields_v6':
        from .method_context_stages import Adapter
        return Adapter(source_atom_context, catalog_scope)
    if policy == 'row_fields_v5':
        from .assertion_scope_stages import Adapter
        return Adapter(source_atom_context, catalog_scope)
    if policy == 'row_fields_v4':
        from .scoped_row_stages import Adapter
        return Adapter(source_atom_context, catalog_scope)
    if policy == 'row_fields_v3':
        from .positioned_row_stages import Adapter
        return Adapter(source_atom_context, catalog_scope)
    if policy == 'row_fields_v2':
        from .scientific_row_stages import Adapter
        return Adapter(source_atom_context, catalog_scope)
    if policy == 'row_fields_v1':
        from .row_catalog_stages import Adapter
        return Adapter(source_atom_context, catalog_scope)
    if policy == 'source_atoms_v1':
        from .source_atom_stages import Adapter
        return Adapter(source_atom_context)
    from . import source_field_stages, owner_witness_stages, quantity_field_stages, frozen_owner_stages, selected_catalog_stages, target_context_stages
    adapters = {module.POLICY: module for module in (source_field_stages, owner_witness_stages, quantity_field_stages, frozen_owner_stages, selected_catalog_stages, target_context_stages)}
    if policy not in adapters:
        raise ValueError('staged_field_generation_policy_unknown')
    return adapters[policy]


def configuration(parent, *, group_size=4, max_source_items=64, workflow='source_item_stages_v1',
                  catalog_evidence_mode='diagnostic', item_owner_policy=None, field_generation_policy=None,
                  source_atom_context=None, catalog_scope=None, **kwargs):
    if catalog_scope is not None and (workflow != 'source_item_stages_v4' or field_generation_policy not in {'row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}):
        raise ValueError('staged_row_scope_policy_mismatch')
    if source_atom_context is not None and (workflow != 'source_item_stages_v4' or field_generation_policy not in {'source_atoms_v1','row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}):
        raise ValueError('staged_atom_context_policy_mismatch')
    if workflow == 'source_item_stages_v5':
        from . import selected_catalog_stages as adapter, identity_stages
        if field_generation_policy not in {None,adapter.POLICY} or item_owner_policy not in {None,identity_stages.POLICY}:
            raise ValueError('staged_selected_catalog_configuration_mismatch')
        config=configuration(parent,group_size=group_size,max_source_items=max_source_items,
            workflow='source_item_stages_v4',catalog_evidence_mode=catalog_evidence_mode,
            item_owner_policy=identity_stages.POLICY,field_generation_policy='source_fields_v4',**kwargs)
        config.update(workflow=adapter.WORKFLOW,output_format=adapter.OUTPUT_FORMAT,field_generation_policy=adapter.POLICY,
            source_selection_version=adapter.SELECTION_VERSION,catalog_completion_version=adapter.COMPLETION_VERSION,
            max_catalog_completions=1,max_catalog_added_entities=adapter.MAX_ADDED_ENTITIES,
            prompt_version=adapter.PROMPT_VERSION,prompt_sha256=adapter.PROMPT_HASH,
            schema_sha256=digest([adapter.declaration_schema(),adapter.completion_schema(),adapter.relation_schema(),
                adapter.binding_schema(),adapter.item_schema(),adapter.links_schema()]))
        return config
    if workflow == 'source_item_stages_v4':
        from . import frozen_owner_stages as adapter, identity_stages
        if field_generation_policy == 'target_context_v1':
            from . import target_context_stages as adapter
        if field_generation_policy in {'source_atoms_v1','row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
            from . import source_atoms
            from .sources import Bundle
            if source_atom_context is None:
                raise ValueError('staged_atom_context_required')
            bundle = Bundle.model_validate(parent['bundle'])
            inventory = verify_parent(parent, bundle, workflow=workflow)
            source_atoms.verify_context(source_atom_context, bundle, inventory, parent)
            adapter = field_adapter(field_generation_policy, source_atom_context=source_atom_context, catalog_scope=catalog_scope)
            if field_generation_policy in {'row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
                adapter.verify_scope(bundle, inventory)
        if field_generation_policy not in {None,adapter.POLICY} or item_owner_policy not in {None,identity_stages.POLICY}:
            raise ValueError('staged_frozen_owner_configuration_mismatch')
        config=configuration(parent,group_size=group_size,max_source_items=max_source_items,
            workflow='source_item_stages_v3',catalog_evidence_mode=catalog_evidence_mode,
            item_owner_policy=identity_stages.POLICY,field_generation_policy='source_fields_v3',**kwargs)
        config.update(workflow=adapter.WORKFLOW,output_format=adapter.OUTPUT_FORMAT,field_generation_policy=adapter.POLICY,
            owner_binding_version=adapter.BINDING_VERSION,prompt_version=adapter.PROMPT_VERSION,prompt_sha256=adapter.PROMPT_HASH,
            schema_sha256=digest([adapter.declaration_schema(),adapter.relation_schema(),adapter.binding_schema(),
                adapter.item_schema(),adapter.links_schema()]))
        if field_generation_policy in {'source_atoms_v1','row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
            from copy import deepcopy
            config.update(source_atom_context=deepcopy(source_atom_context),
                source_atom_context_sha256=digest(source_atom_context), native_output_schema=adapter.NATIVE_SCHEMA)
            if field_generation_policy in {'row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
                from .validation import POSITIONED_VALIDATOR_VERSION
                from .source_quantity_audit import POSITIONED_POLICY
                config['validator_version'] = POSITIONED_VALIDATOR_VERSION
                config['source_quantity_audit_policy'] = POSITIONED_POLICY
                if field_generation_policy in {'row_fields_v4','row_fields_v5','row_fields_v6'}:
                    from .compact_context import VERSION
                    config['context_selection_version'] = getattr(adapter, 'CONTEXT_SELECTION_VERSION', VERSION)
            if field_generation_policy in {'row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
                config.update(catalog_scope=deepcopy(catalog_scope), catalog_scope_sha256=digest(catalog_scope))
        return config
    from .worker import configuration as base_configuration
    inventory = verify_parent(parent, workflow=workflow)
    if not 1 <= group_size <= 4 or not 1 <= max_source_items <= 128:
        raise ValueError('staged_extraction_budget_invalid')
    if len(inventory.items) > max_source_items:
        raise ValueError('staged_inventory_exceeds_declared_budget')
    if workflow not in {'source_item_stages_v1', 'source_item_stages_v2', 'source_item_stages_v3'}:
        raise ValueError('staged_workflow_not_supported')
    if workflow == 'source_item_stages_v3':
        from . import identity_stages
        owners = identity_stages.Ownership
        if item_owner_policy is None: item_owner_policy = identity_stages.POLICY
    else:
        from . import item_ownership as owners
    if item_owner_policy is not None:
        if workflow not in {'source_item_stages_v2', 'source_item_stages_v3'} or item_owner_policy not in owners.POLICIES:
            raise ValueError('staged_item_owner_policy_unknown')
    if field_generation_policy is not None:
        if workflow != 'source_item_stages_v3' or field_generation_policy in {'source_fields_v4','source_fields_v5','target_context_v1','source_atoms_v1','row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
            raise ValueError('staged_field_generation_policy_unknown')
        fields = field_adapter(field_generation_policy)
        owners = fields.Ownership
    if catalog_evidence_mode not in {'strict', 'diagnostic'}:
        raise ValueError('staged_catalog_evidence_mode_invalid')
    config = base_configuration(workflow='inventory_v12' if workflow == 'source_item_stages_v3' else 'inventory_v11', **kwargs)
    if config['provider'] != 'codex': raise ValueError('staged_provider_not_evaluated')
    config.update(workflow='source_item_stages_v1', output_format=OUTPUT_FORMAT,
        parent_run_id=parent['run_id'], frozen_inventory_sha256=digest(inventory.model_dump()),
        group_size=group_size, max_source_items=max_source_items,
        inventory_link_projection_version=None, max_inventory_repairs=0,
        max_extraction_repairs=0, max_evidence_patches=0,
        schema_sha256=digest([stages.catalog_schema(), stages.item_schema(), stages.links_schema()]),
        prompt_version=stages.PROMPT_VERSION, prompt_sha256=stages.PROMPT_HASH)
    from . import frozen_inventory
    if parent.get('schema') in frozen_inventory.FORMATS:
        config.update(frozen_inventory_snapshot_version=parent['schema'],
            frozen_source_occurrences_sha256=digest(parent['required_occurrences']))
    from .typed_inventory_handoff import source_piece_prompt
    piece_prompt=source_piece_prompt(parent)
    if piece_prompt:config['source_piece_evidence_sha256']=sha(piece_prompt.encode())
    if workflow in {'source_item_stages_v2', 'source_item_stages_v3'}:
        from . import item_flow_v2 as flow, catalog_stages as catalogs
        if workflow == 'source_item_stages_v3':
            flow = catalogs = fields if field_generation_policy is not None else identity_stages
        if field_generation_policy is not None:
            config.update(field_generation_policy=field_generation_policy,
                prompt_inventory_projection_sha256=digest(fields.inventory_ledger(inventory)))
        from .source_quantity_audit import POLICY
        config.update(workflow=workflow, output_format=flow.OUTPUT_FORMAT, catalog_evidence_mode=catalog_evidence_mode,
            source_quantity_audit_policy=POLICY,
            schema_sha256=digest([catalogs.declaration_schema(), catalogs.relation_schema(),
                                 stages.item_schema(), stages.links_schema()]),
            prompt_version=flow.PROMPT_VERSION, prompt_sha256=flow.PROMPT_HASH)
        if item_owner_policy is not None:
            owner_prompt_version,owner_prompt_hash=owners.prompt_identity(item_owner_policy)
            config.update(item_owner_policy=item_owner_policy,
                schema_sha256=digest([owners.declaration_schema(),catalogs.relation_schema(),
                                     owners.item_schema(),getattr(catalogs, 'links_schema', stages.links_schema)()]),
                prompt_version=owner_prompt_version,prompt_sha256=owner_prompt_hash)
    return config


def diagnostic(error):
    from .worker import schema_error_records
    if isinstance(error, ValidationError):
        return {'code': 'staged_output_schema_invalid', 'details': schema_error_records(error)}
    code = str(error)
    return {'code': code if code.startswith('staged_') else 'staged_output_contract_invalid'}


def replay(transcript, bundle, inventory, config):
    """Reconstruct decisions from retained responses, including failed stages."""
    if config['output_format'] in {'materials-source-item-transcript/2', 'materials-source-item-transcript/3', 'materials-source-item-transcript/4', 'materials-source-item-transcript/5'}:
        from .item_flow_v2 import replay as replay_v2
        return replay_v2(transcript, bundle, inventory, config)
    if (transcript.get('schema') != OUTPUT_FORMAT or transcript.get('work_id') != bundle.work_id
            or transcript.get('parent_run_id') != config['parent_run_id']):
        raise ValueError('staged_transcript_binding_mismatch')
    entries = transcript['entries']; catalog = None; decisions = {}; links = None; errors = []
    plans = []; outcomes = []
    for index, entry in enumerate(entries):
        expected = 'catalog' if index == 0 else (f'items-{index}' if index <= len(plans) else 'contexts')
        if entry['name'] != expected or index > len(plans)+1:
            raise ValueError('staged_transcript_order_invalid')
        if entry['raw_output'] is None:
            if index != len(entries)-1: raise ValueError('staged_calls_after_provider_failure')
            errors.append({'stage': entry['name'], 'code': 'staged_provider_stage_incomplete'})
            break
        try:
            if index == 0:
                candidate = stages.parse_response(stages.EntityCatalog, entry['raw_output'])
                items = stages.check_catalog(candidate, inventory, bundle, config['max_source_items'])
                plans = stages.groups(items, config['group_size']); catalog = candidate
            elif index <= len(plans):
                group = stages.parse_response(stages.ItemGroup, entry['raw_output'])
                stages.check_group(group, plans[index-1], catalog, bundle.work_id)
                decisions.update(group.decisions)
                outcomes.append({'stage': entry['name'], 'item_ids': plans[index-1], 'valid_decision_objects': True})
            else:
                candidate = stages.parse_response(stages.ContextLinks, entry['raw_output'])
                stages.check_links(candidate, inventory, stages.graph_objects(catalog, decisions))
                links = candidate
        except (ValidationError, ValueError, KeyError) as error:
            errors.append({'stage': entry['name'], **diagnostic(error)})
            if index == 0:
                if len(entries) != 1: raise ValueError('staged_calls_after_invalid_catalog')
                break
            if index <= len(plans):
                outcomes.append({'stage': entry['name'], 'item_ids': plans[index-1], 'valid_decision_objects': False})
    if catalog is None:
        return {'catalog': None, 'decisions': {}, 'links': None, 'plans': [], 'errors': errors, 'group_outcomes': outcomes}
    return {'catalog': catalog, 'decisions': decisions, 'links': links, 'plans': plans,
            'errors': errors, 'group_outcomes': outcomes}


def assembled_report(transcript, bundle, inventory, config):
    if config['output_format'] in {'materials-source-item-transcript/2', 'materials-source-item-transcript/3', 'materials-source-item-transcript/4', 'materials-source-item-transcript/5'}:
        from .item_flow_v2 import assembled_report as report_v2
        return report_v2(transcript, bundle, inventory, config)
    result = replay(transcript, bundle, inventory, config)
    report = {'staged_errors': result['errors'], 'group_outcomes': result['group_outcomes']}
    catalog = result['catalog']
    if catalog is None: return report
    items, _ = stages.inventory_items(inventory, catalog)
    missing = [x.id for x in items if x.id not in result['decisions']]
    # An unfinished journal is an explicit operational failure, never an empty.
    errors = list(result['errors'])
    if len(transcript['entries']) < len(result['plans'])+2:
        errors.append({'stage': 'assembly', 'code': 'staged_operations_not_completed'})
    report['staged_errors'] = errors
    try:
        graph, coverage, proof = stages.assemble(bundle, inventory, catalog, result['decisions'], result['links'],
            missing_item_ids=missing, stage_failures=errors)
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
    return report


def enqueue(store, parent, **kwargs):
    from .sources import Bundle
    config = configuration(parent, **kwargs)
    bundle = Bundle.model_validate(parent['bundle']); key, _ = save_bundle(store.root, bundle)
    path = store.root/'parents'/(parent['run_id']+'.json'); raw = canonical(parent).encode()
    if path.exists() and path.read_bytes() != raw: raise ValueError('staged_parent_snapshot_conflict')
    if not path.exists(): private_write(path, raw)
    return store.enqueue(work_id=bundle.work_id, bundle_hash=key, config=config, max_attempts=1)


def run_one(store, job_id, *, provider_override=None, max_seconds=None):
    job = store.claim(lease_seconds=3900, job_id=job_id)
    if job is None: return None
    return run_claimed(store, job, provider_override=provider_override, max_seconds=max_seconds)


def run_claimed(store, job, *, provider_override=None, max_seconds=None):
    from .worker import implementation_sources
    directory = store.root/'attempts'/job['id']/job['lease_token']
    directory.mkdir(parents=True, mode=0o700)
    config = job['config']; started = time.monotonic(); usage = Counter()
    receipt = {'schema': 'materials-staged-ner-attempt/1', 'job_id': job['id'], 'attempt_id': job['lease_token'],
        'work_id': job['work_id'], 'bundle_sha256': job['bundle_hash'], 'config': config,
        'raw_output_kind': 'assembled_stage_transcript', 'output_token_limit_enforced_by_provider': False,
        'scientific_acceptance': False, 'production_writes': False, 'stages': []}
    transcript = {'schema': config['output_format'], 'work_id': job['work_id'], 'parent_run_id': config['parent_run_id'], 'entries': []}
    state = 'failed'; error_code = None; retryable = False
    inventory = bundle = None
    piece_prompt = ''
    def save_transcript():
        raw = canonical(transcript).encode(); private_write(directory/'output.json', raw)
        receipt['raw_output_sha256'] = sha(raw)
    def call(name, prompt, schema):
        if piece_prompt:prompt+='\n'+piece_prompt
        stage_dir = directory/name
        entry = {'name': name, 'raw_output': None, 'prompt': prompt, 'schema': schema}
        transcript['entries'].append(entry); save_transcript()
        info = {'name': name, 'prompt_sha256': sha(prompt.encode()), 'schema_sha256': digest(schema)}
        receipt['stages'].append(info)
        tokens = len(tiktoken.get_encoding('cl100k_base').encode(prompt+canonical(schema), disallowed_special=()))
        info['input_count'] = {'tokens': tokens, 'tokenizer': 'cl100k_base', 'provider_exact': False}
        private_write(stage_dir/'input.txt', prompt.encode()); private_write(stage_dir/'schema.json', canonical(schema).encode())
        if tokens > config['max_input_tokens']: raise ProviderFailure('stage_input_budget_exceeded')
        budget = min(config['timeout_seconds'], max_seconds) if max_seconds is not None else config['timeout_seconds']
        remaining = budget - (time.monotonic()-started)
        if remaining < 1: raise ProviderFailure('run_wall_budget_exhausted')
        info['timeout_seconds'] = remaining
        response = (provider_override or CodexProvider()).extract(prompt, schema, dict(config, timeout_seconds=remaining), stage_dir)
        usage.update(response.usage); entry['raw_output'] = response.text
        info.update(provider=response.provider, model=response.model, response_id=response.response_id,
            elapsed_seconds=response.elapsed_seconds, usage=response.usage, raw_output_sha256=sha(response.text.encode()))
        private_write(stage_dir/'output.json', response.text.encode()); save_transcript()
    try:
        parent = json.loads((store.root/'parents'/(config['parent_run_id']+'.json')).read_text())
        bundle = load_bundle(store.root/'bundles'/f'{job["bundle_hash"]}.json')
        inventory = verify_parent(parent, bundle, workflow=config['workflow'])
        from .typed_inventory_handoff import source_piece_prompt
        piece_prompt=source_piece_prompt(parent)
        receipt.update(source_inventory_parent=parent, inventory=inventory.model_dump())
        expected = configuration(parent, group_size=config['group_size'], max_source_items=config['max_source_items'], workflow=config['workflow'],
            catalog_evidence_mode=config.get('catalog_evidence_mode', 'strict'),
            item_owner_policy=config.get('item_owner_policy'), field_generation_policy=config.get('field_generation_policy'),
            source_atom_context=config.get('source_atom_context'),
            catalog_scope=config.get('catalog_scope'),
            **{key: config[key] for key in ('provider', 'model', 'reasoning', 'timeout_seconds', 'max_input_tokens', 'max_output_tokens')})
        if expected != config or job['bundle_hash'] != digest(bundle.model_dump()) or job['work_id'] != bundle.work_id:
            raise ProviderFailure('staged_worker_contract_drift')
        if check_admission(bundle): raise ProviderFailure('staged_source_not_admitted')
        sources = implementation_sources()
        if digest({key: sha(value) for key, value in sources.items()}) != config['implementation_sha256']:
            raise ProviderFailure('worker_source_changed_during_capture')
        code = store.root/'implementations'/config['implementation_sha256']
        for name, value in sources.items():
            path = code/name
            if path.exists() and path.read_bytes() != value: raise ProviderFailure('implementation_snapshot_corrupt')
            if not path.exists(): private_write(path, value)
        private_write(code/'manifest.json', canonical({'files': {k: sha(v) for k, v in sources.items()}, 'runtime': config['runtime']}).encode())
        save_transcript()
        catalogs = None
        link_prompt = stages.render_links; link_schema = stages.links_schema
        if config['workflow'] in {'source_item_stages_v2', 'source_item_stages_v3', 'source_item_stages_v4', 'source_item_stages_v5'}:
            from .item_flow_v2 import interfaces
            catalogs, owners, _, _ = interfaces(config)
            link_prompt = getattr(catalogs, 'render_links', stages.render_links)
            link_schema = getattr(catalogs, 'links_schema', stages.links_schema)
            if config.get('item_owner_policy') is not None:
                call('declarations',owners.render_declarations(bundle,inventory,policy=config['item_owner_policy']),owners.declaration_schema(bundle,inventory))
            else:
                call('declarations', catalogs.render_declarations(bundle, inventory), catalogs.declaration_schema(bundle))
            declared = replay(transcript, bundle, inventory, config)['declared_catalog']
            if declared is None: raise ProviderFailure('staged_catalog_invalid')
            if config['workflow'] == 'source_item_stages_v5':
                parsed=replay(transcript,bundle,inventory,config)
                call('catalog-completion',catalogs.render_completion(bundle,inventory,parsed['declarations'],declared),
                    catalogs.completion_schema(bundle,declared))
                parsed=replay(transcript,bundle,inventory,config)
                if parsed['catalog_completion'] is None:raise ProviderFailure('staged_catalog_invalid')
                declared=parsed['declared_catalog']
            call('catalog-relations', catalogs.render_relations(bundle, inventory, declared), catalogs.relation_schema(bundle, declared))
        else:
            call('catalog', stages.render_catalog(bundle, inventory), stages.catalog_schema(bundle))
        parsed = replay(transcript, bundle, inventory, config)
        if parsed['catalog'] is None: raise ProviderFailure('staged_catalog_invalid')
        catalog = parsed['catalog']; all_items, _ = stages.inventory_items(inventory, catalog)
        if config['workflow'] in {'source_item_stages_v4','source_item_stages_v5'}:
            owner_options = {'declarations': parsed['declarations']} if config.get('field_generation_policy') in {'source_atoms_v1','row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'} else {}
            call('item-owners',catalogs.render_bindings(bundle,inventory,catalog,**owner_options),
                catalogs.binding_schema(bundle,inventory,catalog,**owner_options))
            parsed=replay(transcript,bundle,inventory,config)
            if parsed['item_owner_plan'] is None:raise ProviderFailure('staged_catalog_invalid')
        for index, item_ids in enumerate(parsed['plans'], 1):
            if config.get('item_owner_policy') is not None:
                call(f'items-{index}',owners.render_items(bundle,inventory,catalog,item_ids,parsed['item_owner_plan']),
                    owners.item_schema(bundle,catalog,item_ids,all_items,plan=parsed['item_owner_plan']))
            else:
                call(f'items-{index}', stages.render_items(bundle, inventory, catalog, item_ids),
                     stages.item_schema(bundle, catalog, item_ids, all_items))
        parsed = replay(transcript, bundle, inventory, config)
        graph = (catalogs.context_graph(catalog,parsed['decisions'],bundle) if hasattr(catalogs,'context_graph')
                 else stages.graph_objects(catalog, parsed['decisions']))
        call('contexts', link_prompt(bundle, inventory, graph), link_schema(bundle, inventory, graph))
    except ProviderFailure as error:
        error_code, retryable = error.code, error.retryable; usage.update(error.usage)
    except (ValidationError, ValueError, KeyError, OSError) as error:
        error_code = 'staged_worker_contract_invalid'; receipt['worker_diagnostic'] = diagnostic(error)
    save_transcript()
    report = assembled_report(transcript, bundle, inventory, config) if inventory is not None else {}
    if inventory is not None and config.get('frozen_inventory_snapshot_version'):
        attach_source_accounting(report, parent, bundle)
    receipt.update(report)
    if error_code is None:
        if 'extraction' not in report:
            state, error_code = 'quarantined', 'staged_output_contract_invalid'
        elif report['validation']['valid']:
            state = 'success_empty' if report['extraction']['outcome'] == 'empty' else 'succeeded'
        else:
            state, error_code = 'quarantined', 'source_or_scientific_contract_validation_failed'
    elif error_code == 'staged_catalog_invalid': state = 'quarantined'
    receipt.update(state=state, error_code=error_code, retryable=retryable, usage=usage,
                   elapsed_seconds=time.monotonic()-started)
    path = directory/'receipt.json'; raw = canonical(receipt).encode(); private_write(path, raw)
    store.finish(job, state=state, receipt_path=str(path.relative_to(store.root)), receipt_hash=sha(raw),
        usage=usage, duration_seconds=receipt['elapsed_seconds'], error_code=error_code, retryable=retryable)
    return {key: receipt[key] for key in ('job_id', 'state', 'error_code', 'usage', 'elapsed_seconds')}


def verify_receipt(receipt, bundle, raw_output):
    transcript = json.loads(raw_output)
    if 'source_inventory_parent' not in receipt:
        if (receipt['state'] != 'failed' or receipt.get('extraction') or transcript.get('entries')
                or receipt.get('stages')):
            raise ValueError('staged_failed_preflight_has_scientific_payload')
        return {}
    inventory = verify_parent(receipt['source_inventory_parent'], bundle, workflow=receipt['config']['workflow'])
    from . import frozen_inventory
    if ((receipt['source_inventory_parent'].get('schema') in frozen_inventory.FORMATS)
            != bool(receipt['config'].get('frozen_inventory_snapshot_version'))):
        raise ValueError('staged_frozen_parent_policy_mismatch')
    if (receipt['config']['parent_run_id'] != receipt['source_inventory_parent']['run_id']
            or receipt['config']['frozen_inventory_sha256'] != digest(inventory.model_dump())
            or inventory.model_dump() != receipt['inventory']
            or receipt.get('raw_output_kind') != 'assembled_stage_transcript'):
        raise ValueError('staged_receipt_parent_binding_mismatch')
    if receipt['config'].get('field_generation_policy') is not None:
        fields = field_adapter(receipt['config']['field_generation_policy'])
        if receipt['config'].get('prompt_inventory_projection_sha256') != digest(fields.inventory_ledger(inventory)):
            raise ValueError('staged_prompt_inventory_projection_mismatch')
    if receipt['config'].get('field_generation_policy') in {'source_atoms_v1','row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
        from .source_atoms import verify_context
        context = receipt['config'].get('source_atom_context')
        if not isinstance(context, dict) or digest(context) != receipt['config'].get('source_atom_context_sha256'):
            raise ValueError('staged_atom_context_hash_mismatch')
        verify_context(context, bundle, inventory, receipt['source_inventory_parent'])
        if receipt['config']['field_generation_policy'] in {'row_fields_v1','row_fields_v2','row_fields_v3','row_fields_v4','row_fields_v5','row_fields_v6'}:
            scope = receipt['config'].get('catalog_scope')
            if not isinstance(scope, dict) or digest(scope) != receipt['config'].get('catalog_scope_sha256'):
                raise ValueError('staged_row_scope_hash_mismatch')
            field_adapter(receipt['config']['field_generation_policy'], source_atom_context=context, catalog_scope=scope).verify_scope(bundle, inventory)
    if len(transcript['entries']) != len(receipt['stages']): raise ValueError('staged_receipt_stage_count_mismatch')
    from .typed_inventory_handoff import source_piece_prompt
    piece_prompt=source_piece_prompt(receipt['source_inventory_parent'])
    if (bool(piece_prompt)!=bool(receipt['config'].get('source_piece_evidence_sha256'))
            or (piece_prompt and sha(piece_prompt.encode())!=receipt['config']['source_piece_evidence_sha256'])):
        raise ValueError('staged_source_piece_evidence_config_mismatch')
    for entry, stage in zip(transcript['entries'], receipt['stages']):
        if piece_prompt and not entry['prompt'].endswith('\n'+piece_prompt):
            raise ValueError('staged_source_piece_evidence_prompt_mismatch')
        if (entry['name'] != stage['name'] or sha(entry['prompt'].encode()) != stage['prompt_sha256']
                or digest(entry['schema']) != stage['schema_sha256']):
            raise ValueError('staged_receipt_input_hash_mismatch')
        if entry['raw_output'] is not None and sha(entry['raw_output'].encode()) != stage.get('raw_output_sha256'):
            raise ValueError('staged_receipt_raw_stage_hash_mismatch')
    report = assembled_report(transcript, bundle, inventory, receipt['config'])
    if receipt['config'].get('frozen_inventory_snapshot_version'):
        from . import frozen_inventory
        parent = receipt['source_inventory_parent']
        if (receipt['config']['frozen_inventory_snapshot_version'] != parent['schema']
                or receipt['config'].get('frozen_source_occurrences_sha256') != digest(parent['required_occurrences'])):
            raise ValueError('staged_frozen_occurrence_config_mismatch')
        attach_source_accounting(report, parent, bundle)
        if report['frozen_source_accounting'] != receipt.get('frozen_source_accounting'):
            raise ValueError('staged_frozen_occurrence_receipt_mismatch')
    for key in ('staged_errors', 'group_outcomes', 'assembly_error', 'staged_assembly', 'extraction', 'inventory_coverage',
                'declared_catalog', 'catalog_projection', 'source_quantity_audit', 'item_owner_plan', 'owner_selection_projection',
                'source_selection_projection', 'catalog_completion_projection'):
        if receipt.get(key) != report.get(key): raise ValueError('staged_receipt_assembly_mismatch')
    diagnostic_report = report.get('catalog_diagnostic')
    retained_diagnostic = receipt.get('catalog_diagnostic')
    if bool(diagnostic_report) != bool(retained_diagnostic) or (diagnostic_report and
            diagnostic_report['catalog_sha256'] != retained_diagnostic.get('catalog_sha256')):
        raise ValueError('staged_receipt_catalog_diagnostic_binding_mismatch')
    # Historical validation stays pinned; later validator versions replay into
    # separate artifacts rather than altering old rows or scientific status.
    if 'validation' in report and receipt['validation']['extraction_sha256'] != report['validation']['extraction_sha256']:
        raise ValueError('staged_receipt_extraction_binding_mismatch')
    return report


def attach_source_accounting(report, parent, bundle):
    from .frozen_inventory import outcome_accounting
    from .contract import parse_extraction
    accounting = outcome_accounting(parent, report)
    report['frozen_source_accounting'] = accounting
    if 'extraction' in report and not accounting['fully_materialized']:
        report['validation']['issues'].append({'code': 'frozen_source_occurrences_not_materialized', 'path': '/'})
        report['validation']['valid'] = False
        report['training_assessment'] = training_exclusions(
            parse_extraction(report['extraction']), bundle, report['validation'])
