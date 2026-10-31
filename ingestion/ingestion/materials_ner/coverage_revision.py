"""Source review can retain newly discovered results explicitly unextracted."""
from typing import Literal, Union

from pydantic import create_model

from . import condition_review as conditions, scoped_review as scoped, relational_review as review
from .contract import digest
from .wire_v2 import UnextractedItem
from .wire_v9 import ScopedExtraction

VERSION='materials-scoped-review/3'
PROMPT_VERSION='materials-coverage-review-prompt/1.0.0'
UnextractedEdit=create_model('AddUnextractedResult',__base__=scoped.base.EditBase,
    action=(Literal['add'],...),entity=(Literal['unextracted_item'],...),value=(UnextractedItem,...))


class NativeEdits(conditions.NativeEdits):
    schema_version: Literal['materials-scoped-review/3']
    edits: list[Union[scoped.edit_types+(UnextractedEdit,)]]


verify_parent=scoped.verify_parent
validate_request=scoped.validate_request
INSTRUCTIONS="""Source discovery must not force an unsupported scientific result.
This revision additionally allows entity=unextracted_item, action=add, with value
containing item_id, reason and explanation. To retain a newly discovered source
assertion that cannot yet be represented faithfully, add its literal source item
using entity=additional_item and add its matching unextracted_item in the same
response. Give both edits original source spans and source-grounded reasons, and
account for both in the issue disposition. Reasons are not_a_result,
insufficient_context or unresolved. A real fitted/derived result is not_a_result
only if the original source actually warrants that exclusion, not because its
type is unregistered or a measurement condition is unknown.
Do not invent a point pressure, assign another specimen's method, average endpoint
values, silently drop units or misclassify an unknown quantity as a registered one.
Keep separate endpoints as separate source items when the source reports distinct
values. Preserve negative or qualitative assertions with their own literal source.
An explicitly unextracted item remains a review hold, not an accepted result or ML
row. Resolve an earlier unextracted item only through the existing explicit
resolved_unextracted_items operation with a real observation carrying that ID.
All condition-change accounting and whole-graph source checks still apply.
"""
PROMPT_HASH=digest({'version':PROMPT_VERSION,'conditions':conditions.PROMPT_HASH,'instructions':INSTRUCTIONS})


def configuration(parent,*,review_request,**kwargs):
    config=scoped._configuration(parent,review_request=review_request,**kwargs)
    config.update(workflow='scoped_review_v3',output_format=VERSION,schema_sha256=digest(output_schema()),
                  prompt_version=PROMPT_VERSION,prompt_sha256=PROMPT_HASH)
    return config


def output_schema(bundle=None,inventory=None,parent=None,*,review_request=None):
    schema=NativeEdits.model_json_schema()
    original=conditions.output_schema(bundle,inventory,parent,review_request=review_request)
    schema['$defs'].update(original['$defs'])
    for key in ['work_id','parent_run_id','base_graph_sha256','request_sha256','dispositions']:
        schema['properties'][key]=original['properties'][key]
    if bundle is not None:
        from .evidence import source_catalog
        schema['$defs']['AddUnextractedResult']['properties']['span_ids']['items']['enum']=list(source_catalog(bundle)['spans'])
    return schema


def render(bundle,inventory,parent,*,review_request):
    return conditions.render(bundle,inventory,parent,review_request=review_request).replace(
        'Return '+conditions.VERSION+'.',INSTRUCTIONS+'\nReturn '+VERSION+'.')


def _apply(graph,inventory,parent_run_id,edits,request,bundle):
    if edits.request_sha256!=digest(request.model_dump()):raise ValueError('review_response_request_hash_mismatch')
    revision=scoped.base.apply_to_graph(graph.model_dump(),parent_run_id,edits,
        graph_model=ScopedExtraction,applied_model=scoped.AppliedScoped)
    conditions._condition_audit(graph,revision.revised_graph,edits.condition_changes,bundle)
    items={item.id:item for item in inventory.items+revision.revised_graph.additional_items}
    for edit in edits.edits:
        if edit.entity!='unextracted_item':continue
        item=items.get(edit.value.item_id)
        if item is None or not set(edit.span_ids)&set(item.source_span_ids):
            raise ValueError('coverage_revision_unextracted_source_disconnected')
    return conditions.AppliedReview(**revision.model_dump(),request=request,dispositions=edits.dispositions,
                                    condition_changes=edits.condition_changes)


def apply_edits(parent,bundle,edits,*,review_request):
    graph,inventory=scoped.resolve_parent(parent,bundle)
    request=review._check_request(review_request,parent,bundle,graph)
    return _apply(graph,inventory,parent['run_id'],edits,request,bundle)


def _audit(graph,parent_run_id,revision,bundle):
    proof=conditions._audit(graph,parent_run_id,revision,bundle)
    return dict(proof,schema='materials-coverage-review-audit/1',
        source_item_changes=[c for c in proof['changes'] if c['entity'] in {'additional_item','unextracted_item'}])


def audit_revision(parent,revision,bundle):
    graph,_=scoped.resolve_parent(parent,bundle)
    return _audit(graph,parent['run_id'],revision,bundle)


def verify_receipt(receipt,bundle,raw_output,*,depth=0):
    parent=receipt['revision_parent'];graph,inventory=scoped.resolve_parent(parent,bundle,depth=depth)
    request=review._check_request(receipt['config']['review_request'],parent,bundle,graph)
    if (receipt['config']['parent_run_id']!=parent['run_id'] or receipt['inventory']!=inventory.model_dump()
            or receipt['config']['review_request_sha256']!=digest(request.model_dump())
            or receipt.get('review_request')!=request.model_dump()):raise ValueError('coverage_receipt_request_binding_mismatch')
    if 'extraction' not in receipt:return graph,inventory
    revision=_apply(graph,inventory,parent['run_id'],NativeEdits.model_validate_json(raw_output),request,bundle)
    proof=_audit(graph,parent['run_id'],revision,bundle)
    if proof!=receipt.get('revision_audit') or revision.revised_graph.expand(bundle).model_dump()!=receipt['extraction']:
        raise ValueError('coverage_receipt_reconstruction_mismatch')
    if not {(i['code'],i['path']) for i in proof['issues']}<={(i['code'],i['path']) for i in receipt['validation']['issues']}:
        raise ValueError('coverage_receipt_omits_review_holds')
    return revision.revised_graph,inventory
