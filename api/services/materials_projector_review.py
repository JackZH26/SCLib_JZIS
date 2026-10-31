"""Bounded private display of original projector failures and source findings.

Import verifies the scientific packet. This projection verifies the embedded
provenance and source quotations it exposes; it never reruns a model or treats
an assistant finding as independent approval. Local artifact paths are omitted.
"""
from copy import deepcopy
import hashlib
import json

from services import materials_proposal_review as review
from services.materials_proposal_storage import canonical, digest

FORMAT = 'materials-source-projector-proposal/1'
WORKFLOW = 'source_projector_proposal_v1'
VERSION = 'materials-projector-review-context/1'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _embedded(pin, text):
    review.require(isinstance(text, str) and len(text.encode()) == pin['bytes']
                   and _sha(text.encode()) == pin['sha256'], 'projector_review_capture_mismatch')
    def pairs(items):
        review.require(len(dict(items)) == len(items), 'projector_review_duplicate_key')
        return dict(items)
    return json.loads(text, object_pairs_hook=pairs)


def _anchor(anchor, packet):
    review.require(set(anchor) == {'block_id','start_char','end_char','quote'}, 'projector_review_anchor_shape')
    block = next((b for b in packet['bundle']['blocks'] if b['id'] == anchor['block_id']), None)
    a, z = anchor['start_char'], anchor['end_char']
    review.require(block is not None and type(a) is int and type(z) is int
        and 0 <= a < z <= len(block['text']) and block['text'][a:z] == anchor['quote'], 'projector_review_source_mismatch')
    return dict(anchor, document_id=block['document_id'], locator=block['locator'],
        block_sha256=block['sha256'], quote_sha256=_sha(anchor['quote'].encode()))


def captured(packet):
    """Check the capture before either a display projection or a raw export."""
    receipt = packet['receipt']; c = receipt.get('config', {})
    if (c.get('workflow') != WORKFLOW and c.get('output_format') != FORMAT
            and receipt.get('schema') != FORMAT and 'projector_provenance' not in receipt):
        return None
    try:
        review.require(c.get('workflow') == WORKFLOW and c.get('output_format') == FORMAT
            and receipt.get('schema') == FORMAT and not packet['scientific_acceptance']
            and not packet['ml_training_eligible'], 'projector_review_identity')
        p = receipt['projector_provenance']; config = p['config']
        attempt = _embedded(p['terminal_pin'], p['terminal_json'])
        review.require(attempt['config_sha256'] == digest(config)
            and attempt['job_id'] == receipt['job_id'] == packet['job_id']
            and attempt['work_id'] == receipt['work_id'] == packet['work_id']
            and attempt['bundle_sha256'] == receipt['bundle_sha256'] == packet['bundle_hash']
            and receipt['graph_authorship'] == config['model'] == c['model']
            and config['provider'] == c['provider']
            and all(receipt[k] is False for k in ['paper_completed','scientific_acceptance','ml_training_eligible','production_writes'])
            and all(attempt[k] is False for k in ['paper_completed','scientific_acceptance','ml_training_eligible','semantic_validation_qualified']),
            'projector_review_terminal_mismatch')
        returned = _embedded(attempt['provider_return'], p['provider_json'])
        review.require(returned['job_id'] == attempt['job_id'] and returned['attempt_id'] == attempt['attempt_id']
            and returned['config_sha256'] == attempt['config_sha256']
            and returned['result']['model'] == config['model'] and returned['result']['provider'] == config['provider']
            and returned['result']['text'] == packet['raw_output']
            and _sha(packet['raw_output'].encode()) == receipt['raw_output_sha256'], 'projector_review_provider_mismatch')
        model = json.loads(packet['raw_output'])
        review.require(_embedded(attempt['model_graph'], p['artifacts']['model_graph']) == model,
                       'projector_review_model_graph_mismatch')
        parsed = 'extraction' in receipt
        if parsed:
            review.require(_embedded(attempt['graph'], p['artifacts']['graph']) == receipt['extraction']
                and attempt['outcome'] == 'graph_drafted_pending_semantic_review', 'projector_review_compiled_graph_mismatch')
        else:
            review.require(attempt['outcome'] == 'graph_not_validated' and not any(packet['rows'].values())
                           and attempt['state'] == 'quarantined', 'projector_review_unparsed_graph_mismatch')
        diagnostic = (_embedded(attempt['diagnostic'], p['artifacts']['diagnostic'])
                      if 'diagnostic' in attempt else None)
        request = _embedded(config['request'], p['request_json'])
        scope = _embedded(request['scope'], p['scope_json'])
        coverage = _embedded(request['coverage'], p['coverage_json'])
        review.require(coverage['bundle_sha256'] == packet['bundle_hash']
            and coverage['work_id'] == packet['work_id'] and coverage['source']['preflight'] == scope['preflight']
            and receipt['paper_review']['coverage_hash'] == coverage['coverage_hash']
            and receipt['paper_review']['scope_review_complete'] is False
            and receipt['paper_review']['independent_review'] is False, 'projector_review_coverage_mismatch')
        findings = None
        if receipt['review_findings'] is not None:
            attachment = receipt['review_findings']; findings = _embedded(attachment['pin'], attachment['text'])
            review.require(findings['schema'] == 'materials-projector-review-findings/1'
                and findings['work_id'] == packet['work_id'] and findings['bundle_sha256'] == packet['bundle_hash']
                and findings['attempt_sha256'] == p['terminal_pin']['sha256']
                and findings['independent_review'] is False and findings['author']['kind'] == 'assistant'
                and len(findings['findings']) <= 2000, 'projector_review_findings_mismatch')
        items = []
        for item in findings['findings'] if findings else []:
            review.require(item['kind'] in {'entity','source_completeness'}, 'projector_review_finding_kind')
            if item['kind'] == 'entity':
                parts = item['path'].split('/')
                review.require(len(parts) == 3 and parts[1] in receipt['extraction']
                    and parts[2].isdigit() and int(parts[2]) < len(receipt['extraction'][parts[1]]), 'projector_review_finding_owner')
            else:
                review.require(item['path'] == '/paper', 'projector_review_finding_scope')
            items.append({k:deepcopy(item[k]) for k in ['id','kind','path','code','note']} |
                         dict(source_quotes=[_anchor(a, packet) for a in item['anchors']]))
        review.require([i for i in (findings['findings'] if findings else []) if i['kind'] == 'source_completeness']
                       == receipt['paper_review']['source_completeness_findings'], 'projector_review_omissions_mismatch')
        return dict(provenance=p, config=config, attempt=attempt, model=model, parsed=parsed,
                    diagnostic=diagnostic, coverage=coverage, findings=findings, items=items)
    except review.ProposalIntegrityError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        raise review.ProposalIntegrityError('projector_review_capture_invalid') from error


def project(packet):
    value = captured(packet)
    if value is None: return None
    a, p, c, coverage, findings = (value[k] for k in ['attempt','provenance','config','coverage','findings'])
    raw_results = value['model'].get('results') if isinstance(value['model'], dict) else None
    return dict(version=VERSION, graph_authorship=packet['receipt']['graph_authorship'],
        provider=c['provider'], model=c['model'], reasoning=c['reasoning'],
        producer_interface=c['interface_version'], evidence_binding=c['binding_version'],
        terminal=dict(job_id=a['job_id'], attempt_id=a['attempt_id'], receipt_sha256=p['terminal_pin']['sha256'],
            config_sha256=a['config_sha256'], raw_output_sha256=packet['receipt']['raw_output_sha256'],
            state=a['state'], outcome=a['outcome'], error_code=a.get('error_code'), diagnostic=deepcopy(value['diagnostic'])),
        disposition='draft_pending_review' if value['parsed'] else 'unparsed_model_graph',
        raw_result_objects=len(raw_results) if isinstance(raw_results, list) else None,
        retained_result_rows=len(packet['rows']['results']),
        publication_version=coverage['source']['publication_version'], coverage_sha256=coverage['coverage_hash'],
        findings_author=deepcopy(findings['author']) if findings else None,
        findings_created_at=findings['created_at'] if findings else None,
        findings_sha256=packet['receipt']['review_findings']['pin']['sha256'] if findings else None,
        findings=value['items'], source_completeness_findings=sum(i['kind'] == 'source_completeness' for i in value['items']),
        independent_review=False, paper_completed=False, scientific_acceptance=False, ml_training_eligible=False)
