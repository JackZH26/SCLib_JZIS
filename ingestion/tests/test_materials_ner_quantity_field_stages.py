"""Actual dimension failure, source units, table headers and unchanged replay."""
from copy import deepcopy
import json

import jsonschema
import pytest

from materials_private_fixtures import private_json

from ingestion.materials_ner import identity_stages as identity, item_stages as items, item_worker
from ingestion.materials_ner import owner_witness_stages as previous, quantity_field_stages as coupled, staged_revision
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.sources import Bundle
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_identity_stages import fixture
from test_materials_ner_item_stages import parent_packet, StageProvider


def failed_case(window=2, policy='source_fields_v2'):
    raw = next(c for c in private_json('materials_ner_quantity_state_failures.json')['cases'] if c['window']==window and c['policy']==policy)
    bundle = Bundle.model_validate(raw['bundle']); inventory = Inventory.model_validate(raw['inventory'])
    owned = identity.OwnedDeclarations.model_validate(raw['outputs']['declarations'])
    relations = identity.Relations.model_validate(raw['outputs']['catalog-relations'])
    catalog, _ = identity.project(identity.body(owned), relations, bundle)
    plan = identity.project_owners(owned, inventory, bundle)
    group = items.ItemGroup.model_validate(raw['outputs']['items-1'])
    return bundle, inventory, owned, relations, catalog, plan, group


def schema_for(parts, policy=coupled):
    bundle, inventory, _, _, catalog, plan, group = parts
    all_items, _ = items.inventory_items(inventory, catalog)
    return policy.item_schema(bundle, catalog, list(group.decisions), all_items, plan=plan)


def test_actual_pressure_with_tesla_is_rejected_before_generation_without_rewriting_the_old_output():
    parts = failed_case(); group = parts[-1]; original = deepcopy(group.model_dump())
    jsonschema.validate(original, schema_for(parts,previous))
    schema = schema_for(parts);jsonschema.Draft202012Validator.check_schema(schema)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(original,schema)
    result = original['decisions']['I1']['observation']['result']
    assert result['quantity_kind']=='critical_pressure' and result['quantity']['raw']=='6 T'
    result['quantity_kind']='hc2'
    jsonschema.validate(original,schema)
    # No new source data or scientific interpretation is written by schema construction.
    assert group.decisions['I1'].observation.result.quantity_kind=='critical_pressure'


@pytest.mark.parametrize('kind,unit,allowed', [('hc2','T',True),('unmapped','T',True),
    ('pauli_limit_flux_density','T',True),('hc2','mT',False),('critical_pressure','GPa',False),
    ('critical_pressure','T',False),('tc','K',False),('hc2_field_strength','Oe',False)])
def test_literal_source_unit_cannot_be_rescaled_or_changed_to_fit_a_kind(kind,unit,allowed):
    parts=failed_case();data=parts[-1].model_dump();result=data['decisions']['I1']['observation']['result']
    result['quantity_kind']=kind;result['quantity']['unit']=unit
    validator=jsonschema.Draft202012Validator(schema_for(parts))
    assert validator.is_valid(data) is allowed


def test_different_units_on_one_owner_group_are_not_conflated():
    parts=failed_case(4);schema=schema_for(parts);group=parts[-1].model_dump()
    jsonschema.validate(group,schema)
    group['decisions']['I3']['observation']['result']['quantity']['unit']='T'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(group,schema)
    assert coupled.explicit_source_unit(parts[0],parts[1].items[0])['unit_literal']=='T'
    assert coupled.explicit_source_unit(parts[0],parts[1].items[2])['unit_literal']=='K'


@pytest.mark.parametrize('raw', ['6', 'T -> 0', '6 T/2 T', 'fabricated 6 GPa', None])
def test_bare_table_or_unsupported_literal_has_no_inferred_unit(raw):
    bundle,inventory,*_=failed_case();item=inventory.items[0].model_copy(update=dict(value_raw=raw))
    assert coupled.explicit_source_unit(bundle,item) is None


@pytest.mark.parametrize('kind,unit,valid', [('hc2','T',True),('critical_pressure','GPa',True),
    ('tc','K',True),('critical_pressure','T',False),('hc2','K',False),('unmapped','unregistered-source-unit',True)])
def test_table_header_path_keeps_registered_dimensions_and_unmapped_values(kind,unit,valid):
    parts=list(failed_case());parts[1].items[0].value_raw='6'
    data=parts[-1].model_dump();result=data['decisions']['I1']['observation']['result']
    result['quantity_kind']=kind;result['quantity'].update(raw='6',unit=unit)
    assert jsonschema.Draft202012Validator(schema_for(parts)).is_valid(data) is valid


@pytest.mark.parametrize('quantity',[
    dict(raw='approximately 6 T',relation='exact',value=6,lower=None,upper=None,approximate=True,uncertainty=None),
    dict(raw='4 to 6 T',relation='interval',value=None,lower=4,upper=6,approximate=False,uncertainty=None),
    dict(raw='<= 6 T',relation='le',value=None,lower=None,upper=6,approximate=False,uncertainty=None),
    dict(raw='6 +/- 1 T',relation='exact',value=6,lower=None,upper=None,approximate=False,
         uncertainty=dict(kind='reported_unspecified',minus=1,plus=1,level=None,raw='+/- 1')),
])
def test_shape_constraints_are_preserved_rather_than_replacing_quantities_with_scalar_defaults(quantity):
    parts=failed_case();data=parts[-1].model_dump();result=data['decisions']['I1']['observation']['result']
    result['quantity_kind']='hc2';result['quantity'].update(quantity)
    # Check against the inherited branch too: this test concerns unchanged shape constraints.
    before=jsonschema.Draft202012Validator(schema_for(parts,previous)).is_valid(data)
    after=jsonschema.Draft202012Validator(schema_for(parts)).is_valid(data)
    assert before and after
    result['quantity']['value']=999;result['quantity']['lower']=2;result['quantity']['upper']=3
    assert not jsonschema.Draft202012Validator(schema_for(parts)).is_valid(data)


def test_missing_quantity_and_non_detection_branches_survive():
    parts=failed_case();data=parts[-1].model_dump();result=data['decisions']['I1']['observation']['result']
    result['quantity_kind']='unmapped'
    result['quantity'].update(status='ambiguous',value=None,lower=None,upper=None,relation=None,uncertainty=None)
    jsonschema.validate(data,schema_for(parts))
    schema=previous.item_schema();old=next(b for b in schema['$defs']['ObservationResult']['anyOf'] if b['properties']['quantity_kind']['enum']==['non_detection'])
    result_schema=coupled.coupled_result_schema(schema['$defs']['ObservationResult'],schema['$defs'])
    assert next(b for b in result_schema['anyOf'] if b['properties']['quantity_kind']['enum']==['non_detection'])==old


def test_schema_compaction_preserves_reachable_references_and_inventory_bytes():
    parts=failed_case(4);before=digest(parts[1].model_dump());schema=schema_for(parts)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert 'OwnedResult1' not in schema['$defs'] and 'ObservationResult' not in schema['$defs']
    assert digest(parts[1].model_dump())==before
    assert len(json.dumps(schema))<len(json.dumps(schema_for(parts,previous)))


@pytest.mark.parametrize('failure',[None,2,4])
def test_worker_archive_and_revision_keep_the_policy_and_all_failed_attempts(tmp_path,failure):
    parent,_,_,_,_=parent_packet(tmp_path/'parent');bundle,inventory,raw,relations,decisions,links=fixture();keys=list(decisions)
    outputs=[raw,relations,*[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
        decisions={k:decisions[k] for k in keys[i:i+4]}) for i in range(0,len(keys),4)],links]
    store=Store(tmp_path/'staged');job=item_worker.enqueue(store,parent,workflow=identity.WORKFLOW,field_generation_policy=coupled.POLICY)
    outcome=run_one(store,job_id=job,provider_override=StageProvider(outputs,fail_at=failure))
    assert outcome['state']==('failed' if failure else 'succeeded'),outcome
    packet=import_packet(store,job);verify_packet(packet)
    assert packet['receipt']['config']['prompt_version']==coupled.PROMPT_VERSION
    db=ProposalDatabase(tmp_path/'private');assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    if not failure:
        graph,_=staged_revision.resolve_parent(packet);assert graph.expand(bundle).model_dump()==packet['receipt']['extraction']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
