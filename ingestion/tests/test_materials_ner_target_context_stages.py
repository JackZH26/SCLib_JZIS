"""Policy isolation, source fidelity and recovery on the existing stage sequence."""
from copy import deepcopy
import jsonschema
import pytest

from ingestion.materials_ner import target_context_stages as target, frozen_owner_stages as old
from ingestion.materials_ner import selected_catalog_stages as expanded, identity_stages as identity
from ingestion.materials_ner import item_worker, item_flow_v2, staged_revision
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import Inventory, source_text
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.sources import Bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_frozen_owner_stages import typed
from test_materials_ner_item_stages import parent_packet, StageProvider
from test_materials_ner_selected_catalog_stages import failure


def test_old_default_and_new_policy_have_distinct_pinned_prompts(tmp_path):
    parent, *_ = parent_packet(tmp_path/'parent')
    before = item_worker.configuration(parent, workflow=old.WORKFLOW)
    new = item_worker.configuration(parent, workflow=old.WORKFLOW, field_generation_policy=target.POLICY)
    assert new['workflow'] == before['workflow'] == old.WORKFLOW
    assert new['output_format'] == before['output_format'] == old.OUTPUT_FORMAT
    assert new['prompt_sha256'] != before['prompt_sha256']
    assert item_flow_v2.interfaces(new)[0] is target
    assert item_flow_v2.interfaces(before)[0] is old
    assert item_worker.configuration(parent, workflow=old.WORKFLOW) == before
    assert 'max_catalog_completions' not in new
    with pytest.raises(ValueError, match='field_generation_policy_unknown'):
        item_worker.configuration(parent, workflow=identity.WORKFLOW, field_generation_policy=target.POLICY)
    with pytest.raises(ValueError, match='selected_catalog_configuration_mismatch'):
        item_worker.configuration(parent, workflow=expanded.WORKFLOW, field_generation_policy=target.POLICY)


@pytest.mark.parametrize('window', [2, 4])
def test_source_and_all_inventory_coordinates_survive_shorter_declaration_prompt(window):
    case = failure(window); bundle = Bundle.model_validate(case['bundle'])
    inventory = Inventory.model_validate(case['inventory']); before = deepcopy(case)
    prompt = target.render_declarations(bundle, inventory)
    assert source_text(bundle) in prompt
    assert 'SOURCE_TOKEN_INDEX:' not in prompt and 'SOURCE_INVENTORY:' not in prompt
    assert len(prompt) < len(expanded.render_declarations(bundle, inventory))
    ledger = target.inventory_ledger(inventory)
    assert [item['id'] for item in ledger['items']] == [item.id for item in inventory.items]
    assert all(item['source_span_ids'] == original.source_span_ids for item, original in zip(ledger['items'], inventory.items))
    assert case == before
    jsonschema.Draft202012Validator.check_schema(target.declaration_schema(bundle, inventory))


def test_reference_candidates_copy_original_syntax_without_relabelling_authorship():
    bundle = Bundle.model_validate(failure(4)['bundle']); source = source_catalog(bundle)
    before = bundle.model_dump(); rows = target.citation_literals(bundle)
    assert rows
    assert any(row['literal'] == r'\bibitem{upperc}' for row in rows)
    for row in rows:
        assert source['spans'][row['span_id']]['text'][row['start_char']:row['end_char']] == row['literal']
        assert not {'source_role', 'source_id', 'sample_id'} & row.keys()
    assert bundle.model_dump() == before


def test_empty_conditions_and_missing_method_remain_representable_without_fabrication():
    bundle, inventory, declarations, *_ = typed(); raw = declarations.model_dump()
    for sample in raw['samples']:
        for state in sample['states']:
            state['conditions'] = []
            state['evidence'] = [ref for ref in state['evidence'] if all(not p.startswith('/conditions') for p in ref['fields'])]
    for protocol in raw['protocols']:
        protocol.update(method=None, method_class='unspecified', parameters=[])
        protocol['evidence'] = [ref for ref in protocol['evidence'] if all(p not in {'/method'} and not p.startswith('/parameters') for p in ref['fields'])]
    jsonschema.validate(raw, target.declaration_schema(bundle, inventory))
    parsed = target.Declarations.model_validate(raw)
    catalog = target.check_declarations(parsed, inventory, bundle, 64)
    assert all(not state.conditions for state in catalog.states)
    assert all(p.method is None for p in catalog.protocols)


@pytest.mark.parametrize('failure_at', [None, 1, 2, 3, 4, 5, 6])
def test_new_policy_retains_worker_failures_and_exact_private_packet_replay(tmp_path, failure_at):
    parent, *_ = parent_packet(tmp_path/'parent')
    bundle, inventory, declarations, relations, catalog, selection, decisions, links = typed()
    keys = list(decisions)
    outputs = [declarations.model_dump(), relations.model_dump(), selection.model_dump(),
               *[dict(schema_version='materials-source-item-group/1', work_id=bundle.work_id,
                      decisions={k: decisions[k] for k in keys[i:i+4]}) for i in range(0, len(keys), 4)], links]
    store = Store(tmp_path/'target')
    job = item_worker.enqueue(store, parent, workflow=target.WORKFLOW, field_generation_policy=target.POLICY)
    outcome = run_one(store, job_id=job, provider_override=StageProvider(outputs, fail_at=failure_at))
    assert outcome['state'] == ('failed' if failure_at else 'succeeded'), outcome
    packet = import_packet(store, job); verify_packet(packet)
    assert packet['receipt']['config']['field_generation_policy'] == target.POLICY
    assert len(packet['rows']['results']) == {None: 5, 1: 0, 2: 0, 3: 0, 4: 0, 5: 4, 6: 5}[failure_at]
    assert 'catalog-completion' not in [row['name'] for row in packet['receipt']['stages']]
    db = ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    if failure_at is None:
        graph, _ = staged_revision.resolve_parent(packet)
        assert graph.expand(bundle).model_dump() == packet['receipt']['extraction']
        corrupted = deepcopy(packet['receipt']); corrupted['owner_selection_projection']['catalog_sha256'] = '0'*64
        with pytest.raises(ValueError, match='assembly_mismatch'):
            item_worker.verify_receipt(corrupted, bundle, packet['raw_output'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


def test_fabricated_citation_and_duplicate_relations_still_fail_without_repair():
    bundle, inventory, declarations, relations, catalog, selection, *_ = typed()
    selected = selection.model_copy(deep=True)
    chosen = next(iter(selected.decisions.values()))
    chosen.attribution.cited_source_raw = r'\cite{fabricated-not-in-source}'
    with pytest.raises(ValueError, match='citation_not_in_source'):
        target.bind(selected, declarations, relations, inventory, bundle)
    linked = next((use for use in relations.protocol_uses.values() if use.uses), None)
    assert linked is not None
    linked.uses.append(linked.uses[0].model_copy(deep=True))
    with pytest.raises(ValueError, match='use_not_in_frozen_declarations'):
        target.project(declarations, relations, bundle)
