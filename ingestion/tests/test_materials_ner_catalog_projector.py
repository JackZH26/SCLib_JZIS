"""Original-ID transport tests, using synthetic source text and no real calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ingestion.materials_ner import source_projector as projector, projection_binding as binding
from ingestion.materials_ner import reviewed_reader as reader, scoped_evidence
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.store import Store
from test_materials_ner_reviewed_proposals import prepared, graph
from test_materials_ner_source_projector import Fake


@pytest.fixture
def catalog_case(prepared,tmp_path):
    _,_,scope,bundle,manifest=prepared
    mp=tmp_path/'coverage.json';reader.put(mp,manifest)
    path=tmp_path/'catalog-input.json'
    reader.put(path,dict(schema=projector.INPUT_SCHEMA,scope=reader.reference(scope),
        coverage=reader.reference(mp),evidence_transport='source_catalog'))
    p=projector.prepare(path);g=graph(bundle)
    g['results'][0]['definition']['criterion_raw']='resistive onset'
    for group in binding.GROUPS:
        for entity in g[group]:
            entity['evidence']=[dict(field=e['field'],witness_ids=['E0001']) for e in entity['evidence']]
    g['results'][0]['evidence'] += [dict(field='/quantity/'+key,witness_ids=['E0001']) for key in ['raw','unit']]
    return path,p,g


def test_catalog_interface_is_closed_and_native_science_is_unchanged(catalog_case):
    _,p,g=catalog_case;Draft202012Validator.check_schema(p['schema'])
    assert Draft202012Validator(p['schema']).is_valid(g)
    for change in ['quote','unknown_id','empty_ids','bad_field']:
        bad=deepcopy(g);e=bad['results'][0]['evidence'][0]
        if change=='quote':e['quote']='fabricated'
        elif change=='unknown_id':e['witness_ids']=['E9999']
        elif change=='empty_ids':e['witness_ids']=[]
        else:e['field']='/results/r/quantity'
        assert not Draft202012Validator(p['schema']).is_valid(bad)
    c=binding.compile_catalog_bindings(g,p['bundle'],p['scope'],p['coverage'],p['source_catalog'])
    assert not c['holds'],c
    assert c['scientific_payload_unchanged']
    assert binding.scientific_payload(c['graph'])==binding.scientific_payload(g)
    units=[e for e in c['graph']['results'][0]['evidence'] if e['field']=='/quantity/unit']
    assert len(units)==1 and units[0]['quote']=='K'
    for group in binding.GROUPS:
        for entity in c['graph'][group]:
            for e in entity['evidence']:
                assert set(e)=={'field','block_id','quote','start_char','end_char'}
                block=next(b for b in p['bundle'].blocks if b.id==e['block_id'])
                assert block.text[e['start_char']:e['end_char']]==e['quote']


@pytest.mark.parametrize('failure',['unknown_id','duplicate_id','absent_literal','repeated_literal','clipped_unit','bad_field'])
def test_failed_selections_are_held_without_repairing_scientific_values(catalog_case,failure):
    _,p,g=catalog_case;r=g['results'][0];e=r['evidence'][0]
    if failure=='unknown_id':e['witness_ids']=['E9999']
    elif failure=='duplicate_id':e['witness_ids']=['E0001','E0001']
    elif failure=='absent_literal':r['quantity']['raw']='999 K';r['quantity']['value']=999
    elif failure=='repeated_literal':r['definition']['criterion_raw']='onset'
    elif failure=='clipped_unit':r['quantity']['unit']='esistive'
    else:e['field']='/results/r/quantity_kind'
    c=binding.compile_catalog_bindings(g,p['bundle'],p['scope'],p['coverage'],p['source_catalog'])
    assert c['holds'] and binding.scientific_payload(c['graph'])==binding.scientific_payload(g)


def test_context_only_numeric_evidence_cannot_become_a_target_result(catalog_case):
    _,p,g=catalog_case;scope=deepcopy(p['scope']);scope['passages'][0]['role']='context'
    catalog=scoped_evidence.build(p['bundle'],scope)
    c=binding.compile_catalog_bindings(g,p['bundle'],scope,p['coverage'],catalog)
    assert any(h['code']=='explicit_evidence_selector_invalid' for h in c['holds'])


def test_changed_catalog_fails_closed(catalog_case):
    _,p,g=catalog_case;catalog=deepcopy(p['source_catalog']);catalog['spans']['E0001']['text']='fabricated'
    with pytest.raises(ValueError,match='scoped_catalog_drift'):
        binding.compile_catalog_bindings(g,p['bundle'],p['scope'],p['coverage'],catalog)


def test_catalog_projector_pins_replays_and_does_not_grant_admission(catalog_case,tmp_path):
    path,p,g=catalog_case;store=Store(tmp_path/'catalog-queue');job=projector.enqueue(store,path);fake=Fake(g)
    result=projector.run(store,job,provider_override=fake)
    assert result['state']=='succeeded',result
    assert projector.run(Store(store.root),job,provider_override=fake)==result and fake.calls==1
    assert result['provider_only_locator_fields']==['witness_ids']
    assert json.loads(reader.checked(result['model_graph']).read_text())==g
    assert json.loads(reader.checked(result['source_catalog']).read_text())==p['source_catalog']
    assert not any(result[k] for k in ['paper_completed','proposal_generated','scientific_acceptance','ml_training_eligible'])
    Path(result['source_catalog']['path']).write_text('{}')
    with pytest.raises(ValueError):projector.run(store,job,provider_override=fake)
    assert fake.calls==1


def test_conflicting_transport_is_rejected_before_dispatch(catalog_case):
    path,_,_=catalog_case;r=json.loads(path.read_text());r['require_context_quote']=True;path.write_text(canonical(r))
    with pytest.raises(ValueError,match='conflicting_evidence_transports'):projector.prepare(path)


def test_source_catalog_prompt_has_no_reference_or_quote_locator_instruction(catalog_case):
    _,p,_=catalog_case
    assert 'witness_ids' in p['prompt'] and 'ORIGINAL SOURCE CATALOGUE' in p['prompt']
    assert 'context_quote' not in p['prompt']
    assert p['source_catalog']['reference_answers_used'] is False
