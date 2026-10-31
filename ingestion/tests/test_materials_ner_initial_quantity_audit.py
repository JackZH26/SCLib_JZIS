"""Initial extraction retains source-support gaps without rewriting science."""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner import source_quantity_audit as audit, staged_revision as revision, item_worker
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.sources import make_blocks
from ingestion.materials_ner.inventory import Inventory
from test_materials_ner_staged_revision import fixture


def test_initial_worker_records_replayable_audit_without_scientific_permission(tmp_path):
    _,bundle,packet,_,_=fixture(tmp_path)
    receipt=packet['receipt'];graph,_=revision.resolve_parent(packet);before=graph.model_dump()
    assert receipt['config']['source_quantity_audit_policy']==audit.POLICY
    result=receipt['source_quantity_audit']
    assert result==audit.audit(graph,bundle)
    assert result['graph_sha256']==digest(before) and result['records']
    assert result['scientific_graph_unchanged'] and result['unsupported_layout_is_not_absence']
    assert graph.model_dump()==before and not result['scientific_acceptance'] and not result['ml_training_eligible']
    damaged=deepcopy(receipt);damaged['source_quantity_audit']['records'][0]['status']='approved'
    with pytest.raises(ValueError,match='staged_receipt_assembly_mismatch'):
        item_worker.verify_receipt(damaged,bundle,packet['raw_output'])


def test_historical_unpinned_transcript_does_not_acquire_a_new_audit(tmp_path):
    _,bundle,packet,_,_=fixture(tmp_path);receipt=packet['receipt'];config=deepcopy(receipt['config'])
    config.pop('source_quantity_audit_policy')
    report=item_worker.assembled_report(json.loads(packet['raw_output']),bundle,Inventory.model_validate(receipt['inventory']),config)
    assert 'source_quantity_audit' not in report
    assert report['extraction']==receipt['extraction']


def test_same_numeric_value_does_not_approve_a_different_quantity_name(tmp_path):
    _,bundle,packet,_,_=fixture(tmp_path);graph,_=revision.resolve_parent(packet)
    q=graph.observations[0].result.quantity
    text=f'SYNTHETIC exact assignment $T_c={q.value:g}$ {q.unit}.'
    block=make_blocks(bundle.documents[0].id,[('synthetic:assignment',text)])[0]
    block.id='synthetic:assignment';bundle.blocks.append(block)
    alias=next(k for k,v in source_catalog(bundle)['spans'].items() if v['block_id']==block.id)
    result=graph.observations[0].result
    result.quantity_name_raw='T_c'
    evidence_type=type(result.evidence[0])
    result.evidence=[evidence_type(fields=['/quantity','/quantity_name_raw'],span_ids=[alias])]
    report=audit.audit(graph,bundle);row=next(r for r in report['records'] if r['path']=='/observations/0/result/quantity')
    assert row['status']=='name_and_numeric_assignment_supported'
    assert row['matching_name_assignments'] and row['source_review_required']
    assert not row['scientific_acceptance']
    result.quantity_name_raw='Different physical quantity'
    before=graph.model_dump();report=audit.audit(graph,bundle)
    row=next(r for r in report['records'] if r['path']=='/observations/0/result/quantity')
    assert row['status']=='quantity_name_or_numeric_coupling_unresolved'
    assert row['source_fragment_choices'] and not row['matching_name_assignments']
    assert graph.model_dump()==before and len(graph.observations)==len(before['observations'])


def test_bad_source_scope_is_reported_without_erasing_other_initial_results(tmp_path):
    _,bundle,packet,_,_=fixture(tmp_path);graph,_=revision.resolve_parent(packet)
    graph.observations[0].result.evidence[0].span_ids=['S99999']
    before=graph.model_dump();report=audit.audit(graph,bundle)
    assert any(r['status']=='source_scope_requires_review' for r in report['records'])
    assert graph.model_dump()==before and report['scientific_graph_unchanged']
