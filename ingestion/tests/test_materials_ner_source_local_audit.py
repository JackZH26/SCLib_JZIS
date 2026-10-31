"""Literal local context preserves numeric occurrence identities without labels."""
import json
from types import SimpleNamespace
import pytest
from ingestion.materials_ner import source_local_audit as local
from ingestion.materials_ner import source_mentions as base
from ingestion.materials_ner import source_audit_worker as worker
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.inventory import Inventory
from test_materials_ner_source_mentions import fixture


def test_each_display_context_is_exact_original_text_at_its_own_occurrence():
    bundle,manifest,_,_=fixture();context=local.local_context(bundle)
    assert context['mention_manifest_sha256']==digest(manifest)
    assert not context['contains_scientific_labels'] and not context['baseline_included']
    assert len(context['occurrences'])==len(manifest['mentions'])
    blocks={b.id:b for b in bundle.blocks}
    for occurrence,original in zip(context['occurrences'],manifest['mentions']):
        assert all(occurrence[k]==v for k,v in original.items())
        text=blocks[occurrence['block_id']].text
        assert occurrence['context_quote']==text[occurrence['context_start_char']:occurrence['context_end_char']]
        assert occurrence['left_context']+occurrence['text']+occurrence['right_context']==occurrence['context_quote']
    twos=[o for o in context['occurrences'] if o['text']=='2']
    assert len(twos)==3 and len({o['start_char'] for o in twos})==3
    assert twos[0]['left_context'].endswith('K-') and twos[-1]['left_context'].endswith('Figure ')


def test_prompt_displays_all_ids_once_without_prior_or_scientific_reference_labels():
    bundle,manifest,_,_=fixture();prompt=local.render(bundle)
    rows=[json.loads(line.removeprefix('NUMERIC_OCCURRENCE: ')) for line in prompt.splitlines() if line.startswith('NUMERIC_OCCURRENCE: ')]
    assert [r['id'] for r in rows]==[m['id'] for m in manifest['mentions']]
    assert all('kind' not in r and 'item_ids' not in r for r in rows)
    assert 'FIRST_READ_INVENTORY' not in prompt and 'BASE_GRAPH' not in prompt
    assert local.render(bundle)==prompt
    assert local.PROMPT_HASH!=base.PROMPT_HASH


def test_repair_diagnostics_identify_disconnected_item_without_rewriting_it():
    bundle,_,_,raw=fixture()
    raw['mention_decisions'][0]['item_ids']=['I5']
    checked=base.validate_audit(base.MentionAudit.model_validate(raw),bundle)
    assert not checked['valid']
    details=local.item_diagnostics(raw,bundle);first=details[0]
    assert first['item_id']=='I1' and first['value_raw']=='0.25 nΩ m K-2'
    assert first['literal_possible_mention_ids'] and first['linked_mention_ids']==[]
    fifth=details[4]
    assert set(fifth['linked_mention_ids'])-set(fifth['literal_possible_mention_ids'])
    prompt=local.render_repair(bundle,raw,checked)
    assert 'ITEM_LINK_DIAGNOSTICS:' in prompt and 'PREVIOUS_SOURCE_AUDIT:' in prompt
    assert raw['mention_decisions'][0]['item_ids']==['I5']


def test_unknown_context_contract_is_not_silently_legacy():
    with pytest.raises(ValueError,match='context_format_unknown'):
        worker._format({'source_context_format':'invented'})


def test_textual_qualitative_result_cannot_vanish_from_comparison():
    bundle,_,inventory,raw=fixture()
    raw['items'].append({'id':'I6','sample_raw':'FeSe0.9','quantity_name_raw':'literal qualitative fixture',
        'value_raw':'decreases','source_span_ids':['S1'],'context_span_ids':[]})
    raw['span_dispositions'][0]['item_ids'].append('I6')
    candidate=base.MentionAudit.model_validate(raw)
    graph=SimpleNamespace(additional_items=[],model_dump=lambda:{'additional_items':[]})
    assert base.validate_audit(candidate,bundle)['valid']
    legacy=worker._compare({},candidate,Inventory.model_validate(inventory),graph,bundle)
    assert legacy['qualitative_items_requiring_semantic_comparison']==[]
    fixed=worker._compare({'audit_comparison_version':'materials-source-audit-comparison/2'},
                          candidate,Inventory.model_validate(inventory),graph,bundle)
    assert fixed['schema']=='materials-source-audit-comparison/2'
    assert [i['id'] for i in fixed['qualitative_items_requiring_semantic_comparison']]==['I6']
    assert fixed['population_recall_estimate'] is None and not fixed['scientific_acceptance']
    with pytest.raises(ValueError,match='comparison_version_unknown'):
        worker._compare({'audit_comparison_version':'invented'},candidate,Inventory.model_validate(inventory),graph,bundle)
