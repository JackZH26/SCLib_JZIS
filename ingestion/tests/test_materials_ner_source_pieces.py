"""Authored multipart source, uncertainty and native transport regressions."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner import source_piece_inventory as pieces, source_keyed_inventory as keyed
from ingestion.materials_ner import source_role_inventory as role, page_images, item_worker, frozen_inventory
from ingestion.materials_ner import typed_inventory_handoff as handoff
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.sources import Block, sha
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_source_keyed import fixture as keyed_fixture
from test_materials_ner_item_stages import StageProvider, responses


def fixture(pdf=False, continuation=False):
    original, bundle, scope, old, bindings, rest = keyed_fixture(pdf)
    if continuation:
        text = 'For Sample A, this absence refers only to the stated supercurrent detection window.'
        original.blocks.append(Block(id='B_CONTEXT', document_id=original.documents[0].id,
            ordinal=1, locator='pdf_page:2' if pdf else 'page:2', text=text, sha256=sha(text.encode())))
        bundle, scope = role.scope(original, [original.blocks[0].id])
    cat = role.selection_catalog(bundle)
    def selected(selection):
        if selection is None:
            return []
        first = cat['texts'][selection.first_text_id]
        last = cat['texts'][selection.last_text_id or selection.first_text_id]
        return [key for key, row in cat['texts'].items() if row['block_id'] == first['block_id']
            and first['start_char'] <= row['start_char'] and row['end_char'] <= last['end_char']]
    def record(value, anchor=None):
        row = dict(sample_description=value.sample_description, property_text_ids=selected(value.property_evidence),
            subject_text_ids=list(dict.fromkeys(key for s in value.subject_evidence for key in selected(s))),
            support_text_ids=value.support_text_ids, context_kind=value.context_kind, description=value.description)
        if anchor is not None:
            row.update(continuation_text_ids=selected(value.statement)[1:], value_status=value.value_status)
        elif isinstance(value, role.ContextSelection):
            row['role'] = value.role
        return row
    numeric = {key: dict(disposition='outcome', records=[record(r) for r in entry.records])
        if entry.disposition == 'outcome' else entry.model_dump() for key, entry in old.numeric.items()}
    text = {key: dict(review=value.review, reason=value.reason,
        unvalued_records=[record(r, key) for r in value.unvalued_records]) for key, value in old.text.items()}
    plan = pieces.KeyedPlan(schema_version=pieces.VERSION, work_id=bundle.work_id,
        catalog_sha256=cat['catalog_sha256'], completion_state='complete', numeric=numeric, text=text,
        additional_numeric=[], contexts=[record(value) for value in old.contexts], limitations=[])
    if continuation:
        key = next(key for key, row in cat['texts'].items() if row['block_id'] == 'B_CONTEXT')
        unvalued = next(value.unvalued_records[0] for value in plan.text.values() if value.unvalued_records)
        unvalued.continuation_text_ids = [key]
        unvalued.property_text_ids.append(key)
        unvalued.subject_text_ids.append(key)
        # The authored provider must acknowledge the added context block;
        # keeping its old one-block receipt correctly triggers quarantine.
        rest = deepcopy(rest)
        rest[0]['processed_block_ids'] = list(source_catalog(bundle)['blocks'])
    projected, _ = pieces.project_plan(plan, bundle)
    selected_plan, _ = keyed.project_plan(projected, bundle)
    binding = pieces.KeyedBindings(schema_version=pieces.BINDING, work_id=bundle.work_id,
        plan_sha256=digest(plan.model_dump()), decisions=bindings.decisions,
        coverage_checks={key: dict(decision='non_outcome_supported', reason='Authored source review.')
            for key in role.selected_coverage(selected_plan, cat)})
    return original, bundle, scope, plan, binding, rest


def snapshot(pdf=False, continuation=False):
    from test_materials_ner_page_images import png
    original, bundle, scope, plan, bindings, rest = fixture(pdf, continuation)
    images = page_images.freeze(original, [] if not pdf else [dict(
        pdf_sha256=original.documents[0].source_sha256, pdf_page=1,
        rendering={'producer': 'authored-fixture'}, raw=png())])
    inputs = [dict(path='/authored/' + row['image_id'] + '.png',
        **{key: row[key] for key in ['image_id', 'sha256', 'width', 'height', 'media_type']}) for row in images['pages']]
    model, inventory, proof = pieces.compile(plan, bindings, bundle)
    captures = dict(original_bundle=canonical(original.model_dump()), source_bundle=canonical(bundle.model_dump()),
        source_catalog=canonical(source_catalog(bundle)), scope=canonical(scope),
        numeric_catalog=canonical(role.catalog(bundle)), selection_catalog=canonical(role.selection_catalog(bundle)),
        source_layout='null', page_images=canonical(images),
        role_image_inputs=canonical(page_images.receipt(inputs)), binding_image_inputs=canonical(page_images.receipt(inputs)),
        role_prompt=pieces.render(original, bundle, scope, images), role_schema=canonical(pieces.output_schema(bundle)),
        role_raw=canonical(plan.model_dump()), role_plan=canonical(plan.model_dump()), role_validation=canonical(proof['piece_validation']),
        binding_prompt=pieces.render_bindings(original, bundle, scope, plan, images),
        binding_schema=canonical(pieces.binding_schema(bundle, plan)), binding_raw=canonical(bindings.model_dump()),
        bindings=canonical(bindings.model_dump()), typed_inventory=canonical(model.model_dump()),
        inventory=canonical(inventory.model_dump()), projection=canonical(proof),
        validation=canonical(proof['typed_projection']['validation']))
    receipt = dict(schema=pieces.ATTEMPT, work_id=bundle.work_id, status='source_piece_inventory_valid',
        terminal=True, provider_calls=2, source_unchanged=True, scientific_acceptance=False,
        full_graph_extraction=False, item_count=len(inventory.items),
        **{key: dict(path='/authored/' + key, sha256=sha(raw.encode())) for key, raw in captures.items()})
    parent = handoff.build(bundle, receipt_raw=canonical(receipt), captures=captures)
    return bundle, parent, receipt, captures, rest


def test_no_endpoint_pairs_and_context_page_continuation_keeps_every_original_piece():
    original, bundle, scope, plan, bindings, _ = fixture(continuation=True)
    schema = pieces.output_schema(bundle)
    assert 'first_text_id' not in canonical(schema) and 'last_text_id' not in canonical(schema)
    jsonschema.validate(plan.model_dump(), schema)
    jsonschema.validate(bindings.model_dump(), pieces.binding_schema(bundle, plan))
    validation = pieces.inspect(plan, bundle)
    assert validation['valid'], validation
    model, inventory, proof = pieces.compile(plan, bindings, bundle)
    assert [entry.value_raw for entry in model.entries[:-1]] == ['39 K', '37 K', '8 nm', '8 nm']
    last = proof['source_piece_ledger']['A5']
    statement = [p for p in last['pieces'] if p['purpose'] == 'statement']
    assert len(statement) == 2 and [p['source']['target'] for p in statement] == [True, False]
    assert [p['ordinal'] for p in statement] == [1, 2]
    assert len({p['source']['block_id'] for p in statement}) == 2
    assert last['inventory_item_id'] == 'I5' and not last['continuous_combined_quote_created']
    assert model.entries[-1].statement_raw == statement[0]['source']['quote']
    assert set(statement[1]['source']['source_span_ids']) <= set(inventory.items[-1].context_span_ids)
    assert not set(statement[1]['source']['source_span_ids']) & set(inventory.items[-1].source_span_ids)
    assert proof['all_evidence_pieces_retained'] and proof['legacy_statement_raw_is_target_anchor']
    for row in proof['source_piece_ledger'].values():
        for piece in row['pieces']:
            source = piece['source']
            block = next(b for b in original.blocks if b.id == source['block_id'])
            assert block.text[source['start_char']:source['end_char']] == source['quote']
    assert not proof['scientific_acceptance'] and not scope['full_source_coverage_established']


@pytest.mark.parametrize('field', ['property_text_ids', 'subject_text_ids', 'support_text_ids', 'continuation_text_ids'])
def test_unknown_and_duplicate_piece_ids_fail_independently(field):
    _, bundle, _, plan, _, _ = fixture()
    row = next(value.unvalued_records[0] for value in plan.text.values() if value.unvalued_records)
    setattr(row, field, ['T_UNKNOWN'])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan.model_dump(), pieces.output_schema(bundle))
    result = pieces.inspect(plan, bundle)
    assert not result['valid'] and any(x['code'] == 'piece_source_invalid' for x in result['issues'])
    setattr(row, field, [next(iter(plan.text))] * 2)
    result = pieces.inspect(plan, bundle)
    assert not result['valid'] and any(x['code'] == 'piece_duplicate_source' for x in result['issues'])


def test_bad_property_subject_and_continuation_are_all_diagnosed():
    _, bundle, _, plan, _, _ = fixture()
    row = next(value.unvalued_records[0] for value in plan.text.values() if value.unvalued_records)
    row.property_text_ids = ['T_BAD_PROPERTY']
    row.subject_text_ids = ['T_BAD_SUBJECT']
    row.continuation_text_ids = ['T_BAD_CONTINUATION']
    issues = [x for x in pieces.inspect(plan, bundle)['issues'] if x['code'] == 'piece_source_invalid']
    assert {x['path'].rsplit('/', 1)[-1] for x in issues} == {'property', 'subject', 'statement'}


def test_unknown_additional_numeric_key_keeps_structured_diagnostics_in_both_contracts():
    _, bundle, _, old, _, _ = keyed_fixture()
    record = next(e.records[0] for e in old.numeric.values() if e.disposition == 'outcome')
    old.additional_numeric = [keyed.AdditionalNumeric(numeric_candidate_id='N999999', records=[record])]
    result = keyed.inspect(old, bundle)
    assert not result['valid'] and any(x['code'] == 'keyed_additional_numeric_identity' for x in result['issues'])
    assert any(x.get('detail') == 'selection_numeric_invalid' for x in result['issues'])
    _, bundle, _, plan, _, _ = fixture()
    record = next(e.records[0] for e in plan.numeric.values() if e.disposition == 'outcome')
    plan.additional_numeric = [pieces.AdditionalNumeric(numeric_candidate_id='N999999', records=[record])]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan.model_dump(), pieces.output_schema(bundle))
    result = pieces.inspect(plan, bundle)
    assert not result['valid'] and any(x.get('detail') == 'keyed_additional_numeric_identity' for x in result['issues'])


@pytest.mark.parametrize('variant', ['partial', 'insufficient_source', 'missing_text', 'missing_numeric', 'wrong_hash', 'repeat_anchor', 'empty_property', 'old_endpoints'])
def test_incomplete_or_obsolete_output_never_reaches_binding(variant):
    _, bundle, _, plan, _, _ = fixture()
    if variant == 'empty_property':
        raw = plan.model_dump()
        next(e for e in raw['numeric'].values() if e['disposition'] == 'outcome')['records'][0]['property_text_ids'] = []
        with pytest.raises(ValueError):
            pieces.KeyedPlan.model_validate(raw)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(raw, pieces.output_schema(bundle))
        return
    if variant == 'old_endpoints':
        raw = plan.model_dump()
        next(e for e in raw['numeric'].values() if e['disposition'] == 'outcome')['records'][0]['property_evidence'] = {'first_text_id': 'T1', 'last_text_id': 'T2'}
        with pytest.raises(ValueError):
            pieces.KeyedPlan.model_validate(raw)
        return
    if variant in {'partial', 'insufficient_source'}:
        plan.completion_state = variant
    elif variant == 'missing_text':
        plan.text.pop(next(iter(plan.text)))
    elif variant == 'missing_numeric':
        plan.numeric.pop(next(iter(plan.numeric)))
    elif variant == 'wrong_hash':
        plan.catalog_sha256 = 'f' * 64
    else:
        key, text = next((k, e) for k, e in plan.text.items() if e.unvalued_records)
        text.unvalued_records[0].continuation_text_ids = [key]
    assert not pieces.inspect(plan, bundle)['valid']
    with pytest.raises(ValueError, match='piece_plan_not_valid'):
        pieces.binding_schema(bundle, plan)


def test_known_numeric_value_with_uncertain_identity_remains_in_source_hold():
    _, bundle, _, plan, bindings, _ = fixture()
    record = next(e.records[0] for e in plan.numeric.values() if e.disposition == 'outcome')
    record.sample_description = 'The source reports the value but its specimen assignment is unresolved.'
    bindings.plan_sha256 = digest(plan.model_dump())
    projected, _ = pieces.project_plan(plan, bundle)
    selected, _ = keyed.project_plan(projected, bundle)
    cat = role.selection_catalog(bundle)
    spans = cat['numeric_catalog']['numeric_candidates'][selected.claims[0].numeric_candidate_id]['source_span_ids']
    bindings.decisions['A1'] = role.Hold(decision='hold', reason='Specimen binding remains unresolved.', span_ids=spans)
    model, inventory, proof = pieces.compile(plan, bindings, bundle)
    assert len(model.entries) == 4
    assert proof['source_piece_ledger']['A1']['numeric_candidate_id'] is not None
    assert proof['source_piece_ledger']['A1']['inventory_item_id'] is None
    assert proof['held_outcomes'][0]['claim_id'] == 'A1'
    assert not any(e.type == 'unvalued_result' and e.value_status == 'unresolved' for e in model.entries)
    assert not proof['scientific_acceptance']


@pytest.mark.parametrize('key', pieces.CAPTURE_KEYS)
def test_every_capture_and_original_piece_is_hash_bound(key):
    bundle, _, receipt, captures, _ = snapshot(continuation=True)
    captures[key] += ' '
    with pytest.raises(ValueError, match='piece_capture_hash_mismatch'):
        handoff.build(bundle, receipt_raw=canonical(receipt), captures=captures)


def test_rehashed_projection_cannot_change_a_piece_role_or_location():
    bundle, _, receipt, captures, _ = snapshot(continuation=True)
    proof = json.loads(captures['projection'])
    proof['source_piece_ledger']['A5']['pieces'][-1]['source']['start_char'] += 1
    captures['projection'] = canonical(proof)
    receipt['projection']['sha256'] = sha(captures['projection'].encode())
    with pytest.raises(ValueError, match='piece_projection_mismatch'):
        handoff.build(bundle, receipt_raw=canonical(receipt), captures=captures)


def test_invalid_receipt_is_rejected_before_missing_files(tmp_path):
    _, bundle, *_ = fixture()
    path = tmp_path / 'invalid.json'
    path.write_text(canonical(dict(schema=pieces.ATTEMPT, status='piece_plan_invalid', terminal=True)))
    with pytest.raises(ValueError, match='source_piece_receipt_not_admissible'):
        frozen_inventory.from_files(bundle, path, None)


@pytest.mark.parametrize('continuation', [False, True])
def test_native_consumer_receives_pieces_and_rejects_rehashed_prompt_omission(tmp_path, continuation):
    bundle, parent, _, _, rest = snapshot(pdf=True, continuation=continuation)
    catalog, decisions, links = rest
    store = Store(tmp_path / 'worker')
    job = item_worker.enqueue(store, parent, group_size=2)
    result = run_one(store, job_id=job, provider_override=StageProvider(responses(bundle, catalog, decisions, links)))
    assert result['state'] == 'succeeded', result
    packet = import_packet(store, job)
    verify_packet(packet)
    appendix = handoff.source_piece_prompt(parent)
    transcript = json.loads(packet['raw_output'])
    assert all(e['prompt'].endswith('\n' + appendix) for e in transcript['entries'])
    assert packet['receipt']['config']['source_piece_evidence_sha256'] == sha(appendix.encode())
    if continuation:
        assert 'B_CONTEXT' in appendix and '"purpose":"statement"' in appendix
    database = ProposalDatabase(tmp_path / 'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    altered = deepcopy(packet['receipt'])
    transcript['entries'][0]['prompt'] = transcript['entries'][0]['prompt'].removesuffix('\n' + appendix)
    altered['stages'][0]['prompt_sha256'] = sha(transcript['entries'][0]['prompt'].encode())
    with pytest.raises(ValueError, match='staged_source_piece_evidence_prompt_mismatch'):
        item_worker.verify_receipt(altered, bundle, canonical(transcript))
    altered = deepcopy(packet['receipt'])
    altered['config'].pop('source_piece_evidence_sha256')
    with pytest.raises(ValueError, match='staged_source_piece_evidence_config_mismatch'):
        item_worker.verify_receipt(altered, bundle, packet['raw_output'])
