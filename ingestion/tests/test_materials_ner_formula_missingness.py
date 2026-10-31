"""Unknown formula and unknown specimen survive without fabricated chemistry."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import canonical, parse_extraction
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.wire_v11 import AccountedExtraction as OldAccounted
from ingestion.materials_ner.wire_v12 import AccountedExtraction, output_schema, verify_extraction
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_accounting import fixture as old_fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def fixture(*,missing=True,status='ambiguous'):
    bundle,inventory,raw,_=old_fixture()
    raw['schema_version']='materials-ner-shared/8'
    for sample in raw['samples']:
        sample['formula_unavailability']=None
        if missing:
            sample.update(formula_raw=None,composition_basis='unresolved',identity_resolution='unresolved',
                formula_unavailability=dict(status=status,explanation='The contextual formula is not assigned to this reported specimen.',
                    checked_block_ids=list(source_catalog(bundle)['blocks'])))
            for ref in sample['evidence']:
                ref['fields']=[x for x in ref['fields'] if x!='/formula_raw' and x!='/composition_basis']
            sample['evidence']=[ref for ref in sample['evidence'] if ref['fields']]
    return bundle,inventory,raw


def expand(raw,inventory,bundle):
    return AccountedExtraction.parse_response(canonical(raw)).project(inventory,bundle)[0].expand(bundle)


def test_new_schema_round_trip_preserves_unknown_and_all_reported_values():
    bundle,inventory,raw=fixture();before=deepcopy(raw)
    schema=output_schema(bundle,inventory);jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw,schema)
    graph=expand(raw,inventory,bundle)
    assert graph.schema_version=='materials-ner/9' and graph.samples[0].formula_raw is None
    assert graph.samples[0].identity_resolution=='unresolved'
    assert graph.samples[0].formula_unavailability.checked_block_ids==[b.id for b in bundle.blocks]
    assert parse_extraction(graph.model_dump())==graph and raw==before
    _,_,old,_=old_fixture();old_graph=OldAccounted.model_validate(old).project(inventory,bundle)[0].expand(bundle)
    assert [r.model_dump() for r in graph.results]==[r.model_dump() for r in old_graph.results]
    assert validate_extraction(graph,bundle)['valid']
    reasons=training_exclusions(graph,bundle,validate_extraction(graph,bundle))['results'][0]['reason_codes']
    assert 'formula_unavailable_ambiguous' in reasons and 'sample_identity_unresolved' in reasons


def test_named_subject_and_formula_knowledge_are_separate():
    bundle,inventory,raw=fixture();raw['samples'][0]['identity_resolution']='source_scoped'
    graph=expand(raw,inventory,bundle);reasons=training_exclusions(graph,bundle,validate_extraction(graph,bundle))['results'][0]['reason_codes']
    assert 'formula_unavailable_ambiguous' in reasons
    assert 'sample_identity_unresolved' not in reasons


def test_known_formula_keeps_existing_graph_meaning_and_legacy_rejects_new_null():
    bundle,inventory,raw=fixture(missing=False);graph=expand(raw,inventory,bundle)
    _,_,old,_=old_fixture();old_graph=OldAccounted.model_validate(old).project(inventory,bundle)[0].expand(bundle).model_dump()
    new=graph.model_dump();new['schema_version']='materials-ner/8'
    for sample in new['samples']:sample.pop('formula_unavailability')
    assert new==old_graph
    unknown=expand(fixture()[2],inventory,bundle).model_dump();unknown['schema_version']='materials-ner/8'
    for sample in unknown['samples']:sample.pop('formula_unavailability')
    with pytest.raises(ValidationError):parse_extraction(unknown)


@pytest.mark.parametrize('status',['not_extracted','not_accessible','ambiguous','conflicted','not_reported_in_supplied_source'])
def test_missingness_states_are_retained_and_never_qualified(status):
    bundle,inventory,raw=fixture(status=status);graph=expand(raw,inventory,bundle)
    assert graph.samples[0].formula_unavailability.status==status
    assert all(not r['eligible'] for r in training_exclusions(graph,bundle,validate_extraction(graph,bundle))['results'])


@pytest.mark.parametrize('mutation,code',[
    ('no_status','formula_value_missingness_mismatch'),
    ('present_with_status','formula_value_missingness_mismatch'),
    ('selected_basis','missing_formula_cannot_have_selected_basis'),
    ('empty_scope_absence','formula_source_absence_requires_complete_supplied_scope'),
    ('duplicate_scope','formula_checked_scope_invalid'),
    ('unread_scope','formula_checked_scope_not_read')])
def test_unavailable_formula_does_not_allow_false_absence_or_basis(mutation,code):
    bundle,inventory,raw=fixture();sample=raw['samples'][0]
    if mutation=='no_status':sample['formula_unavailability']=None
    if mutation=='present_with_status':sample['formula_raw']='Nb'
    if mutation=='selected_basis':sample['composition_basis']='nominal'
    if mutation=='empty_scope_absence':sample['formula_unavailability'].update(status='not_reported_in_supplied_source',checked_block_ids=[])
    if mutation=='duplicate_scope':sample['formula_unavailability']['checked_block_ids']*=2
    if mutation=='unread_scope':raw['unread_block_ids']=raw['processed_block_ids'];raw['processed_block_ids']=[]
    with pytest.raises(ValidationError,match=code):expand(raw,inventory,bundle)


@pytest.mark.parametrize('placeholder',['unknown','unspecified','not reported','sample unspecified','n/a',' '])
def test_placeholder_is_never_a_chemical_formula(placeholder):
    bundle,inventory,raw=fixture(missing=False);raw['samples'][0]['formula_raw']=placeholder
    with pytest.raises(ValidationError,match='formula_placeholder_is_not_chemistry'):expand(raw,inventory,bundle)


def test_missingness_read_scope_cannot_reference_a_foreign_block():
    bundle,inventory,raw=fixture();raw['samples'][0]['formula_unavailability']['checked_block_ids']=['invented']
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw,output_schema(bundle,inventory))
    with pytest.raises(KeyError):expand(raw,inventory,bundle)


def test_real_worker_interface_and_private_storage_replay_null_formula(tmp_path):
    bundle,inventory,raw=fixture();store=Store(tmp_path);key,_=save_bundle(tmp_path,bundle)
    cfg=configuration(workflow='inventory_v12');assert cfg['output_format']=='materials-ner-shared/8'
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=key,config=cfg)
    result=run_one(store,job_id=job,provider_override=SequenceProvider([inventory.model_dump(),raw]))
    assert result['state']=='succeeded',result
    packet=import_packet(store,job);verify_packet(packet)
    assert packet['rows']['samples'][0]['payload']['formula_raw'] is None
    assert packet['schema']=='materials-ner-proposals/2'
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as connection:
        retained=json.loads(connection.execute('select payload from samples limit 1').fetchone()[0])['payload']
        assert retained['formula_raw'] is None and retained['formula_unavailability']['status']=='ambiguous'
        assert not connection.execute('pragma foreign_key_check').fetchall()
    changed=deepcopy(packet['receipt']);changed['extraction']['samples'][0]['formula_raw']='Nb'
    with pytest.raises(ValueError,match='accounted_extraction_reconstruction_mismatch'):
        verify_extraction(changed,bundle,canonical(raw))
    from ingestion.materials_ner.item_worker import verify_parent
    with pytest.raises(ValueError,match='staged_inventory_parent_format_not_supported'):
        verify_parent(packet)
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
