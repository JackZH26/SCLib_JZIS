"""Source-bound field revisions of staged graphs; old transcripts stay immutable.

Requests constrain exact fields, not replacement answers. Appended original
context preserves every existing source alias. This is a new model proposal,
never an independent read, a scientific decision or a canonical promotion.
"""
from copy import deepcopy
import json
import re
from types import SimpleNamespace
from typing import Annotated, Literal, get_args, get_origin

from pydantic import BaseModel, Field, JsonValue, TypeAdapter

from .contract import StrictModel, Quantity, canonical, digest
from .quantities import unmapped_quantity_source_issues
from .document_context import build_inventory
from .evidence import source_catalog, selected_quotes
from .inventory import Inventory, strict_schema, source_text, validate_inventory
from .sources import Bundle, Block, sha, verify_bundle
from .wire_v10 import validate_coverage as graph_coverage, REGISTRY_INSTRUCTIONS, DETECTION_INSTRUCTIONS
from . import quantity_name_witness as name_witness
from . import quantity_raw_witness as raw_witness
from . import direction_witness
from . import observation_holds
from . import owner_additions

VERSION = 'materials-staged-field-revision/1'
REQUEST_VERSION = 'materials-staged-field-request/1'
PROMPT_VERSION = 'materials-staged-field-prompt/1.10.0'
COVERAGE_POLICY = 'original_inventory_scope_v1'
BINDING_POLICY = 'literal_owner_v1'
WITNESS_POLICY = 'literal_witness_choice_v2'
FAILURE_POLICY = 'independent_evidence_v1'
QUANTITY_RAW_POLICY = raw_witness.POLICY
STALE_EVIDENCE_POLICY = 'missing_field_only_v1'


class ContextSelection(StrictModel):
    source_block_id: str
    start_char: int
    end_char: int
    purpose: str = Field(min_length=1)
    selection_basis: str = Field(min_length=1)


class SourceContext(StrictModel):
    original_bundle: Bundle
    selections: list[ContextSelection] = Field(min_length=1, max_length=8)


class FieldTarget(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    path: str = Field(pattern=r'^/')
    expected_value_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    operation: Literal['replace', 'remove', 'bind_evidence', 'hold_observation', 'append_owner']
    concern: str = Field(min_length=1, max_length=3000)
    source_span_ids: list[str] = Field(min_length=1, max_length=32)


class FieldRequest(StrictModel):
    schema_version: Literal['materials-staged-field-request/1']
    parent_run_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    author_kind: Literal['assistant', 'human']
    fields: list[FieldTarget] = Field(min_length=1, max_length=32)
    source_context: SourceContext | None
    # Earlier model revisions remain review holds, even after a model says fixed.
    prior_revision_run_ids: list[str]


class Selection(StrictModel):
    action: Literal['replace', 'remove', 'bind_evidence', 'hold_observation', 'append_owner', 'unchanged_supported', 'unresolved']
    value: JsonValue
    span_ids: list[str] = Field(max_length=32)
    reason: str = Field(min_length=1, max_length=3000)
    # Optional for immutable historical responses; current schemas constrain
    # each literal's witness independently from additional context spans.
    literal_witnesses: dict[str,str | list[str]] | None = None
    quantity_name_witness: str | None = None


class NativeEdits(StrictModel):
    schema_version: Literal['materials-staged-field-revision/1']
    work_id: str
    parent_run_id: str
    base_graph_sha256: str
    request_sha256: str
    selections: dict[str, Selection]
    read_context_block_ids: list[str]


def pointer(data, path):
    parts = path.strip('/').split('/')
    if not path.startswith('/') or any(not p or '~' in p for p in parts):
        raise ValueError('staged_field_pointer_invalid')
    for part in parts:
        data = data[int(part)] if isinstance(data, list) and part.isdecimal() else data[part]
    return data


def source_bundle(parent, context):
    """Append only exact original slices; prove the existing source prefix exact."""
    base = Bundle.model_validate(parent['bundle']); verify_bundle(base)
    if context is None: return base, {'schema':'materials-revision-context/1', 'added_blocks':[],
        'base_bundle_sha256':digest(base.model_dump()), 'revised_bundle_sha256':digest(base.model_dump())}
    original = context.original_bundle
    if original.work_id != base.work_id: raise ValueError('staged_field_context_work_mismatch')
    inventory = build_inventory(original, [s.model_dump() for s in context.selections])
    docs = {d.id:d.model_dump(exclude={'coverage','parser'}) for d in original.documents}
    if any(docs.get(d.id) != d.model_dump(exclude={'coverage','parser'}) for d in base.documents):
        raise ValueError('staged_field_context_document_mismatch')
    if sum(s.end_char-s.start_char for s in context.selections) > 16000:
        raise ValueError('staged_field_context_budget_exceeded')
    # Document bytes/version alone do not prove the base window's text is genuine.
    originals = {(b.document_id,b.locator):b for b in original.blocks}
    for b in base.blocks:
        match = re.fullmatch(r'[^:]+:(.+):chars\[(\d+):(\d+)\]', b.locator)
        if match: loc,a,z=match[1],int(match[2]),int(match[3])
        elif b.locator.startswith('context-identity:'): loc,a,z=b.locator[17:],0,len(b.text)
        else: loc,a,z=b.locator,0,len(b.text)
        source=originals.get((b.document_id,loc))
        if source is None or source.text[a:z] != b.text:
            raise ValueError('staged_field_context_original_bytes_mismatch')
    revised=base.model_copy(deep=True); added=[]; sources={b.id:b for b in original.blocks}
    key=digest(inventory)[:16]
    for n,selection in enumerate(context.selections):
        source=sources[selection.source_block_id]; text=source.text[selection.start_char:selection.end_char]
        block=Block(id=f'{source.id}:revision:{key}:{n}',document_id=source.document_id,
            ordinal=max(b.ordinal for b in revised.blocks)+1,
            locator=f'revision-context:{source.locator}:chars[{selection.start_char}:{selection.end_char}]',
            text=text,sha256=sha(text.encode()))
        revised.blocks.append(block)
        added.append({'block_id':block.id,'alias':f'B{len(revised.blocks)}',
            'original_block_id':source.id,'original_block_sha256':source.sha256,
            'start_char':selection.start_char,'end_char':selection.end_char,'text_sha256':block.sha256})
    revised.acquisition_notes.append('STAGED_REVISION_CONTEXT '+canonical({'inventory':inventory,'added_blocks':added}))
    verify_bundle(revised)
    old,new=source_catalog(base),source_catalog(revised)
    if any(new[k].get(a)!=v for k in ('blocks','spans') for a,v in old[k].items()):
        raise ValueError('staged_field_context_changes_old_alias')
    return revised,{'schema':'materials-revision-context/1','base_bundle_sha256':digest(base.model_dump()),
        'revised_bundle_sha256':digest(revised.model_dump()),'original_bundle_sha256':digest(original.model_dump()),
        'inventory':inventory,'added_blocks':added,'existing_source_aliases_unchanged':True}


def resolve_parent(parent, *, depth=0):
    from . import item_worker, item_stages
    if depth>8: raise ValueError('staged_field_ancestry_limit')
    receipt=parent['receipt']; bundle=Bundle.model_validate(parent['bundle'])
    ancestry(parent)
    if (digest(receipt)!=parent['run_id'] or receipt.get('raw_output_sha256')!=sha(parent['raw_output'].encode())
            or receipt['bundle_sha256']!=digest(bundle.model_dump())
            or receipt['state'] not in {'quarantined','succeeded'} or 'extraction' not in receipt):
        raise ValueError('staged_field_parent_binding_mismatch')
    format_=receipt['config']['output_format']; inventory=Inventory.model_validate(receipt['inventory'])
    if format_==VERSION:
        return verify_receipt(receipt,bundle,parent['raw_output'],depth=depth+1)
    if format_ not in {'materials-source-item-transcript/1','materials-source-item-transcript/2','materials-source-item-transcript/3','materials-source-item-transcript/4','materials-source-item-transcript/5'}:
        raise ValueError('staged_field_parent_format_unsupported')
    item_worker.verify_receipt(receipt,bundle,parent['raw_output'])
    replay=item_worker.replay(json.loads(parent['raw_output']),bundle,inventory,receipt['config'])
    ids,_=item_stages.inventory_items(inventory,replay['catalog'])
    assemble=item_stages.assemble;options={}
    if format_ in {'materials-source-item-transcript/3','materials-source-item-transcript/4','materials-source-item-transcript/5'}:
        from .item_flow_v2 import interfaces, assembly_options
        _, _, assemble, _ = interfaces(receipt['config'])
        options=assembly_options(replay,receipt['config'])
    graph,_,proof=assemble(bundle,inventory,replay['catalog'],replay['decisions'],replay['links'],
        missing_item_ids=[x.id for x in ids if x.id not in replay['decisions']],stage_failures=receipt['staged_errors'],**options)
    if proof!=receipt['staged_assembly'] or graph.expand(bundle).model_dump()!=receipt['extraction']:
        raise ValueError('staged_field_parent_reconstruction_mismatch')
    return graph,inventory


def verify_parent(parent,bundle):
    graph,inventory=resolve_parent(parent)
    if graph.work_id!=bundle.work_id: raise ValueError('staged_field_work_mismatch')
    return inventory


def ancestry(parent):
    out=[]
    for _ in range(9):
        if parent['receipt']['config']['output_format']!=VERSION: return out
        out.append(parent['run_id']);parent=parent['receipt']['revision_parent']
    raise ValueError('staged_field_ancestry_limit')


def field_type(graph,path):
    value=graph
    parts=path.strip('/').split('/'); annotation=None
    for p in parts:
        if isinstance(value,BaseModel): annotation=type(value).model_fields[p].rebuild_annotation();value=getattr(value,p)
        elif isinstance(value,list) and p.isdecimal():
            if get_origin(annotation) is Annotated: annotation=get_args(annotation)[0]
            annotation=get_args(annotation)[0];value=value[int(p)]
        else: raise ValueError('staged_field_non_model_pointer')
    match=re.fullmatch(r'/observations/(\d+)/result/quantity_name_raw',path)
    if match and graph.observations[int(match[1])].result.quantity_kind=='unmapped':
        return Annotated[str,Field(min_length=1,pattern=r'\S')]
    return annotation


def validate_request(request,parent,bundle=None):
    request=FieldRequest.model_validate(request);graph,inventory=resolve_parent(parent)
    expected,proof=source_bundle(parent,request.source_context)
    if (request.parent_run_id!=parent['run_id'] or request.prior_revision_run_ids!=ancestry(parent)
            or (bundle is not None and bundle!=expected)):
        raise ValueError('staged_field_request_binding_mismatch')
    paths=[t.path for t in request.fields]
    if len({t.id for t in request.fields})!=len(paths) or len(set(paths))!=len(paths):
        raise ValueError('staged_field_duplicate_target')
    if any(a!=b and b.startswith(a+'/') for a in paths for b in paths):
        raise ValueError('staged_field_overlapping_targets')
    for t in request.fields:
        parts=t.path.strip('/').split('/')
        if parts[0] not in {'samples','states','protocols','observations','context_dispositions','condition_supports'}:
            raise ValueError('staged_field_target_scope_invalid')
        if t.operation=='append_owner':
            owner_additions.spec(graph,parent['run_id'],t)
        elif t.operation=='hold_observation':
            observation_holds.target(graph,inventory,expected,t.path,t.source_span_ids)
        elif t.operation=='remove':
            stale=stale_evidence_target(graph.model_dump(),t.path)
            if not stale and not re.fullmatch(r'/(?:states/\d+/conditions/\d+|protocols/\d+/parameters/\d+|condition_supports/\d+)',t.path):
                raise ValueError('staged_field_removal_scope_invalid')
        elif t.operation=='bind_evidence':
            if (len(parts)<3 or any(x in {'id','context_id','inventory_item_ids','evidence'} for x in parts[2:])
                    or (parts[0]=='observations' and len(parts)<4)
                    or t.path.endswith(('/conditions','/parameters','/qualifiers'))
                    or evidence_owner(graph.model_dump(),t.path)[0] is None
                    or pointer(graph.model_dump(),t.path) in (None,[],{})):
                raise ValueError('staged_field_evidence_target_invalid')
        elif (not re.fullmatch(r'/context_dispositions/\d+',t.path) and
              (len(parts)<3 or any(x in {'id','context_id','inventory_item_ids','evidence'} for x in parts[2:])
              or (parts[0]=='observations' and len(parts)==3 and parts[2] in {'result','definition'})
              or re.fullmatch(r'/states/\d+/conditions/\d+',t.path)
              or t.path.endswith(('/conditions','/parameters')))):
            raise ValueError('staged_field_replacement_scope_invalid')
        if digest(pointer(graph.model_dump(),t.path))!=t.expected_value_sha256:
            raise ValueError('staged_field_precondition_mismatch')
        field_type(graph,t.path);selected_quotes(source_catalog(expected),t.source_span_ids)
    return request


def stale_evidence_target(data,path):
    """A missing field may lose its pointer, never an existing scientific fact.

    Removal is explicit, hash-bound and replayed. Null is an existing field.
    Whole references are removable only when every contained pointer is stale;
    a leaf removal must leave a nonempty reference. Array suffix rules still
    prevent retargeting other requested indices.
    """
    match=re.fullmatch(r'(/(?:samples|states|protocols)/\d+|/observations/\d+/(?:result|definition))'
                       r'/evidence/(\d+)(?:/fields/(\d+))?',path)
    if not match:return None
    owner=pointer(data,match[1]);ref=owner['evidence'][int(match[2])]
    fields=ref['fields'] if match[3] is None else [ref['fields'][int(match[3])]]
    if match[3] is not None and len(ref['fields'])==1:
        raise ValueError('staged_field_stale_leaf_would_empty_reference')
    for field in fields:
        if not re.fullmatch(r'/(?:[A-Za-z_][A-Za-z_0-9]*|0|[1-9][0-9]*)(?:/(?:[A-Za-z_][A-Za-z_0-9]*|0|[1-9][0-9]*))*',field):
            raise ValueError('staged_field_stale_pointer_invalid')
        try:pointer(owner,field)
        except (KeyError,IndexError):pass
        else:raise ValueError('staged_field_evidence_still_addresses_field')
    return dict(policy=STALE_EVIDENCE_POLICY,owner_path=match[1],missing_fields=fields,
                original_reference=deepcopy(ref),scientific_payload_unchanged=True)


def evidence_owner(data,path):
    parts=path.strip('/').split('/')
    if parts[0]=='context_dispositions': return None,None
    if parts[0]=='observations':
        if len(parts)>3 and parts[2] in {'result','definition'}:
            return pointer(data,'/'+ '/'.join(parts[:3])),'/'+ '/'.join(parts[3:])
        return pointer(data,'/'+ '/'.join(parts[:2]))['result'],'/'+ '/'.join(parts[2:])
    if len(parts)>2: return pointer(data,'/'+ '/'.join(parts[:2])),'/'+ '/'.join(parts[2:])
    return None,None


def literal_claims(value,path):
    """Literal prose/labels, excluding numeric raw syntax handled by its parser."""
    if isinstance(value,dict):
        if 'relation' in value and 'status' in value:return {}
        return {p:v for key,child in value.items() for p,v in literal_claims(child,path+'/'+key).items()}
    if isinstance(value,list):
        return {p:v for i,child in enumerate(value) for p,v in literal_claims(child,path+'/'+str(i)).items()}
    if isinstance(value,str) and (path.endswith('_raw') or path.endswith('/raw')):return {path:value}
    return {}


def literal_support(graph,path,bundle):
    catalog=source_catalog(bundle)
    claims=literal_claims(pointer(graph.model_dump(),path),path)
    result={}
    for p,value in claims.items():
        sets=[]
        if value.strip():
            pattern=re.compile(r'\s+'.join(re.escape(word) for word in value.split()))
            for block in bundle.blocks:
                for match in pattern.finditer(block.text):
                    group=[alias for alias,span in catalog['spans'].items() if span['block_id']==block.id
                           and span['start_char']<match.end() and span['end_char']>match.start()]
                    if group and group not in sets:sets.append(group)
        result[p]={'value':value,'supporting_span_sets':sets,
                   'witness_choices':{f'W{i+1}':group for i,group in enumerate(sets)},
                   'supporting_span_ids':list(dict.fromkeys(alias for group in sets for alias in group))}
    return result


def _apply(parent,bundle,edits,request,*,field_evidence_policy='legacy_all_replacements',evidence_binding_policy=None,
           literal_witness_policy=None,binding_failure_policy=None,quantity_name_policy=None,quantity_raw_policy=None,
           field_source_policy=None):
    if field_evidence_policy not in {'legacy_all_replacements','non_null_fields_v2'}:
        raise ValueError('staged_field_evidence_policy_unknown')
    if evidence_binding_policy not in {None,BINDING_POLICY}:
        raise ValueError('staged_field_binding_policy_unknown')
    if literal_witness_policy not in {None,'required_literal_witness_v1',WITNESS_POLICY} or binding_failure_policy not in {None,FAILURE_POLICY}:
        raise ValueError('staged_field_binding_extension_policy_unknown')
    if quantity_name_policy not in {None,name_witness.LEGACY_POLICY,name_witness.POLICY}:
        raise ValueError('staged_field_quantity_name_policy_unknown')
    if quantity_raw_policy not in {None,raw_witness.LEGACY_POLICY,QUANTITY_RAW_POLICY}:
        raise ValueError('staged_field_quantity_raw_policy_unknown')
    if field_source_policy not in {None,direction_witness.POLICY}:
        raise ValueError('staged_field_source_policy_unknown')
    before,inventory=resolve_parent(parent);data=deepcopy(before.model_dump())
    if (edits.work_id!=before.work_id or edits.parent_run_id!=parent['run_id']
            or edits.base_graph_sha256!=digest(data) or edits.request_sha256!=digest(request.model_dump())
            or set(edits.selections)!={t.id for t in request.fields}):
        raise ValueError('staged_field_response_binding_mismatch')
    _,context_proof=source_bundle(parent,request.source_context)
    added={b['alias'] for b in context_proof['added_blocks']}
    if len(set(edits.read_context_block_ids))!=len(edits.read_context_block_ids) or not set(edits.read_context_block_ids)<=added:
        raise ValueError('staged_field_context_read_scope_invalid')
    removals={t.path for t in request.fields if edits.selections[t.id].action=='remove'}
    for path in removals:
        prefix,index=path.rsplit('/',1);array=pointer(data,prefix)
        if any(prefix+'/'+str(i) not in removals for i in range(int(index),len(array))):
            raise ValueError('staged_field_removal_requires_suffix_no_index_retargeting')
    changes=[];catalog=source_catalog(bundle);rejected=[];holds=[];owners=[]
    independent=(binding_failure_policy==FAILURE_POLICY and all(t.operation=='bind_evidence' for t in request.fields))
    for t in request.fields:
        s=edits.selections[t.id];old=pointer(before.model_dump(),t.path)
        stale=stale_evidence_target(before.model_dump(),t.path) if t.operation=='remove' else None
        if s.action in {'replace','remove','bind_evidence','hold_observation','append_owner'} and s.action!=t.operation:
            raise ValueError('staged_field_operation_not_requested')
        if t.operation=='append_owner' and s.action not in {'append_owner','unresolved'}:
            raise ValueError('staged_owner_addition_decision_invalid')
        if s.action not in {'replace','hold_observation','append_owner'} and s.value is not None:
            raise ValueError('staged_field_nonreplacement_has_value')
        if s.action!='bind_evidence' and s.literal_witnesses is not None:
            raise ValueError('staged_field_witnesses_on_nonbinding_decision')
        if evidence_binding_policy and t.operation=='bind_evidence' and s.action=='unchanged_supported':
            raise ValueError('staged_field_binding_requires_explicit_decision')
        spans=list(s.span_ids);errors=[];replacement=s.value
        direction=direction_witness.context(t.path,bundle,t.source_span_ids) if field_source_policy else None
        direction_choice=None
        if direction and s.action=='replace':
            if not isinstance(s.value,dict) or set(s.value)!={'source_choice'} or not isinstance(s.value['source_choice'],str):
                raise ValueError('staged_field_direction_source_choice_invalid')
            direction_choice=direction['choices'].get(s.value['source_choice'])
            if direction_choice is None:raise ValueError('staged_field_direction_source_choice_invalid')
            replacement=direction_choice['raw']
            spans=list(dict.fromkeys(spans+direction_choice['source_span_ids']))
        if direction and s.action=='unchanged_supported':
            raise ValueError('staged_field_direction_requires_source_choice')
        raw_context=raw_witness.context(before,t.path,bundle) if quantity_raw_policy==QUANTITY_RAW_POLICY else None
        raw_choice=None
        if raw_context and s.action=='replace':
            if not isinstance(s.value,dict) or set(s.value)!={'source_choice'} or not isinstance(s.value['source_choice'],str):
                raise ValueError('staged_field_quantity_raw_source_choice_invalid')
            raw_choice=raw_context['choices'].get(s.value['source_choice'])
            if raw_choice is None:raise ValueError('staged_field_quantity_raw_source_choice_invalid')
            replacement=raw_choice['raw']
            spans=list(dict.fromkeys(spans+raw_choice['source_span_ids']))
        if raw_context and s.action=='unchanged_supported':
            raise ValueError('staged_field_quantity_raw_requires_source_choice')
        name_context=name_witness.context(before,t.path,bundle,quantity_name_policy) if quantity_name_policy else None
        if s.quantity_name_witness is not None and not (name_context and s.action in {'replace','unchanged_supported'}):
            raise ValueError('staged_field_unexpected_quantity_name_witness')
        if name_context and s.action in {'replace','unchanged_supported'}:
            candidate=name_context['choices'].get(s.quantity_name_witness)
            if candidate is None or candidate['name']!=(s.value if s.action=='replace' else old):
                raise ValueError('staged_field_quantity_name_assignment_mismatch')
            spans=list(dict.fromkeys(spans+candidate['source_span_ids']))
        if s.action=='bind_evidence':
            claims=literal_claims(old,t.path)
            if literal_witness_policy and (s.literal_witnesses is None or set(s.literal_witnesses)!=set(claims)):
                errors.append('staged_field_literal_witnesses_incomplete')
            if s.literal_witnesses is not None:
                support=literal_support(before,t.path,bundle)
                groups=[];invalid=set(s.literal_witnesses)!=set(claims)
                for path,choice in s.literal_witnesses.items():
                    if path not in support:continue
                    group=(support[path]['witness_choices'].get(choice) if isinstance(choice,str) else
                           choice if literal_witness_policy!=WITNESS_POLICY else None)
                    if group not in support[path]['supporting_span_sets']:invalid=True
                    else:groups.append(group)
                if invalid:
                    errors.append('staged_field_literal_witness_invalid')
                else:spans=list(dict.fromkeys(spans+[a for group in groups for a in group]))
        try:quotes=selected_quotes(catalog,spans) if spans else []
        except ValueError:
            if not (independent and s.action=='bind_evidence'):raise
            errors.append('staged_field_binding_span_invalid');quotes=[]
        if s.action in {'replace','remove','bind_evidence','hold_observation','append_owner','unchanged_supported'} and not quotes:
            errors.append('staged_field_changed_value_has_no_source')
        if evidence_binding_policy and s.action=='bind_evidence' and any(
                not any(' '.join(value.split()) in ' '.join(q['quote'].split()) for q in quotes)
                for value in literal_claims(old,t.path).values()):
            errors.append('staged_field_binding_literal_not_supported')
        if (field_source_policy or s.action=='append_owner') and s.action in {'replace','remove','bind_evidence','hold_observation','append_owner'} and not set(t.source_span_ids)<=set(spans):
            errors.append('staged_field_required_source_span_missing')
        if errors and not (independent and s.action=='bind_evidence'):raise ValueError(errors[0])
        if errors:rejected.append({'target_id':t.id,'path':t.path,'codes':errors})
        raw_guard=None
        if quantity_raw_policy and s.action=='replace' and t.path.endswith('/quantity/raw'):
            frozen=pointer(before.model_dump(),t.path.rsplit('/',1)[0])
            candidate=Quantity.model_validate(dict(frozen,raw=replacement))
            issues=unmapped_quantity_source_issues(candidate,
                [SimpleNamespace(field='/quantity',quote=q['quote']) for q in quotes],'/quantity')
            if issues:raise ValueError('staged_field_quantity_raw_incompatible:'+','.join(issues))
            raw_guard=dict(policy=quantity_raw_policy,frozen_quantity_sha256=digest(frozen),
                candidate_quantity_sha256=digest(candidate.model_dump()),issues=[],
                numeric_semantics_unchanged=True,unit_unchanged=True)
        if s.action=='append_owner':
            value,owner_spec=owner_additions.apply(data,before,parent['run_id'],t,s.value)
            owners.append(owner_spec)
        elif s.action=='hold_observation':
            decision=observation_holds.HoldDecision.model_validate(s.value,strict=True)
            held=observation_holds.target(before,inventory,bundle,t.path,spans)
            held['unextracted_items']=[dict(item_id=i,**decision.model_dump()) for i in old['inventory_item_ids']]
            holds.append(held);value={'unextracted_items':held['unextracted_items']}
        elif s.action=='replace':
            value=TypeAdapter(field_type(before,t.path)).validate_python(replacement,strict=True)
            value=TypeAdapter(field_type(before,t.path)).dump_python(value,mode='json')
            if re.fullmatch(r'/context_dispositions/\d+',t.path) and value['context_id']!=old['context_id']:
                raise ValueError('staged_field_context_identity_changed')
            left,key=t.path.rsplit('/',1);owner=pointer(data,left)
            owner[int(key) if isinstance(owner,list) else key]=value
        else: value=None if s.action=='remove' else old
        if s.action in {'replace','remove','bind_evidence'} and not errors and not stale:
            owner,field=evidence_owner(data,t.path)
            if owner is not None:
                refs=[]
                for ref in owner['evidence']:
                    fields=[f for f in ref['fields'] if f!=field
                            and (s.action=='bind_evidence' or not f.startswith(field+'/'))]
                    if fields:refs.append(dict(ref,fields=fields))
                if s.action=='bind_evidence' or (s.action=='replace' and (value is not None or field_evidence_policy=='legacy_all_replacements')):
                    refs.append({'fields':[field],'span_ids':spans})
                owner['evidence']=refs
        selection=s.model_dump(exclude={key for key in ('literal_witnesses','quantity_name_witness') if getattr(s,key) is None})
        change={'target':t.model_dump(),'selection':selection,'before':old,'after':value,
            'before_sha256':digest(old),'after_sha256':digest(value),'source_quotes':quotes,
            'changed':s.action in {'remove','hold_observation','append_owner'} or (s.action=='replace' and value!=old)}
        if literal_witness_policy or binding_failure_policy:
            change.update(effective_span_ids=spans,binding_errors=errors,
                binding_outcome=('rejected' if errors else 'applied') if s.action=='bind_evidence' else 'not_requested')
        if name_context:change['quantity_name_context']=name_context
        if raw_guard:change['quantity_raw_guard']=raw_guard
        if raw_context:change['quantity_raw_context']=raw_context
        if raw_choice:change['selected_quantity_raw_source']=raw_choice
        if direction:change['direction_source_context']=direction
        if direction_choice:change['selected_direction_source']=direction_choice
        if stale:change['stale_evidence_target']=stale
        if s.action=='hold_observation':change['observation_hold']=held
        if s.action=='append_owner':change['owner_addition']=owner_spec
        changes.append(change)
    for path in sorted(removals,key=lambda p:int(p.rsplit('/',1)[1]),reverse=True):
        prefix,index=path.rsplit('/',1);pointer(data,prefix).pop(int(index))
    hold_audit=observation_holds.apply(data,holds)
    owner_audit=owner_additions.audit_usage(data,owners)
    data['processed_block_ids']+=edits.read_context_block_ids
    after=type(before).model_validate(data)
    # Parsing may check references, but cannot generate or silently normalize fields.
    if after.model_dump()!=data: raise ValueError('staged_field_implicit_field_change')
    audit={'schema':'materials-staged-field-audit/1','parent_run_id':parent['run_id'],
        'base_graph_sha256':digest(before.model_dump()),'revised_graph_sha256':digest(after.model_dump()),
        'request_sha256':digest(request.model_dump()),'changes':changes,'context':context_proof,
        'read_context_block_ids':edits.read_context_block_ids,'prior_revision_run_ids':request.prior_revision_run_ids,
        'unlisted_scientific_fields_unchanged':True,'issues':[{'code':'staged_field_revision_requires_scientific_review','path':'/'}],
        'valid':False,'reviewer_kind':'model','independent_review':False,'scientific_acceptance':False,'ml_training_eligible':False}
    if field_evidence_policy!='legacy_all_replacements':audit['field_evidence_policy']=field_evidence_policy
    if evidence_binding_policy:audit['evidence_binding_policy']=evidence_binding_policy
    if literal_witness_policy:audit['literal_witness_policy']=literal_witness_policy
    if quantity_name_policy:audit['quantity_name_policy']=quantity_name_policy
    if quantity_raw_policy:audit['quantity_raw_policy']=quantity_raw_policy
    if field_source_policy:audit['field_source_policy']=field_source_policy
    if hold_audit:
        audit['observation_holds']=hold_audit
        audit['issues'].append({'code':'staged_observation_hold_requires_scientific_review','path':'/'})
    if owner_audit:
        audit['owner_additions']=owner_audit
        audit['issues'].append({'code':'staged_owner_revision_requires_scientific_review','path':'/'})
    if binding_failure_policy:
        audit.update(binding_failure_policy=binding_failure_policy,independent_evidence_operations=independent,
                     rejected_field_bindings=rejected)
        audit['issues'] += [{'code':'staged_field_evidence_binding_rejected','path':r['path']} for r in rejected]
    return SimpleNamespace(revised_graph=after,audit=audit)


def apply_edits(parent,bundle,edits,*,review_request,field_evidence_policy='non_null_fields_v2',evidence_binding_policy=BINDING_POLICY,
                literal_witness_policy=WITNESS_POLICY,binding_failure_policy=FAILURE_POLICY,quantity_name_policy=name_witness.POLICY,
                quantity_raw_policy=QUANTITY_RAW_POLICY,field_source_policy=None):
    request=validate_request(review_request,parent,bundle)
    return _apply(parent,bundle,edits,request,field_evidence_policy=field_evidence_policy,evidence_binding_policy=evidence_binding_policy,
                  literal_witness_policy=literal_witness_policy,binding_failure_policy=binding_failure_policy,
                  quantity_name_policy=quantity_name_policy,quantity_raw_policy=quantity_raw_policy,field_source_policy=field_source_policy)


def audit_revision(parent,revision,bundle): return revision.audit


def validate_coverage(graph,inventory,bundle,*,parent=None,read_context_block_ids=()):
    """Keep original result discovery separate from later supporting-context reads.

    The graph and its evidence are still checked against the complete current
    bundle. Only first-read inventory checks use that inventory's immutable
    original bundle. No items, reading claims or completeness are manufactured.
    Omitting parent preserves historical combined-scope behavior for replay.
    """
    report=graph_coverage(graph,inventory,bundle)
    if parent is None:return report
    root=parent;history=[]
    while root['receipt']['config']['output_format']==VERSION:
        audit=root['receipt']['revision_audit']
        history.append({'run_id':root['run_id'],'context':audit['context'],
                        'read_context_block_ids':audit['read_context_block_ids']})
        root=root['receipt']['revision_parent']
    original=Bundle.model_validate(root['bundle']);base_catalog=source_catalog(original);catalog=source_catalog(bundle)
    if root['receipt']['inventory']!=inventory.model_dump():raise ValueError('staged_field_inventory_ancestry_mismatch')
    if any(catalog[k].get(a)!=v for k in ('blocks','spans') for a,v in base_catalog[k].items()):
        raise ValueError('staged_field_inventory_source_prefix_mismatch')
    initial=validate_inventory(inventory,original)
    report['issues']=[i for i in report['issues'] if not i['code'].startswith('first_read_')]
    report['issues'] += [{'code':'first_read_'+i['code'],'path':'/'} for i in initial['issues']]
    appended=[a for a in catalog['blocks'] if a not in base_catalog['blocks']]
    read=[a for entry in reversed(history) for a in entry['read_context_block_ids']]+list(read_context_block_ids)
    if len(set(read))!=len(read) or not set(read)<=set(appended):
        raise ValueError('staged_field_context_read_ancestry_invalid')
    if set(read)!=(set(graph.processed_block_ids)&set(appended)):
        report['issues'].append({'code':'revision_context_read_ledger_mismatch','path':'/'})
    report['valid']=not report['issues']
    report['source_scope']={'policy':COVERAGE_POLICY,
        'first_read':{'root_run_id':root['run_id'],'bundle_sha256':digest(original.model_dump()),
            'inventory_sha256':digest(inventory.model_dump()),'block_ids':list(base_catalog['blocks']),
            'processed_block_ids':inventory.processed_block_ids,'unread_block_ids':inventory.unread_block_ids,
            'result_items':len(inventory.items),'validation':initial},
        'revision_context':{'current_bundle_sha256':digest(bundle.model_dump()),
            'appended_block_ids':appended,'declared_read_block_ids':read,
            'not_declared_read_block_ids':[a for a in appended if a not in read],
            'ancestor_read_history':list(reversed(history)),
            'current_read_context_block_ids':list(read_context_block_ids),
            'independent_result_inventory':False,'counted_as_recall_gain':False},
        'reading_is_model_reported':True,'independent_recall_denominator_available':False}
    return report


def verify_receipt(receipt,bundle,raw_output,*,depth=0):
    if depth>8: raise ValueError('staged_field_ancestry_limit')
    parent=receipt['revision_parent'];request=validate_request(receipt['config']['review_request'],parent,bundle)
    graph,inventory=resolve_parent(parent,depth=depth+1)
    if (receipt['config']['parent_run_id']!=parent['run_id'] or receipt['inventory']!=inventory.model_dump()
            or receipt['review_request']!=request.model_dump()
            or receipt['config']['review_request_sha256']!=digest(request.model_dump())):
        raise ValueError('staged_field_receipt_binding_mismatch')
    if 'extraction' not in receipt: return graph,inventory
    revision=_apply(parent,bundle,NativeEdits.model_validate_json(raw_output),request,
        field_evidence_policy=receipt['config'].get('field_evidence_policy','legacy_all_replacements'),
        evidence_binding_policy=receipt['config'].get('evidence_binding_policy'),
        literal_witness_policy=receipt['config'].get('literal_witness_policy'),
        binding_failure_policy=receipt['config'].get('binding_failure_policy'),
        quantity_name_policy=receipt['config'].get('quantity_name_policy'),
        quantity_raw_policy=receipt['config'].get('quantity_raw_policy'),
        field_source_policy=receipt['config'].get('field_source_policy'))
    if revision.audit!=receipt['revision_audit'] or revision.revised_graph.expand(bundle).model_dump()!=receipt['extraction']:
        raise ValueError('staged_field_receipt_reconstruction_mismatch')
    if not {(i['code'],i['path']) for i in revision.audit['issues']} <= {(i['code'],i['path']) for i in receipt['validation']['issues']}:
        raise ValueError('staged_field_receipt_omits_review_hold')
    policy=receipt['config'].get('coverage_policy')
    if policy is not None:
        if policy!=COVERAGE_POLICY:raise ValueError('staged_field_coverage_policy_unknown')
        coverage=validate_coverage(revision.revised_graph,inventory,bundle,parent=parent,
                                  read_context_block_ids=revision.audit['read_context_block_ids'])
        if coverage!=receipt['inventory_coverage']:
            raise ValueError('staged_field_coverage_receipt_mismatch')
        if not {(i['code'],i['path']) for i in coverage['issues']} <= {(i['code'],i['path']) for i in receipt['validation']['issues']}:
            raise ValueError('staged_field_receipt_omits_coverage_hold')
    return revision.revised_graph,inventory


INSTRUCTIONS='''Perform only the exact REQUEST.fields operations against this fallible graph.
Return one decision per target, including unresolved when the source is insufficient.
The request identifies concerns, not correct replacement answers. Read original
source spans, including appended method context, before changing a scientific field.
replace supplies the full value of ONLY the target field in its existing type,
except quantity/raw and orientation_raw replacements which use source-choice objects.
For orientation_raw replacements, DIRECTION_CONTEXT lists exact original phrases
at verified source coordinates. Use value={"source_choice":"D1"} to select one
applicable choice; never type or translate a replacement direction. Perpendicular
and parallel candidates can occur together: read the exact result-field pair.
Unsupported notation must stay unresolved. A field magnitude is not a direction.
The DIRECTION_CONTEXT rule applies only to orientation_raw, not component_raw.
For component_raw, supply an applicable exact source fragment as a string under
the ordinary source-evidence rules; an empty orientation catalog does not forbid
a component fragment. Do not infer applicability merely from a literal match.
For every changed field, span_ids must retain all REQUEST source_span_ids; these
are required source witnesses, not optional hints. Include additional applicable
context when necessary. This requirement does not prove sample ownership.
bind_evidence uses value=null and changes ONLY the source binding of the exact
target field. It must support that entire existing value, including all parts of
a sensitivity or condition object. It cannot fix a wrong value, interpretation or
nonliteral raw string. Use unresolved when the existing value lacks support.
For an owning object, select its complete context and preserve its more specific
child-field evidence. Do not substitute a different field or repair data under
the guise of rebinding evidence. An unchanged_supported decision makes no change.
For bind_evidence requests, choose bind_evidence or unresolved, never an implicit
no-op. LITERAL_SUPPORT lists deterministic source matches for literal prose and
labels. If any listed field has no supporting span, binding is forbidden and
unresolved is required. Otherwise selected spans must support every listed
literal. Matching text is necessary but does not prove semantic/sample ownership.
Numeric raw notation still requires its separate numeric semantic validation.
For an explicitly requested replacement of an unknown method, replace with
value=null preserves the unknown and clears that field's invalid evidence under
the non-null-fields policy. unresolved with value=null performs no cleanup.
Do not fill an unknown method simply to make its evidence pointer valid.
A requested quantity/raw replacement is a literal presentation correction only.
For this target, value is an object {"source_choice":"Q1"} selecting one entry
from QUANTITY_RAW_CONTEXT. Do not type the replacement string. The program copies
the exact original fragment at that choice's verified source coordinates and
preserves its full numeric shape and unit. Read the source owner and context:
an equal number or compatible unit elsewhere does not establish applicability.
If there is no applicable choice, use unresolved with value=null. Unsupported
table/prose layouts retain their source assertions and review holds.
Select an exact original numeric expression supporting this quantity. Its value,
relation, endpoints, unit, approximation and uncertainty remain frozen. Do not
change a number or scale to repair a literal mismatch. TeX math delimiters can
occur inside a source expression and must be preserved by source selection.
This recognizer requires a complete fragment with an explicit compatible unit.
A whole-quantity scientific correction needs its own explicit request.
QUANTITY_NAME_CONTEXT lists exact source assignments compatible with the frozen
result number, numeric shape and explicit unit. These are fallible source-owner
candidates, not approved names. For a quantity_name_raw replacement, select one
N-key in quantity_name_witness and copy its exact name to value. Read the linked
sample, state, procedure, definition and source role before choosing; an equal
number/unit elsewhere is not identity. Choose unresolved if no applicable choice
exists. Unsupported prose/table layouts remain pending, not absent results.
unchanged_supported requires a choice matching the existing name. Other actions
and non-name fields use quantity_name_witness=null. Do not change numerical
values, units, approximation or uncertainty to make a name match. The program
preserves them and retains their pre-existing validation issues.
An unmapped physical quantity requires a nonblank original source name or symbol.
Do not clear that name to null to remove a source-literal error. Read the linked
table heading, caption and surrounding method spans; if a faithful name cannot
be established, keep the field unresolved with its original value and review hold.
For bind_evidence, literal_witnesses maps EACH literal path in LITERAL_SUPPORT to
one listed witness_choices key (W1, W2, ...). Each choice contains the original
span or adjacent spans supporting that literal; no text is rewritten. Choices
are local to each literal path. Additional field context stays in span_ids. Use {} if there
are no literal paths. Other decisions use literal_witnesses=null. span_ids keeps
the additional field-context evidence; the program combines these explicit span
choices. A matching macro alone does not establish the sample identity: include
its actual specimen context or leave the binding unresolved. Do not silently
expand or rewrite a source formula macro. Invalid independent evidence bindings
are preserved as rejected decisions while other supported bindings may survive;
this never certifies the scientific interpretation or removes review holds.
remove is permitted only for an explicitly listed erroneous auxiliary assertion or
support edge; never erase its actual source fact when another representation is needed.
append_owner is permitted only for a requested sample, state or protocol slot.
Return one typed declaration with the exact assigned_id in OWNER_ADDITION_SLOTS.
The program appends it without changing any existing owner. Rebind the applicable
existing observation through its separately requested sample_id, state_id and/or
protocol_id fields. Each added owner must be used by an observation; never add a
dummy owner to satisfy a missing reference. If unsupported, choose unresolved.
New owners use the existing scientific types and field evidence. An unknown probe
uses method=null and method_class=unspecified, not a nearby NMR or transport
procedure. Unknown specimen applicability stays unresolved; a shared formula
does not prove reuse of the same specimen. Do not invent a formula, ambient
pressure, condition or protocol parameter. A limiting T -> 0 assertion is not a
measurement at 0 K and does not specify a fitting or extrapolation method.
Preserve its literal interpretation on the result. No scientific acceptance,
duplicate-identity decision or evidence of a new measurement is conferred.
hold_observation is permitted only for an explicitly requested whole observation.
Its value is {"reason":"not_a_result|insufficient_context|unresolved", "explanation":"..."}.
Use not_a_result only when this item does not report an independent result of the
asserted kind, such as an applied-field regime misread as a new critical threshold.
A repeated genuine result or a missing owner may require unresolved or
insufficient_context instead; do not remove a true source result to improve metrics.
Every original item ID remains in the unextracted ledger with the model's reason,
and its full old observation remains in immutable ancestry. This is a review hold,
never approved scientific exclusion or proof of a negative measurement. Use each
item's own source occurrence. Any context binding, dependency or condition support
pointing to the held result must be explicitly addressed in the same request;
the program rejects dangling relations instead of silently removing them.
All quantities and owners of other observations remain unchanged. Preserve useful
source facts as existing context or explicit pending items, not as invented results.
An explicitly requested stale evidence pointer may be removed only if it addresses
a field absent from its owning object. Do not remove an existing field's evidence,
including evidence for a null field. A requested whole context disposition may
change between carried and unresolved when supported by its own original context;
its context_id must remain exactly unchanged. Do not transfer a procedure merely
because the same abstract also supplies a sample formula or form.
Unchanged and unresolved use value=null. Every change needs an English reason and
the field's own source spans. The program replaces evidence for that field only.
Existing object IDs and all unlisted scientific fields remain fixed. Untargeted
scientific problems remain review holds. Do not return a complete graph.
Width is distinct from thickness, fit results from direct observations, adopted
cited parameters from newly measured data, and current steps from magnetic fields.
Use unmapped for a physical result lacking a correct registered kind. Preserve
all source numbers, bounds, uncertainty and units except an explicitly targeted
quantity correction. A source fit interval must not collapse to its first endpoint.
A negative observation does not measure an unrelated geometry condition. Source
assertions can remain as sample conditions or result sensitivities independently
of invalid support edges. No scientific approval or training permission is granted.
window_position belongs only to a condition whose role is detection_window; a fit
window or study extent keeps its numeric interval but uses window_position=null.
Context bindings must remain nonempty for carried context. Select only actual
fields still available after requested removals, or leave the target unresolved.
read_context_block_ids lists only appended context blocks read in this revision;
it is an extraction coverage report, not proof of whole-paper coverage.
'''
PROMPT_HASH=digest({'version':PROMPT_VERSION,'instructions':INSTRUCTIONS})


def output_schema(bundle=None,inventory=None,parent=None,*,review_request=None):
    if parent is None: return strict_schema(NativeEdits)
    request=validate_request(review_request,parent,bundle);graph,_=resolve_parent(parent)
    schema=strict_schema(NativeEdits);schema['$defs']={}
    branches={};span_ids=list(source_catalog(bundle)['spans'])
    remaining=deepcopy(graph.model_dump())
    proposed_holds={pointer(remaining,t.path)['id'] for t in request.fields if t.operation=='hold_observation'}
    remaining['observations']=[o for o in remaining['observations'] if o['id'] not in proposed_holds]
    removals=[t.path for t in request.fields if t.operation=='remove']
    for path in sorted(removals,key=lambda p:int(p.rsplit('/',1)[1]),reverse=True):
        prefix,index=path.rsplit('/',1);pointer(remaining,prefix).pop(int(index))
    from .item_stages import binding_targets
    for t in request.fields:
        value_schema=(owner_additions.schema(graph,parent['run_id'],t,request.fields,span_ids) if t.operation=='append_owner'
                      else observation_holds.HoldDecision.model_json_schema() if t.operation=='hold_observation'
                      else TypeAdapter(field_type(graph,t.path)).json_schema())
        schema['$defs'].update(value_schema.pop('$defs',{}))
        if re.fullmatch(r'/states/\d+/conditions/\d+/window_position',t.path):
            if pointer(graph.model_dump(),t.path.rsplit('/',1)[0])['role']!='detection_window':
                value_schema={'type':'null'}
        if re.fullmatch(r'/context_dispositions/\d+/bindings',t.path):
            choices=[]
            for target in binding_targets(remaining):
                if target['fields']:
                    choices.append({'type':'object','additionalProperties':False,
                        'properties':{'entity':{'type':'string','enum':[target['entity']]},
                            'entity_id':{'type':'string','enum':[target['entity_id']]},
                            'field':{'type':'string','enum':target['fields']}},'required':['entity','entity_id','field']})
            value_schema=dict(value_schema,items={'anyOf':choices})
        options=[]
        actions=(t.operation,'unresolved') if t.operation=='append_owner' else (t.operation,'unchanged_supported','unresolved')
        reference=re.fullmatch(r'/observations/\d+/(sample_id|state_id|protocol_id)',t.path)
        if reference:
            group={'sample_id':'samples','state_id':'states','protocol_id':'protocols'}[reference[1]]
            value_schema['enum']=owner_additions.available_ids(graph,parent['run_id'],request.fields)[group]
        name_context=name_witness.context(graph,t.path,bundle)
        raw_context=raw_witness.context(graph,t.path,bundle)
        direction=direction_witness.context(t.path,bundle,t.source_span_ids)
        if direction and t.operation=='replace':
            actions=('replace','unresolved') if direction['choices'] else ('unresolved',)
            value_schema={'type':'object','additionalProperties':False,
                'properties':{'source_choice':{'type':'string','enum':list(direction['choices'])}},
                'required':['source_choice']}
        if raw_context and t.operation=='replace':
            actions=('replace','unresolved') if raw_context['choices'] else ('unresolved',)
            value_schema={'type':'object','additionalProperties':False,
                'properties':{'source_choice':{'type':'string','enum':list(raw_context['choices'])}},
                'required':['source_choice']}
        if name_context and t.operation=='replace':
            actions=('replace','unresolved') if name_context['choices'] else ('unresolved',)
        if t.operation=='bind_evidence':
            supported=all(v['supporting_span_ids'] for v in literal_support(graph,t.path,bundle).values())
            actions=('bind_evidence','unresolved') if supported else ('unresolved',)
        for action in actions:
            witnesses={'type':'null'}
            names={'type':'null'}
            candidate_value=value_schema
            if name_context and action=='replace':
                names={'type':'string','enum':list(name_context['choices'])}
                candidate_value={'type':'string','enum':list(dict.fromkeys(c['name'] for c in name_context['choices'].values()))}
            if action=='bind_evidence':
                support=literal_support(graph,t.path,bundle)
                witnesses={'type':'object','additionalProperties':False,
                    'properties':{path:{'type':'string','enum':list(value['witness_choices'])} for path,value in support.items()},
                    'required':list(support)}
            options.append({'type':'object','additionalProperties':False,
                'properties':{'action':{'type':'string','enum':[action]},
                    'value':candidate_value if action in {'replace','hold_observation','append_owner'} else {'type':'null'},
                    'literal_witnesses':witnesses,
                    'quantity_name_witness':names,
                    'span_ids':{'type':'array','items':{'type':'string','enum':span_ids},'maxItems':32,
                        'minItems':0 if action=='unresolved' else 1},
                    'reason':{'type':'string','minLength':1,'maxLength':3000}},
                'required':['action','value','span_ids','reason','literal_witnesses','quantity_name_witness']})
        branches[t.id]={'anyOf':options}
    schema['properties']['selections']={'type':'object','additionalProperties':False,'properties':branches,'required':list(branches)}
    _,proof=source_bundle(parent,request.source_context)
    schema['properties']['read_context_block_ids']['items']={'type':'string','enum':[b['alias'] for b in proof['added_blocks']]}
    if not proof['added_blocks']:schema['properties']['read_context_block_ids']={'type':'array','items':{'type':'string'},'maxItems':0}
    for key,value in {'work_id':bundle.work_id,'parent_run_id':parent['run_id'],
        'base_graph_sha256':digest(graph.model_dump()),'request_sha256':digest(request.model_dump())}.items():
        schema['properties'][key]={'type':'string','enum':[value]}
    # Apply the provider's strict object rules to dynamically derived field types.
    def strict(node):
        if isinstance(node,dict):
            if node.get('type')=='object' and 'properties' in node:
                node['additionalProperties']=False;node['required']=list(node['properties'])
            for value in node.values():strict(value)
        elif isinstance(node,list):
            for value in node:strict(value)
    strict(schema)
    return schema


def render(bundle,inventory,parent,*,review_request):
    request=validate_request(review_request,parent,bundle);graph,_=resolve_parent(parent)
    display=request.model_dump(exclude={'source_context'})
    return '\n'.join([INSTRUCTIONS,REGISTRY_INSTRUCTIONS,DETECTION_INSTRUCTIONS,
        'BASE_GRAPH: '+canonical(graph.model_dump()),'BASE_GRAPH_SHA256: '+digest(graph.model_dump()),
        'REQUEST: '+canonical(display),'REQUEST_SHA256: '+digest(request.model_dump()),
        'OWNER_ADDITION_SLOTS: '+canonical({t.id:owner_additions.spec(graph,parent['run_id'],t) for t in request.fields if t.operation=='append_owner'}),
        'LITERAL_SUPPORT: '+canonical({t.id:literal_support(graph,t.path,bundle) for t in request.fields if t.operation=='bind_evidence'}),
        'QUANTITY_NAME_CONTEXT: '+canonical({t.id:name_witness.context(graph,t.path,bundle) for t in request.fields if t.path.endswith('/quantity_name_raw')}),
        'QUANTITY_RAW_CONTEXT: '+canonical({t.id:raw_witness.context(graph,t.path,bundle) for t in request.fields if t.path.endswith('/quantity/raw')}),
        'DIRECTION_CONTEXT: '+canonical({t.id:direction_witness.context(t.path,bundle,t.source_span_ids) for t in request.fields if t.path.endswith('/orientation_raw')}),
        'PARENT_RUN_ID: '+parent['run_id'],source_text(bundle),'Return '+VERSION+'.'])


def configuration(parent,*,review_request,**kwargs):
    from .worker import configuration as base_configuration
    request=validate_request(review_request,parent)
    config=base_configuration(workflow='inventory_v11',**kwargs)
    if config['provider']!='codex': raise ValueError('staged_field_provider_not_evaluated')
    # The inventory workflow's default validator predates positioned native
    # evidence. The verified parent determines the output contract of a field
    # revision; no historical proposal or validation receipt is rewritten.
    if parent['receipt']['extraction']['schema_version']=='materials-ner/11':
        from .validation import POSITIONED_VALIDATOR_VERSION
        config.update(validator_version=POSITIONED_VALIDATOR_VERSION,
            native_output_schema='materials-ner/11')
    config.update(workflow='staged_field_revision_v1',output_format=VERSION,parent_run_id=parent['run_id'],
        coverage_policy=COVERAGE_POLICY,
        evidence_binding_policy=BINDING_POLICY,
        literal_witness_policy=WITNESS_POLICY,binding_failure_policy=FAILURE_POLICY,
        quantity_name_policy=name_witness.POLICY,
        quantity_raw_policy=QUANTITY_RAW_POLICY,
        field_source_policy=direction_witness.POLICY,
        field_evidence_policy='non_null_fields_v2',
        review_request=request.model_dump(),review_request_sha256=digest(request.model_dump()),
        max_inventory_repairs=0,max_extraction_repairs=0,max_evidence_patches=0,max_source_revisions=1,
        inventory_link_projection_version=None,schema_sha256=digest(output_schema()),
        prompt_version=PROMPT_VERSION,prompt_sha256=PROMPT_HASH)
    return config
