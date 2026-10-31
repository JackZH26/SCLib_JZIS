"""Durable, bounded source selection; all outputs remain review-only candidates."""
from pathlib import Path
from typing import Literal
import json,time
from pydantic import Field
import tiktoken
from .contract import StrictModel,canonical,digest
from .evidence import source_catalog
from .sources import load_bundle,save_bundle,private_write,check_admission,sha
from .providers import CodexProvider,ResponsesProvider,ProviderFailure
from . import compiled_fields as fields

WORKFLOW='compiled_source_fields_v1'
OUTPUT_FORMAT='materials-compiled-field-worker/1'


class Assertion(StrictModel):
    id:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
    source_span_ids:list[str]=Field(min_length=1)
    context_span_ids:list[str]
    prior_assertion:dict
    parent_entry_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')


class Request(StrictModel):
    schema_version:Literal['materials-compiled-field-request/1']
    work_id:str
    bundle_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    parent_dataset_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    assertions:list[Assertion]=Field(min_length=1,max_length=64)


def prepare(bundle,request):
    request=Request.model_validate(request)
    if request.work_id!=bundle.work_id or request.bundle_sha256!=digest(bundle.model_dump()):
        raise ValueError('compiled_request_source_mismatch')
    ids=[a.id for a in request.assertions]
    if len(ids)!=len(set(ids)):raise ValueError('compiled_request_duplicate_assertion')
    catalog=source_catalog(bundle);packets=[]
    for a in request.assertions:
        for refs in [a.source_span_ids,a.context_span_ids]:
            if len(refs)!=len(set(refs)) or any(s not in catalog['spans'] for s in refs):
                raise ValueError('compiled_request_unknown_or_duplicate_span')
        if a.prior_assertion.get('id')!=a.id:raise ValueError('compiled_request_assertion_identity')
        previous=dict(prior_assertion=dict(a.prior_assertion,context_span_ids=a.context_span_ids),
            allowed_raw_occurrence_spans=a.source_span_ids,parent_entry_sha256=a.parent_entry_sha256)
        packets.append(dict(assertion_id=a.id,prior_field_record=previous))
    selected=fields.local_catalog(bundle,packets)
    return request,packets,selected


def configuration(bundle,request,**kwargs):
    from .worker import configuration as base_configuration
    request,packets,catalog=prepare(bundle,request)
    config=base_configuration(workflow='inventory_v12',**kwargs)
    prompt=fields.render(bundle,catalog);schema=fields.output_schema(catalog)
    config.update(workflow=WORKFLOW,output_format=OUTPUT_FORMAT,request_sha256=digest(request.model_dump()),
        source_selection_policy=fields.POLICY,inventory_link_projection_version=None,inventory_schema_sha256=None,
        max_inventory_repairs=0,max_extraction_repairs=0,max_evidence_patches=0,
        schema_sha256=digest(schema),prompt_version=fields.POLICY,prompt_sha256=sha(prompt.encode()))
    return config


def enqueue(store,bundle,request,**kwargs):
    request=Request.model_validate(request);config=configuration(bundle,request,**kwargs)
    bundle_hash,_=save_bundle(store.root,bundle)
    path=store.root/'compiled-requests'/f'{config["request_sha256"]}.json';raw=canonical(request.model_dump()).encode()
    if path.exists() and path.read_bytes()!=raw:raise ValueError('compiled_request_snapshot_corrupt')
    if not path.exists():private_write(path,raw)
    return store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=config,max_attempts=1)


def replay(raw,bundle,request):
    request,packets,catalog=prepare(bundle,request)
    model=fields.parse_output(raw,catalog)
    return fields.project_and_validate(model,bundle,catalog,packets)


def run_claimed(store,job,*,provider_override=None,max_seconds=None):
    from .worker import implementation_sources
    config=job['config'];directory=store.root/'attempts'/job['id']/job['lease_token'];directory.mkdir(parents=True,mode=0o700)
    started=time.monotonic();usage={};state='failed';error=None;dependencies={}
    receipt=dict(schema=OUTPUT_FORMAT,job_id=job['id'],attempt_id=job['lease_token'],work_id=job['work_id'],
        config=config,bundle_sha256=job['bundle_hash'],provider_calls=0,automatic_retries=0,
        scientific_acceptance=False,qualified_ml_rows=0,canonical_writes=False,
        output_token_limit_enforced_by_provider=config['provider']=='responses')
    try:
        bundle_path=store.root/'bundles'/f'{job["bundle_hash"]}.json'
        request_path=store.root/'compiled-requests'/f'{config["request_sha256"]}.json'
        dependencies={str(p):sha(p.read_bytes()) for p in [bundle_path,request_path]}
        bundle=load_bundle(bundle_path);request=json.loads(request_path.read_bytes())
        if digest(bundle.model_dump())!=job['bundle_hash'] or bundle.work_id!=job['work_id']:
            raise ProviderFailure('compiled_job_source_mismatch')
        expected=configuration(bundle,request,**{k:config[k] for k in ['provider','model','reasoning','timeout_seconds','max_input_tokens','max_output_tokens']})
        if expected!=config:raise ProviderFailure('compiled_worker_contract_drift')
        if check_admission(bundle):
            state='blocked';raise ProviderFailure('compiled_source_not_admitted')
        sources=implementation_sources();code=store.root/'implementations'/config['implementation_sha256']
        if digest({n:sha(b) for n,b in sources.items()})!=config['implementation_sha256']:
            raise ProviderFailure('compiled_implementation_changed_during_capture')
        for name,raw in sources.items():
            target=code/name
            if target.exists() and target.read_bytes()!=raw:raise ProviderFailure('compiled_implementation_snapshot_corrupt')
            if not target.exists():private_write(target,raw)
        private_write(directory/'implementation-manifest.json',canonical({n:sha(b) for n,b in sources.items()}).encode())
        parsed,packets,catalog=prepare(bundle,request)
        prompt=fields.render(bundle,catalog);schema=fields.output_schema(catalog)
        private_write(directory/'request.json',canonical(request).encode());private_write(directory/'catalog.json',canonical(catalog).encode())
        private_write(directory/'input.txt',prompt.encode());private_write(directory/'schema.json',canonical(schema).encode())
        tokens=len(tiktoken.get_encoding('cl100k_base').encode(prompt+canonical(schema),disallowed_special=()))
        receipt['input_count']=dict(tokens=tokens,tokenizer='cl100k_base',provider_exact=False)
        if tokens>config['max_input_tokens']:
            state='blocked';raise ProviderFailure('compiled_input_budget_exceeded')
        budget=min(config['timeout_seconds'],max_seconds) if max_seconds is not None else config['timeout_seconds']
        remaining=budget-(time.monotonic()-started)
        if remaining<1:raise ProviderFailure('compiled_wall_budget_exhausted')
        provider=provider_override or (CodexProvider() if config['provider']=='codex' else ResponsesProvider())
        receipt['provider_calls']=1
        response=provider.extract(prompt,schema,dict(config,timeout_seconds=remaining),directory/'provider')
        usage=response.usage;private_write(directory/'output.json',response.text.encode())
        receipt['raw_output_sha256']=sha(response.text.encode())
        receipt['provider']=dict(name=response.provider,model=response.model,response_id=response.response_id,elapsed_seconds=response.elapsed_seconds)
        projection,validation=replay(response.text,bundle,request)
        private_write(directory/'compiled-fields.json',canonical(projection).encode());private_write(directory/'validation.json',canonical(validation).encode())
        receipt.update(projection_sha256=digest(projection),validation_sha256=digest(validation),
            raw_output_sha256=sha(response.text.encode()),assertions_accounted=validation['assertions_accounted'],
            technical_issues=validation['issues'],explicit_hold_count=validation['explicit_hold_count'],
            execution_status='compiled_candidates_retained_for_review')
        state='quarantined';error='compiled_fields_require_graph_and_scientific_review'
    except ProviderFailure as exc:
        error=exc.code;usage=exc.usage or usage
    except (ValueError,KeyError,IndexError,TypeError,OSError) as exc:
        error='compiled_output_or_request_invalid'
        receipt['failure']=dict(type=type(exc).__name__,detail=str(exc))
    finally:
        current=digest({n:sha(b) for n,b in implementation_sources().items()})
        receipt['implementation_unchanged']=current==config['implementation_sha256']
        if not receipt['implementation_unchanged']:state='quarantined';error='compiled_implementation_drift'
        drift=[p for p,h in dependencies.items() if not Path(p).exists() or sha(Path(p).read_bytes())!=h]
        receipt['source_request_unchanged']=not drift
        if drift:state='quarantined';error='compiled_source_request_drift'
        receipt.update(state=state,error_code=error,usage=usage,duration_seconds=time.monotonic()-started,terminal=True)
        raw=canonical(receipt).encode();path=directory/'receipt.json';private_write(path,raw)
        store.finish(job,state=state,receipt_path=str(path),receipt_hash=sha(raw),usage=usage,
            duration_seconds=receipt['duration_seconds'],error_code=error,retryable=False)
    return dict(job_id=job['id'],state=state,error_code=error,receipt_path=str(path),scientific_acceptance=False)
