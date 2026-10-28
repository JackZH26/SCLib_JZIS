"""Source domain ranges are not silently promoted to measurement conditions."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import parse_extraction
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.sources import make_blocks, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.wire_v8 import RelationalExtraction
from ingestion.materials_ner.wire_v9 import ScopedExtraction, output_schema, validate_coverage
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_relations import fixture as relation_fixture


def fixture():
    bundle, inventory, raw = relation_fixture()
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic:1", bundle.blocks[0].text +
        " The phase extends over 10 to 30 GPa. The fit uses temperatures from 20 to 70 K.")])
    raw['schema_version'] = 'materials-ner-shared/5'
    for index, (role, kind, unit, lo, hi, wording) in enumerate([
        ('study_extent', 'pressure', 'GPa', 10, 30, '10 to 30 GPa'),
        ('fit_window', 'temperature', 'K', 20, 70, '20 to 70 K'),
    ], 1):
        raw['states'][0]['conditions'].append({'id': role, 'kind': kind, 'role': role,
            'quantity': {'status': 'reported', 'raw': wording, 'relation': 'interval', 'value': None,
                'lower': lo, 'upper': hi, 'unit': unit, 'approximate': False, 'uncertainty': None},
            'orientation_raw': None, 'basis_raw': None, 'window_position': None})
        raw['states'][0]['evidence'][0]['fields'].append(f'/conditions/{index}')
    return bundle, inventory, raw


def test_versioned_scope_roles_preserve_source_ranges_without_changing_old_contract():
    bundle, inventory, raw = fixture()
    schema = output_schema(bundle, Inventory.model_validate(inventory))
    jsonschema.Draft202012Validator.check_schema(schema); jsonschema.validate(raw, schema)
    wire = ScopedExtraction.model_validate(raw); extraction = wire.expand(bundle)
    assert validate_extraction(extraction, bundle)['valid']
    assert validate_coverage(wire, Inventory.model_validate(inventory), bundle)['valid']
    assert parse_extraction(extraction.model_dump()).model_dump() == extraction.model_dump()
    selected = [c.model_dump() for c in extraction.states[0].conditions[1:]]
    assert selected == raw['states'][0]['conditions'][1:]
    assert all(c['quantity']['value'] is None and c['window_position'] is None for c in selected)
    assessment = training_exclusions(extraction, bundle, validate_extraction(extraction, bundle))
    assert all('measurement_pressure_unknown' in row['reason_codes'] for row in assessment['results'])
    old = deepcopy(raw); old['schema_version'] = 'materials-ner-shared/4'
    with pytest.raises(ValidationError): RelationalExtraction.model_validate(old)


@pytest.mark.parametrize('role', ['study_extent', 'fit_window'])
def test_source_domain_never_counts_as_reported_non_detection_window(role):
    bundle, inventory, raw = fixture()
    observation = raw['observations'][0]
    observation['result'].update(quantity_kind='non_detection',
        quantity={'status': 'not_applicable', 'raw': None, 'relation': None, 'value': None, 'lower': None,
                  'upper': None, 'unit': None, 'approximate': False, 'uncertainty': None},
        qualifiers=[{'kind': 'non_detection', 'target': 'superconductivity', 'observable': 'unspecified',
                     'existence': 'not_established', 'raw': 'No superconductivity was detected.', 'window_status': 'reported'}])
    raw['states'][0]['conditions'][2]['role'] = role
    extraction = ScopedExtraction.model_validate(raw).expand(bundle)
    checked = validate_extraction(extraction, bundle)
    assert 'reported_detection_window_missing' in {r['code'] for r in checked['issues']}
    assert all(not row['eligible'] for row in training_exclusions(extraction, bundle, checked)['results'])


def test_scope_role_cannot_use_a_detection_endpoint_marker():
    bundle, _, raw = fixture()
    raw['states'][0]['conditions'][2]['window_position'] = 'interval'
    checked = validate_extraction(ScopedExtraction.model_validate(raw).expand(bundle), bundle)
    assert 'window_position_outside_detection_context' in {r['code'] for r in checked['issues']}


def test_worker_archive_roundtrip_preserves_new_roles_and_relationship_closure(tmp_path):
    bundle, inventory, raw = fixture(); store = Store(tmp_path)
    bundle_hash, _ = save_bundle(tmp_path, bundle)
    config = configuration(workflow='inventory_v9')
    assert config['max_evidence_patches'] == config['max_extraction_repairs'] == 0
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=config)
    result = run_one(store, job_id=job, provider_override=SequenceProvider([inventory, raw]))
    assert result['state'] == 'succeeded'
    packet = import_packet(store, job); verify_packet(packet)
    assert packet['schema'] == 'materials-ner-proposals/2'
    assert packet['receipt']['extraction']['schema_version'] == 'materials-ner/7'
    database = ProposalDatabase(tmp_path / 'proposals')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        stored = json.loads(connection.execute('SELECT payload FROM runs').fetchone()[0])
        assert stored == packet
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


@pytest.mark.parametrize('wire_version', ['legacy', 'scoped'])
@pytest.mark.parametrize('kind', ['unresolved', 'bulk'])
def test_unknown_sample_kind_is_not_a_positive_assertion_but_known_kinds_need_evidence(wire_version, kind):
    bundle, inventory, raw = relation_fixture() if wire_version == 'legacy' else fixture()
    raw['samples'][0]['target_kind'] = kind
    for binding in raw['samples'][0]['evidence']:
        binding['fields'] = [field for field in binding['fields'] if field != '/target_kind']
    raw['samples'][0]['evidence'] = [binding for binding in raw['samples'][0]['evidence'] if binding['fields']]
    model = RelationalExtraction if wire_version == 'legacy' else ScopedExtraction
    checked = validate_extraction(model.model_validate(raw).expand(bundle), bundle)
    missing = {'code':'field_evidence_missing', 'path':'/samples/0/target_kind'}
    assert (missing in checked['issues']) == (kind != 'unresolved')
    if kind == 'unresolved':
        assert checked['valid']
        assert not any(row['eligible'] for row in training_exclusions(model.model_validate(raw).expand(bundle),bundle,checked)['results'])
