"""One durable blind source audit; comparison is performed after the model call."""
from collections import Counter
import time

from pydantic import ValidationError
import tiktoken

from .contract import canonical, digest
from .providers import CodexProvider, ProviderFailure
from .scoped_review import resolve_parent
from .sources import check_admission, private_write, sha
from . import source_mentions as audit


def _format(config):
    if config.get('source_context_format')=='materials-mention-local-context/1':
        from . import source_local_audit
        return source_local_audit
    if config.get('source_context_format') is not None:raise ValueError('source_audit_context_format_unknown')
    return audit


def _compare(config,candidate,inventory,graph,bundle):
    version=config.get('audit_comparison_version','materials-source-audit-comparison/1')
    if version=='materials-source-audit-comparison/1':return audit.compare_inventory(candidate,inventory,graph,bundle)
    if version=='materials-source-audit-comparison/2':
        from .source_local_audit import compare_inventory
        return compare_inventory(candidate,inventory,graph,bundle)
    raise ValueError('source_audit_comparison_version_unknown')


def configuration(parent, *, repair_parent=None, local_context=False, **kwargs):
    from .worker import configuration as worker_config
    config=worker_config(workflow='inventory_v9',**kwargs)
    if config['provider']!='codex': raise ValueError('source_audit_provider_not_evaluated')
    config.update(workflow='source_mention_audit_v1', output_format=audit.AUDIT_VERSION,
        baseline_run_id=parent['run_id'], schema_sha256=digest(audit.output_schema()),
        prompt_version=audit.PROMPT_VERSION,prompt_sha256=audit.PROMPT_HASH,
        max_inventory_repairs=0,max_extraction_repairs=0,max_evidence_patches=0,
        max_numeric_mentions=600,baseline_in_model_input=False)
    if repair_parent is not None:
        if (repair_parent['receipt'].get('repair_parent') is not None
                or repair_parent['receipt']['config']['baseline_run_id']!=parent['run_id']):
            raise ValueError('source_audit_repair_ancestry_invalid')
        config.update(workflow='source_mention_audit_repair_v1',repair_run_id=repair_parent['run_id'],
            prompt_version=audit.REPAIR_PROMPT_VERSION,prompt_sha256=audit.REPAIR_PROMPT_HASH)
        local_context=local_context or repair_parent['receipt']['config'].get('source_context_format') is not None
    if local_context:
        from . import source_local_audit as local
        config.update(source_context_format=local.VERSION,workflow='source_local_audit_repair_v1' if repair_parent else 'source_local_audit_v1',
            prompt_version=local.REPAIR_PROMPT_VERSION if repair_parent else local.PROMPT_VERSION,
            prompt_sha256=local.REPAIR_PROMPT_HASH if repair_parent else local.PROMPT_HASH,
            audit_comparison_version='materials-source-audit-comparison/2')
    return config


def _check_repair(parent,bundle,repair_parent):
    if (digest(repair_parent['receipt'])!=repair_parent['run_id']
            or repair_parent['receipt'].get('repair_parent') is not None
            or repair_parent['receipt']['config']['baseline_run_id']!=parent['run_id']):
        raise ValueError('source_audit_repair_parent_binding_invalid')
    _,checked=verify_receipt(repair_parent['receipt'],bundle,repair_parent['raw_output'])
    if checked['valid']:raise ValueError('source_audit_repair_requires_invalid_accounting')


def run_one(store,job_id,parent,bundle,*,provider_override=None,repair_parent=None):
    from .worker import implementation_sources
    graph,inventory=resolve_parent(parent,bundle)
    if repair_parent is not None:_check_repair(parent,bundle,repair_parent)
    job=store.claim(lease_seconds=3900,job_id=job_id)
    if job is None:return None
    directory=store.root/'attempts'/job['id']/job['lease_token']
    config=job['config'];format_=_format(config);started=time.monotonic();usage=Counter();state='failed';error=None
    receipt={'schema':'materials-source-audit-attempt/1','job_id':job['id'],'attempt_id':job['lease_token'],
        'work_id':bundle.work_id,'bundle_sha256':job['bundle_hash'],'config':config,'baseline_parent':parent,
        'baseline_in_model_input':False,'scientific_acceptance':False,'production_writes':False,
        'output_token_limit_enforced_by_provider':False}
    if repair_parent is not None:receipt['repair_parent']=repair_parent
    try:
        expected=configuration(parent,repair_parent=repair_parent,local_context=config.get('source_context_format') is not None,
            **{k:config[k] for k in ['provider','model','reasoning','timeout_seconds','max_input_tokens','max_output_tokens']})
        if expected!=config or job['bundle_hash']!=digest(bundle.model_dump()) or job['work_id']!=bundle.work_id:
            raise ProviderFailure('source_audit_worker_contract_drift')
        if check_admission(bundle):raise ProviderFailure('source_audit_source_not_admitted')
        sources=implementation_sources()
        if digest({n:sha(r) for n,r in sources.items()})!=config['implementation_sha256']:
            raise ProviderFailure('worker_source_changed_during_capture')
        code=store.root/'implementations'/config['implementation_sha256']
        for name,payload in sources.items():
            target=code/name
            if target.exists() and target.read_bytes()!=payload:raise ProviderFailure('implementation_snapshot_corrupt')
            if not target.exists():private_write(target,payload)
        private_write(code/'manifest.json',canonical({'files':{n:sha(r) for n,r in sources.items()},'runtime':config['runtime']}).encode())
        manifest=audit.mention_manifest(bundle);schema=audit.output_schema(bundle);prompt=format_.render(bundle)
        if repair_parent is not None:
            prompt=format_.render_repair(bundle,repair_parent['receipt']['audit'],repair_parent['receipt']['validation'])
        receipt['mention_manifest']=manifest
        if config.get('source_context_format') is not None:
            context=format_.local_context(bundle);receipt['local_context_sha256']=digest(context)
            private_write(directory/'local-context.json',canonical(context).encode())
        tokens=len(tiktoken.get_encoding('cl100k_base').encode(prompt+canonical(schema),disallowed_special=()))
        stage={'name':'blind_source_audit','prompt_sha256':sha(prompt.encode()),'schema_sha256':digest(schema),
               'input_count':{'tokens':tokens,'tokenizer':'cl100k_base','provider_exact':False}}
        receipt['stages']=[stage]
        for filename,payload in [('input.txt',prompt.encode()),('schema.json',canonical(schema).encode()),
                                 ('mention-manifest.json',canonical(manifest).encode())]:private_write(directory/filename,payload)
        if len(manifest['mentions'])>config['max_numeric_mentions']:raise ProviderFailure('source_audit_mention_budget_exceeded')
        if tokens>config['max_input_tokens']:raise ProviderFailure('stage_input_budget_exceeded')
        remaining=config['timeout_seconds']-(time.monotonic()-started)
        if remaining<1:raise ProviderFailure('run_wall_budget_exhausted')
        stage['timeout_seconds']=remaining
        response=(provider_override or CodexProvider()).extract(prompt,schema,dict(config,timeout_seconds=remaining),directory/'source-audit')
        usage.update(response.usage);private_write(directory/'output.json',response.text.encode())
        receipt['raw_output_sha256']=sha(response.text.encode())
        stage.update(provider=response.provider,model=response.model,response_id=response.response_id,
                     usage=response.usage,elapsed_seconds=response.elapsed_seconds,raw_output_sha256=receipt['raw_output_sha256'])
        candidate=audit.MentionAudit.model_validate_json(response.text)
        checked=audit.validate_audit(candidate,bundle)
        receipt.update(audit=candidate.model_dump(),validation=checked)
        if checked['valid']:
            comparison=_compare(config,candidate,inventory,graph,bundle);receipt['comparison']=comparison
            pending=any(comparison[k] for k in ['unrepresented_result_mentions','classification_disagreements','qualitative_items_requiring_semantic_comparison'])
            state='quarantined' if pending else 'succeeded'
            if pending:error='source_audit_disagreement_requires_review'
        else:state,error='quarantined','source_audit_accounting_invalid'
    except ProviderFailure as failure:
        error=failure.code;usage.update(failure.usage)
    except ValidationError as failure:
        state,error='quarantined','source_audit_schema_invalid'
        receipt['schema_errors']=[{'location':list(e['loc']),'type':e['type']} for e in failure.errors(include_input=False,include_context=False)]
    except (ValueError,KeyError,OSError) as failure:
        state,error='quarantined','source_audit_'+type(failure).__name__
    receipt.update(state=state,error_code=error,retryable=False,usage=usage,elapsed_seconds=time.monotonic()-started)
    path=directory/'receipt.json';raw=canonical(receipt).encode();private_write(path,raw)
    store.finish(job,state=state,receipt_path=str(path.relative_to(store.root)),receipt_hash=sha(raw),
                 usage=usage,duration_seconds=receipt['elapsed_seconds'],error_code=error,retryable=False)
    return {k:receipt[k] for k in ['job_id','state','error_code','usage','elapsed_seconds']}


def verify_receipt(receipt,bundle,raw_output):
    if (receipt['bundle_sha256']!=digest(bundle.model_dump()) or receipt['work_id']!=bundle.work_id
            or receipt['raw_output_sha256']!=sha(raw_output.encode())
            or receipt['config']['baseline_run_id']!=receipt['baseline_parent']['run_id']
            or receipt['baseline_in_model_input'] is not False):raise ValueError('source_audit_receipt_binding_mismatch')
    graph,inventory=resolve_parent(receipt['baseline_parent'],bundle)
    manifest=audit.mention_manifest(bundle)
    if manifest!=receipt['mention_manifest']:raise ValueError('source_audit_manifest_reconstruction_mismatch')
    stage=receipt['stages'][0]
    format_=_format(receipt['config']);prompt=format_.render(bundle)
    if receipt['config'].get('source_context_format') is not None:
        if receipt.get('local_context_sha256')!=digest(format_.local_context(bundle)):
            raise ValueError('source_audit_local_context_reconstruction_mismatch')
    if receipt.get('repair_parent') is not None:
        previous=receipt['repair_parent'];_check_repair(receipt['baseline_parent'],bundle,previous)
        if receipt['config'].get('repair_run_id')!=previous['run_id']:raise ValueError('source_audit_repair_config_mismatch')
        prompt=format_.render_repair(bundle,previous['receipt']['audit'],previous['receipt']['validation'])
    if stage['prompt_sha256']!=sha(prompt.encode()) or stage['schema_sha256']!=digest(audit.output_schema(bundle)):
        raise ValueError('source_audit_input_reconstruction_mismatch')
    candidate=audit.MentionAudit.model_validate_json(raw_output);checked=audit.validate_audit(candidate,bundle)
    if candidate.model_dump()!=receipt['audit'] or checked!=receipt['validation']:
        raise ValueError('source_audit_validation_reconstruction_mismatch')
    if checked['valid']:
        comparison=_compare(receipt['config'],candidate,inventory,graph,bundle)
        if comparison!=receipt.get('comparison'):raise ValueError('source_audit_comparison_reconstruction_mismatch')
        pending=any(comparison[k] for k in ['unrepresented_result_mentions','classification_disagreements','qualitative_items_requiring_semantic_comparison'])
        expected='quarantined' if pending else 'succeeded'
    else:expected='quarantined'
    if receipt['state']!=expected or receipt['scientific_acceptance'] is not False:
        raise ValueError('source_audit_state_reconstruction_mismatch')
    return candidate,checked
