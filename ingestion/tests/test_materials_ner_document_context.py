"""Distant methods are exact context, never a new result target or approval."""
from copy import deepcopy

import pytest

from ingestion.materials_ner.document_context import build_inventory, discover_inventory, attach_context
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import targets, source_text
from ingestion.materials_ner.sources import load_bundle, make_blocks
from ingestion.materials_ner.windows import make_windows
from test_materials_ner_scoped_conditions import fixture


def example(tmp_path):
    parent, _, _ = fixture()
    parent.blocks = make_blocks(parent.documents[0].id, [
        ('pdf_page:1','The specimen is superconducting below 5 K.'),
        ('pdf_page:2','Discussion of transport results.'),
        ('pdf_page:3','Prior work is cited.\nEXPERIMENTAL SECTION\nSingle crystals were grown at 1173 K.\n'),
        ('pdf_page:4','Resistance was measured using four probes with NaCl.\nRaman used mineral oil.\n'),
        ('pdf_page:5','The XRD refinement used GSAS.\nACKNOWLEDGMENT\nGrant 12345.\nREFERENCES\nOther Tc is 9 K.')])
    manifest = make_windows(tmp_path, parent, adjacent_pages=True)
    window = load_bundle(tmp_path/'bundles'/(manifest['windows'][0]['bundle_sha256']+'.json'))
    return parent, window, discover_inventory(parent)


def test_methods_across_pages_are_lossless_without_contaminating_target(tmp_path):
    parent, window, inventory = example(tmp_path)
    before = deepcopy(window.model_dump()); original = deepcopy(parent.model_dump())
    enriched, proof = attach_context(parent, window, inventory)
    assert window.model_dump() == before and parent.model_dump() == original
    assert len(inventory['text_block_index']) == 5 and len(inventory['selections']) == 3
    text = '\n'.join(b.text for b in enriched.blocks if b.locator.startswith('context-document:'))
    assert '1173 K' in text and 'NaCl' in text and 'mineral oil' in text and 'GSAS' in text
    assert 'Grant 12345' not in text and 'Other Tc is 9 K' not in text
    catalog = source_catalog(enriched)
    assert ''.join(catalog['spans'][s]['text'] for s in sorted(targets(catalog))) == parent.blocks[0].text
    assert not proof['counts_as_target_coverage'] and not proof['sample_or_procedure_applicability_verified']
    assert not inventory['all_relevant_context_identified'] and not inventory['visual_coverage_verified']
    assert 'starting-material ratio is not a measured sample composition' in source_text(enriched)


def test_methods_already_in_target_or_adjacent_context_are_not_aliased_twice(tmp_path):
    parent, _, inventory = example(tmp_path)
    manifest = make_windows(tmp_path/'second', parent, adjacent_pages=True)
    window = load_bundle(tmp_path/'second/bundles'/(manifest['windows'][3]['bundle_sha256']+'.json'))
    enriched, proof = attach_context(parent, window, inventory)
    assert proof['added_characters'] == 0
    assert len(enriched.blocks) == len(window.blocks)


@pytest.mark.parametrize('mutation', ['source_hash','offset','work','document','oversized'])
def test_context_parent_provenance_and_budget_cannot_be_bypassed(tmp_path, mutation):
    parent, window, inventory = example(tmp_path)
    if mutation == 'source_hash': inventory['text_block_index'][0]['sha256'] = '0'*64
    if mutation == 'offset': inventory['selections'][0]['start_char'] += 1
    if mutation == 'work': window.work_id = 'arxiv:other'
    if mutation == 'document': window.documents[0].source_sha256 = '1'*64
    with pytest.raises(ValueError): attach_context(parent, window, inventory, max_context_chars=1 if mutation=='oversized' else 12000)


def test_heading_absence_is_recorded_as_a_gap_and_overlap_is_rejected(tmp_path):
    parent, window, inventory = example(tmp_path)
    parent.blocks = make_blocks(parent.documents[0].id, [('pdf_page:1','Unrecognized section layout, no explicit heading.')])
    missing = discover_inventory(parent)
    assert not missing['selections'] and not missing['all_relevant_context_identified']
    selection = {'source_block_id':parent.blocks[0].id, 'start_char':0, 'end_char':12,
                 'purpose':'sample_context', 'selection_basis':'Source coordinates selected for review.'}
    with pytest.raises(ValueError,match='overlapping_selection'): build_inventory(parent,[selection,selection])
