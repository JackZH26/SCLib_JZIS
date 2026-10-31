"""Authored source-map and review regressions, not independent scientific Gold."""
from copy import deepcopy
from functools import lru_cache
from xml.sax.saxutils import escape

import jsonschema
import pytest

from ingestion.materials_ner import pdf_spatial_view as spatial, pdf_layout
from ingestion.materials_ner import source_spatial_review as review, source_piece_review as legacy
from ingestion.materials_ner import source_role_inventory as role, typed_inventory_handoff as handoff
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.sources import sha
from test_materials_ner_source_piece_review import fixture as old_fixture
from test_materials_ner_source_keyed import fixture as source_fixture


@lru_cache
def _fixture():
    bundle, prior, old = old_fixture()
    parent = review.from_prior(prior)
    raw = old.model_dump()
    raw.update(schema_version=review.VERSION, parent_id=parent['parent_id'])
    for row in raw['record_reviews'].values():
        row.pop('decision')
        for check in row['checks'].values():
            check['witness_ids'] = check.pop('text_ids')
    for name in ('numeric_reviews', 'text_reviews'):
        for row in raw[name].values():
            row.pop('text_ids')
            row['additional_witness_ids'] = []
    return bundle, prior, parent, review.Review.model_validate(raw)


def fixture():
    return deepcopy(_fixture())


def spatial_fixture():
    original, *_ = source_fixture(pdf=True)
    body = ('run #1\nFigure 1. Plot from run #1.\n'
        'The pressure scan on specimen B yields a transition temperature of 2.17 K. '
        'The low temperature measurement continues in the adjacent column.\n'
        '0\n0\nA signed slope of -1.2 K/GPa was inferred from these observations.\n')
    original.blocks[0].text = body
    original.blocks[0].sha256 = sha(body.encode())
    bundle, scope = role.scope(original, [original.blocks[0].id])
    cat = role.selection_catalog(bundle)
    texts = [('run #1', 330, 100), ('Figure 1. Plot from run #1.', 320, 160),
        ('The pressure scan on specimen B yields a transition tem-\nperature of 2.17 K. '
         'The low temperature measurement continues in the adjacent column.', 50, 100),
        ('0', 330, 130), ('fabricated text', 340, 140),
        ('A signed slope of -1.2 K/GPa was inferred from these observations.', 50, 200)]
    def region(text, x, y):
        lines = []
        for i, line in enumerate(text.splitlines()):
            box = f'xMin="{x}" yMin="{y+i*12}" xMax="{x+220}" yMax="{y+i*12+10}"'
            lines.append(f'<line {box}><word {box}>{escape(line)}</word></line>')
        box = f'xMin="{x}" yMin="{y}" xMax="{x+220}" yMax="{y+len(lines)*12}"'
        return f'<flow><block {box}>{"".join(lines)}</block></flow>'
    xml = '<doc><page width="600" height="850">' + ''.join(region(*r) for r in texts) + '</page></doc>'
    layout = pdf_layout.build(original, pdf_sha256=original.documents[0].source_sha256,
        bbox_xml=xml, producer='authored fixture')
    return original, cat, scope, layout


def test_spatial_regions_preserve_original_quotes_and_do_not_join_columns_or_runs():
    original, cat, scope, layout = spatial_fixture()
    before = original.model_dump()
    view = spatial.build(layout, original, cat, scope['target_block_ids'])
    assert spatial.verify(view, layout, original, cat, scope['target_block_ids']) == view
    assert original.model_dump() == before
    regions = {r['id']: r for r in view['pages'][0]['regions']}
    body = regions['P1:F3:B1']
    assert body['mapping_status'] == 'unique'
    assert body['matching_policy'] == 'alphabetic_line_wrap_equivalent'
    assert body['horizontal_band'] == 'left_half'
    source = body['original_matches'][0]
    assert original.blocks[0].text[source['start_char']:source['end_char']] == source['quote']
    assert '2.17 K' in source['quote'] and 'run #1' not in source['quote']
    assert regions['P1:F2:B1']['appearance_hint'] == 'caption_like'
    assert regions['P1:F1:B1']['horizontal_band'] == 'right_half'
    assert regions['P1:F1:B1']['mapping_status'] == 'ambiguous'
    assert regions['P1:F4:B1']['mapping_status'] == 'ambiguous'
    assert regions['P1:F5:B1']['mapping_status'] == 'unmapped'
    assert not any(r['ownership_verified'] for r in regions.values())
    assert not view['geometry_establishes_subject_identity'] and not view['semantic_reading_order_verified']
    assert 'not a verified reading order' in spatial.render(view)


def test_matching_preserves_scientific_signs_primes_and_numeric_line_endpoints():
    original, cat, scope, layout = spatial_fixture()
    view = spatial.build(layout, original, cat, scope['target_block_ids'])
    slope = next(r for r in view['pages'][0]['regions'] if r['id'] == 'P1:F6:B1')
    assert '-1.2 K/GPa' in slope['original_matches'][0]['quote']
    assert list(spatial._variants('3.5-\n2 K')) == [('whitespace_equivalent', '3.5-2K')]
    assert spatial._matches('slope of 1.2 K/GPa', original.blocks)[1] == []
    assert spatial._matches('χ′′1', original.blocks)[1] == []


@pytest.mark.parametrize('change', ['quote', 'box', 'ownership', 'mapping'])
def test_rehashed_geometry_or_source_mapping_tampering_is_rejected(change):
    original, cat, scope, layout = spatial_fixture()
    original_layout = deepcopy(layout)
    view = spatial.build(layout, original, cat, scope['target_block_ids'])
    region = next(r for r in view['pages'][0]['regions'] if r['selectable_as_position_witness'])
    if change == 'quote':
        region['original_matches'][0]['quote'] += ' altered'
    elif change == 'box':
        region['box'][0] += 1
    elif change == 'ownership':
        region['ownership_verified'] = True
    else:
        region['original_matches'][0]['start_char'] += 1
    view['view_id'] = digest({k: v for k, v in view.items() if k != 'view_id'})
    assert layout == original_layout
    with pytest.raises(ValueError, match='spatial_view_reconstruction_mismatch'):
        spatial.verify(view, layout, original, cat, scope['target_block_ids'])


def test_spatial_view_cannot_omit_original_characters_or_fill_text_gaps():
    original, cat, scope, layout = spatial_fixture()
    cat['texts'].pop(next(iter(cat['texts'])))
    with pytest.raises(ValueError, match='spatial_source_text_partition'):
        spatial.build(layout, original, cat, scope['target_block_ids'])


def test_keyed_anchors_are_exact_without_model_generated_repeated_locations():
    bundle, prior, parent, result = fixture()
    assert parent['original_parent_id'] == prior['parent_id']
    assert parent['records'] == prior['records'] and parent['original_completion_state'] == 'partial'
    assert set(parent['obligation_anchors']) == set(parent['numeric_obligation_ids'] + parent['text_obligation_ids'])
    for anchor in parent['obligation_anchors'].values():
        source = anchor['source']
        block = next(b for b in bundle.blocks if b.id == source['block_id'])
        assert block.text[source['start_char']:source['end_char']] == source['quote']
        assert anchor['text_ids']
    schema = review.output_schema(parent)
    assert 'decision' not in schema['$defs']['RecordReview']['properties']
    assert 'text_ids' not in schema['$defs']['NumericReview']['properties']
    jsonschema.validate(result.model_dump(), schema)
    assert review.inspect(result, parent)['valid']


@pytest.mark.parametrize('name', ['record_reviews', 'numeric_reviews', 'text_reviews'])
def test_every_original_candidate_and_obligation_still_required(name):
    _, _, parent, result = fixture()
    getattr(result, name).pop(next(iter(getattr(result, name))))
    assert any(i['code'] == 'review_key_coverage_mismatch' for i in review.inspect(result, parent)['issues'])


def test_triage_is_derived_and_preserves_both_revisions_and_unresolved_fields():
    _, _, parent, result = fixture()
    key = next(iter(result.record_reviews)); row = result.record_reviews[key]
    for check in row.checks:
        check[1].status = 'supported'
    row.proposed_role = 'condition'
    validation = review.inspect(result, parent)
    assert validation['valid']
    assert validation['derived_record_triage'][key]['decision'] == 'revise_candidate'
    row.checks.subject.status = 'unresolved'
    row.checks.provenance.status = 'revise'
    triage = review.inspect(result, parent)['derived_record_triage'][key]
    assert triage['decision'] == 'hold' and triage['revised_checks'] == ['provenance']
    assert triage['unresolved_checks'] == ['subject'] and triage['role_change_proposed']


def test_numeric_inference_or_unknown_identity_cannot_erase_reported_number():
    _, _, parent, result = fixture()
    key = next(k for k, r in parent['records'].items() if r['numeric_candidate_id'])
    row = result.record_reviews[key]; row.proposed_role = 'unvalued_result'
    row.interpretation = 'This reported number is inferred and its specimen remains uncertain.'
    assert any(i['code'] == 'review_known_numeric_cannot_become_unvalued' for i in review.inspect(result, parent)['issues'])
    with pytest.raises(ValueError, match='spatial_review_annotations_invalid'):
        review.assemble(parent, canonical(result.model_dump()))


def test_assertion_specific_applicability_does_not_demand_tc_criterion_for_context():
    _, _, parent, result = fixture()
    key = next(k for k, r in parent['records'].items() if r['role'] == 'context')
    row = result.record_reviews[key]
    for _, check in row.checks:
        check.status = 'supported'
    row.checks.method_criterion.status = 'not_applicable'
    row.checks.method_criterion.witness_ids = []
    row.checks.method_criterion.reason = 'This assertion maps a caption to its plotted run, not a transition criterion.'
    assert review.inspect(result, parent)['valid']
    assert review.inspect(result, parent)['derived_record_triage'][key]['decision'] == 'retain_candidate'


@pytest.mark.parametrize('name', ['property_value', 'provenance', 'evidence_scope', 'occurrence_identity'])
def test_result_core_checks_cannot_be_made_inapplicable(name):
    _, _, parent, result = fixture()
    key = next(k for k, r in parent['records'].items() if r['role'] == 'numeric_result')
    getattr(result.record_reviews[key].checks, name).status = 'not_applicable'
    assert not review.inspect(result, parent)['valid']


def test_actual_field_support_remains_required_and_ambiguous_regions_are_unselectable():
    _, _, parent, result = fixture()
    row = next(iter(result.record_reviews.values()))
    row.checks.subject.status = 'supported'; row.checks.subject.witness_ids = []
    assert any(i['code'] == 'review_witness_required' for i in review.inspect(result, parent)['issues'])
    row.checks.subject.witness_ids = ['P999:F1:B1']
    assert any(i['code'] == 'review_unknown_reference' for i in review.inspect(result, parent)['issues'])


@pytest.mark.parametrize('kind', ['source', 'anchor', 'flag', 'coverage'])
def test_rehashed_v2_parent_cannot_replace_source_anchors_or_promote_partial_state(kind):
    _, _, parent, _ = fixture()
    if kind == 'source':
        parent['captures']['role_raw'] += ' '
    elif kind == 'anchor':
        next(iter(parent['obligation_anchors'].values()))['source']['quote'] = 'fabricated'
    elif kind == 'flag':
        parent['canonical_eligible'] = True
    else:
        parent['original_unresolved_text_ids'] = []
    parent['parent_id'] = digest({k: v for k, v in parent.items() if k != 'parent_id'})
    with pytest.raises(ValueError):
        review.verify_parent(parent)


def test_packet_rebuild_preserves_raw_outputs_known_values_and_coverage_debt():
    bundle, prior, parent, result = fixture()
    raw = canonical(result.model_dump()); packet = review.assemble(parent, raw)
    assert review.verify_packet(packet) == packet and packet['raw_review'] == raw
    assert packet['parent']['captures'] == prior['captures']
    assert packet['coverage_debt']['original_text'] == prior['original_unresolved_text_ids']
    for key in ['scientific_acceptance', 'canonical_eligible', 'ml_training_eligible', 'full_source_coverage_established']:
        assert packet[key] is False
    for name in ('numeric_reviews', 'text_reviews'):
        assert all(r['anchor']['source']['quote'] for r in packet['obligation_witnesses'][name].values())
    with pytest.raises(ValueError, match='typed_frozen_receipt_not_admissible'):
        handoff.build(bundle, receipt_raw=canonical(packet), captures={})
    # A v1 model response is never relabelled/repaired into v2.
    _, _, old = old_fixture()
    with pytest.raises(ValueError):
        review.assemble(parent, canonical(old.model_dump()))


@pytest.mark.parametrize('field', ['scientific_acceptance', 'canonical_eligible', 'ml_training_eligible', 'full_source_coverage_established'])
def test_supported_rehashed_diagnostic_packet_cannot_promote_scientific_acceptance(field):
    _, _, parent, result = fixture()
    packet = review.assemble(parent, canonical(result.model_dump()))
    packet[field] = True
    packet['packet_id'] = digest({k: v for k, v in packet.items() if k != 'packet_id'})
    with pytest.raises(ValueError, match='spatial_review_packet_changed'):
        review.verify_packet(packet)
