"""Audit actual occurrences rather than trusting a model's closed inventory."""
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace

import jsonschema
import pytest

from ingestion.materials_ner import source_mentions as audit
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.sources import make_blocks
from ingestion.materials_ner import source_audit_worker as worker
from test_materials_ner_scoped_conditions import fixture as source_fixture
from test_materials_ner_scoped_revision import fixture as parent_fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def fixture():
    bundle,_,_=source_fixture()
    bundle.blocks=make_blocks(bundle.documents[0].id,[('target:synthetic:chars[0:250]',
        'A decreases from 0.25 nΩ m K-2 to 0.01 nΩ m K-2. The fitted n increases from 1.5 to 2.0. '
        'Tc is 6 K at 30 GPa. Figure 2 cites [33]. FeSe0.9 contains ¹⁸O.')])
    manifest=audit.mention_manifest(bundle);items=[]
    for index,(name,value) in enumerate([('A','0.25 nΩ m K-2'),('A','0.01 nΩ m K-2'),('n','1.5'),('n','2.0'),('Tc','6 K')],1):
        items.append({'id':f'I{index}','sample_raw':'FeSe0.9','quantity_name_raw':name,'value_raw':value,
                      'source_span_ids':['S1'],'context_span_ids':[]})
    inventory={'schema_version':'materials-source-inventory/1','work_id':bundle.work_id,
        'processed_block_ids':['B1'],'unread_block_ids':[],'items':items,'context_assertions':[],
        'span_dispositions':[{'span_id':'S1','role':'result_assertions','item_ids':[i['id'] for i in items],'reason':None}],
        'limitations':[]}
    result_ids={'0.25':'I1','0.01':'I2','1.5':'I3','2.0':'I4','6':'I5'}
    decisions=[]
    for mention in manifest['mentions']:
        token=mention['text'];item=result_ids.get(token)
        kind=('result' if item else 'condition' if token=='30' else 'citation' if token=='33'
              else 'sample_identity' if token in ['0.9','¹⁸'] else 'unit_or_equation')
        decisions.append({'mention_id':mention['id'],'kind':kind,'item_ids':[item] if item else [],
                          'reason':'Classify this literal occurrence in the supplied synthetic sentence.'})
    raw=dict(inventory,schema_version=audit.AUDIT_VERSION,bundle_sha256=digest(bundle.model_dump()),
             mention_manifest_sha256=digest(manifest),mention_decisions=decisions)
    return bundle,manifest,inventory,raw


def test_lexer_covers_every_numeric_glyph_and_keeps_repeated_occurrences_separate():
    bundle,manifest,_,_=fixture()
    target=bundle.blocks[0]
    positions=[i for m in manifest['mentions'] for i in range(m['start_char'],m['end_char'])]
    assert len(positions)==len(set(positions))
    assert all(i in positions for i,ch in enumerate(target.text) if ch.isnumeric())
    assert len([m for m in manifest['mentions'] if m['text']=='2'])==3
    assert any(m['text']=='¹⁸' for m in manifest['mentions'])
    for mention in manifest['mentions']:
        assert target.text[mention['start_char']:mention['end_char']]==mention['text']
    context=make_blocks(bundle.documents[0].id,[('context-document:synthetic','Context-only Tc = 999 K.')])[0]
    context.id+=':context';context.ordinal=1;bundle.blocks.append(context)
    assert all(m['text']!='999' for m in audit.mention_manifest(bundle)['mentions'])


def test_blind_audit_exposes_four_omissions_without_turning_conditions_or_units_into_results():
    bundle,manifest,inventory,raw=fixture();candidate=audit.MentionAudit.model_validate(raw)
    schema=audit.output_schema(bundle);jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(raw,schema)
    assert audit.validate_audit(candidate,bundle)['valid']
    prior=deepcopy(inventory);prior['items']=prior['items'][-1:];prior['span_dispositions'][0]['item_ids']=['I5']
    graph=SimpleNamespace(additional_items=[],model_dump=lambda:{'additional_items':[]})
    comparison=audit.compare_inventory(candidate,Inventory.model_validate(prior),graph,bundle)
    assert [r['mention']['text'] for r in comparison['unrepresented_result_mentions']]==['0.25','0.01','1.5','2.0']
    assert not comparison['classification_disagreements'] and comparison['population_recall_estimate'] is None
    assert not comparison['independent_gold'] and not comparison['scientific_acceptance']
    assert 'FIRST_READ_INVENTORY' not in audit.render(bundle) and 'BASE_GRAPH' not in audit.render(bundle)


@pytest.mark.parametrize('mutation',['missing','duplicate','stale','wrong_item','numeric_item_without_link','unresolved'])
def test_unaccounted_and_disconnected_numeric_decisions_remain_invalid(mutation):
    bundle,_,_,raw=fixture()
    if mutation=='missing':raw['mention_decisions'].pop()
    if mutation=='duplicate':raw['mention_decisions'][-1]['mention_id']=raw['mention_decisions'][0]['mention_id']
    if mutation=='stale':raw['mention_manifest_sha256']='0'*64
    if mutation=='wrong_item':raw['mention_decisions'][0]['item_ids']=['I5']
    if mutation=='numeric_item_without_link':raw['mention_decisions'][0].update(kind='other',item_ids=[])
    if mutation=='unresolved':raw['mention_decisions'][-1]['kind']='unresolved'
    assert not audit.validate_audit(audit.MentionAudit.model_validate(raw),bundle)['valid']


def test_item_occurrence_does_not_match_a_different_equal_number():
    bundle,manifest,inventory,raw=fixture()
    item=Inventory.model_validate(inventory).items[-1]
    item.value_raw='2'
    matched=audit.item_mentions(item,source_catalog(bundle),manifest)
    assert {m['text'] for m in manifest['mentions'] if m['id'] in matched}=={'2'}
    # A digit inside 0.25 or 2.0 is not the separate numeric occurrence '2'.
    assert len(matched)==3


@pytest.mark.parametrize('local_context',[False,True])
def test_real_worker_contract_keeps_blind_input_and_reconstructs_backup(tmp_path,local_context):
    store,bundle,parent,_,_=parent_fixture(tmp_path)
    manifest=audit.mention_manifest(bundle);catalog=source_catalog(bundle)
    raw=deepcopy(parent['receipt']['inventory']);inventory=Inventory.model_validate(raw)
    matches={m['id']:[] for m in manifest['mentions']}
    for item in inventory.items:
        for identifier in audit.item_mentions(item,catalog,manifest):matches[identifier].append(item.id)
    raw.update(schema_version=audit.AUDIT_VERSION,bundle_sha256=digest(bundle.model_dump()),
        mention_manifest_sha256=digest(manifest),mention_decisions=[{'mention_id':m['id'],
            'kind':'result' if matches[m['id']] else 'other','item_ids':matches[m['id']],
            'reason':'Synthetic worker accounting fixture.'} for m in manifest['mentions']])
    config=worker.configuration(parent,local_context=local_context);job=store.enqueue(work_id=bundle.work_id,bundle_hash=digest(bundle.model_dump()),config=config,max_attempts=1)
    outcome=worker.run_one(store,job,parent,bundle,provider_override=SequenceProvider([raw]))
    assert outcome['state']=='succeeded'
    receipt_path=next((tmp_path/'attempts'/job).glob('*/receipt.json'))
    receipt=json.loads(receipt_path.read_bytes());output=receipt_path.with_name('output.json').read_text()
    assert 'extraction' not in receipt and not receipt['baseline_in_model_input']
    assert parent['run_id'] not in receipt_path.with_name('input.txt').read_text()
    worker.verify_receipt(receipt,bundle,output)
    if local_context:
        from ingestion.materials_ner.source_local_audit import local_context as build_context
        assert json.loads(receipt_path.with_name('local-context.json').read_text())==build_context(bundle)
        forged=deepcopy(receipt);forged['local_context_sha256']='0'*64
        with pytest.raises(ValueError,match='local_context_reconstruction'):
            worker.verify_receipt(forged,bundle,output)
    with store.connect() as db,sqlite3.connect(tmp_path/'restored.sqlite3') as backup:
        db.backup(backup);assert not backup.execute('PRAGMA foreign_key_check').fetchall()
        assert backup.execute('SELECT result_hash FROM jobs WHERE id=?',(job,)).fetchone()[0]==digest(receipt)
    forged=deepcopy(receipt);forged['comparison']['unrepresented_result_mentions']=[{'invented':True}]
    with pytest.raises(ValueError,match='comparison_reconstruction'):worker.verify_receipt(forged,bundle,output)
    # A bounded repair sees its own failed audit and diagnostics, never the
    # baseline graph, and cannot silently start a second repair generation.
    bad=deepcopy(raw);bad['mention_decisions'][0].update(kind='condition',item_ids=['absent'])
    bad_config=worker.configuration(parent,reasoning='low',local_context=local_context)
    bad_job=store.enqueue(work_id=bundle.work_id,bundle_hash=digest(bundle.model_dump()),config=bad_config,max_attempts=1)
    assert worker.run_one(store,bad_job,parent,bundle,provider_override=SequenceProvider([bad]))['state']=='quarantined'
    bad_path=next((tmp_path/'attempts'/bad_job).glob('*/receipt.json'));bad_receipt=json.loads(bad_path.read_text())
    repair_parent={'run_id':digest(bad_receipt),'receipt':bad_receipt,'raw_output':bad_path.with_name('output.json').read_text()}
    repair_config=worker.configuration(parent,repair_parent=repair_parent)
    repair_job=store.enqueue(work_id=bundle.work_id,bundle_hash=digest(bundle.model_dump()),config=repair_config,max_attempts=1)
    assert worker.run_one(store,repair_job,parent,bundle,repair_parent=repair_parent,
                          provider_override=SequenceProvider([raw]))['state']=='succeeded'
    repair_path=next((tmp_path/'attempts'/repair_job).glob('*/receipt.json'));fixed=json.loads(repair_path.read_text())
    worker.verify_receipt(fixed,bundle,repair_path.with_name('output.json').read_text())
    prompt=repair_path.with_name('input.txt').read_text()
    assert 'PREVIOUS_SOURCE_AUDIT:' in prompt and parent['run_id'] not in prompt and 'BASE_GRAPH:' not in prompt
    with pytest.raises(ValueError,match='repair_ancestry_invalid'):
        worker.configuration(parent,repair_parent={'run_id':digest(fixed),'receipt':fixed,'raw_output':json.dumps(raw)})
