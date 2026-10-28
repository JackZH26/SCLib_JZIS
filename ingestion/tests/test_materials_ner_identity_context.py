"""Identity source passages stay locatable without changing the target scope."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from ingestion.materials_ner import identity_context as identity
from ingestion.materials_ner.cli import main
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.document_context import attach_context, build_inventory
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import targets
from ingestion.materials_ner.reference_context import attach_references, build_index as references, verified_edges
from ingestion.materials_ner.sources import load_bundle, make_blocks, parse_local, save_bundle, sha
from ingestion.materials_ner.windows import make_windows
from test_materials_ner_source_audit import archive
from test_materials_ner_tex_context import source


HEADER = ('\\title[Short]{Synthetic Fe$_{1-x}$Se$_{x}$ sample}\r\n'
          '\\begin{abstract}\r\nWe report a synthetic specimen.\r\n\\end{abstract}\r\n')


def example(tmp_path, header=HEADER):
    text = ('% Preamble template.\r\n' * 180 + header + 'Background.\r\n' * 240 +
            'A target result is discussed \\cite{note}.\r\n' + 'Other discussion.\r\n' * 160 +
            '\\begin{references}\r\n\\bibitem{note} Our measurement has Tc=12 K.\r\n\\end{references}\r\n')
    parent = source([('archive_member:main.tex', text)])
    parent.title = 'Metadata formula Zz999 is not a source passage.'
    manifest = make_windows(tmp_path, parent, max_chars=1000)
    windows = [load_bundle(tmp_path / 'bundles' / (r['bundle_sha256'] + '.json')) for r in manifest['windows']]
    window = next(w for w in windows if any(r'\cite{note}' in b.text for b in w.blocks if b.locator.startswith('target:')))
    return parent, window


def test_long_preamble_does_not_hide_original_header_and_target_ids_stay_fixed(tmp_path):
    parent, window = example(tmp_path)
    before = deepcopy(window.model_dump()); old_catalog = source_catalog(window)
    assert not any(r'\title' in b.text for b in window.blocks)
    index = identity.build_index(parent)
    enriched, proof = identity.attach_identity(parent, window, index)
    assert identity.verify_attachment(parent, window, enriched, index) == proof
    assert {s['purpose'] for s in index['selection_inventory']['selections']} == {'identity_title', 'identity_abstract'}
    original = parent.blocks[0]
    for part in proof['attachment']['attached_slices']:
        local = next(b for b in enriched.blocks if b.id == part['block_id'])
        assert local.text == original.text[part['start_char']:part['end_char']]
        assert sha(local.text.encode()) == part['text_sha256']
        assert '\r\n' in local.text or r'\title' in local.text
    catalog = source_catalog(enriched)
    assert targets(catalog) == targets(old_catalog)
    assert all(catalog['spans'][key] == value for key, value in old_catalog['spans'].items())
    assert 'Zz999' not in ''.join(b.text for b in enriched.blocks)
    assert window.model_dump() == before
    assert not proof['counts_as_target_coverage'] and not proof['sample_or_result_applicability_verified']
    assert not index['all_identity_context_identified']


@pytest.mark.parametrize('hidden', [
    '% \\title{Comment}\n', '\\begin{comment}\n\\title{Example}\n\\end{comment}\n',
    '\\begin{verbatim}\n\\title{Example}\n\\end{verbatim}\n',
    '\\iffalse\n\\title{Hidden}\n\\else\n\\title{Also hidden}\n\\fi\n',
    r'\newcommand{\example}{\title{Template}}', r'\def\example{\title{Template}}',
    r'\verb|\title{Example}|', r'\\title{Escaped}',
])
def test_examples_comments_and_definitions_do_not_supply_a_title(tmp_path, hidden):
    parent, _ = example(tmp_path, hidden + '\n')
    index = identity.build_index(parent)
    assert not index['selection_inventory']['selections'] and not index['candidates']


@pytest.mark.parametrize('header', [
    '\\title{One}\n\\title{Two}\n',
    '\\title{Good}\n\\title{Unclosed\n',
    '\\title{Unclosed\n',
    '\\begin{abstract}\nUnclosed abstract.\n',
    '\\begin{abstract}\nOuter \\begin{abstract} inner \\end{abstract}\n',
])
def test_ambiguous_or_unclosed_headers_are_holds_not_first_match_choices(tmp_path, header):
    parent, _ = example(tmp_path, header)
    index = identity.build_index(parent)
    assert not index['selection_inventory']['selections']
    assert index['holds'] or any(d['status'] == 'ambiguous_literals' for d in index['decisions'])


def test_balanced_title_nested_braces_escaped_delimiters_and_inline_abstract(tmp_path):
    title = '\\title[Short]{Fe$_{1-x}$Se$_{x}$ with \\{literal\\} braces}'
    abstract = '\\abstract{A multi-line\r\nsynthetic description.}'
    parent, _ = example(tmp_path, title + '\r\n' + abstract + '\r\n')
    index = identity.build_index(parent); block = parent.blocks[0]
    assert [block.text[c['start_char']:c['end_char']] for c in index['candidates']] == [title, abstract]


def test_duplicate_members_and_unsupported_pdf_do_not_pick_identity(tmp_path):
    parent, _ = example(tmp_path)
    parent.blocks = make_blocks(parent.documents[0].id, [('archive_member:main.tex', HEADER), ('archive_member:old.tex', HEADER)])
    assert not identity.build_index(parent)['selection_inventory']['selections']
    parent.documents[0].source_kind = 'original_pdf'
    parent.blocks = make_blocks(parent.documents[0].id, [('pdf_page:1', 'A title\nAbstract\nText')])
    index = identity.build_index(parent)
    assert len(index['unsupported_blocks']) == 1 and not index['selection_inventory']['selections']


def test_existing_context_is_subtracted_and_reference_attachment_keeps_its_proof(tmp_path):
    parent, window = example(tmp_path); index = identity.build_index(parent)
    one = index['selection_inventory']['selections'][0]
    selected = {k: one[k] for k in ('source_block_id', 'start_char', 'end_char', 'purpose', 'selection_basis')}
    partial, _ = attach_context(parent, window, build_inventory(parent, [selected]))
    enriched, proof = identity.attach_identity(parent, partial, index)
    assert len(proof['attachment']['attached_slices']) == 1
    complete, _ = attach_references(parent, enriched, references(parent))
    assert verified_edges(complete)[0]['key'] == 'note'
    assert len({b.id for b in complete.blocks}) == len(complete.blocks)
    with pytest.raises(ValueError, match='must_precede_reference'):
        identity.attach_identity(parent, complete, index)
    with pytest.raises(ValueError, match='parent_mismatch'):
        identity.attach_identity(parent, enriched, index)


def test_fragments_and_total_attachment_have_explicit_budgets(tmp_path):
    parent, window = example(tmp_path)
    small = identity.build_index(parent, max_fragment_chars=8)
    assert len(small['holds']) == 2 and not small['selection_inventory']['selections']
    with pytest.raises(ValueError, match='no_silent_truncation'):
        identity.attach_identity(parent, window, identity.build_index(parent), max_context_chars=1)
    with pytest.raises(ValueError, match='requires_original_parent'):
        identity.build_index(window)


@pytest.mark.parametrize('mutation', ['index', 'source', 'window', 'attached'])
def test_tampered_coordinates_source_or_attachment_cannot_verify(tmp_path, mutation):
    parent, window = example(tmp_path); index = identity.build_index(parent)
    enriched, _ = identity.attach_identity(parent, window, index)
    if mutation == 'index':
        index['candidates'][0]['end_char'] -= 1
    elif mutation == 'source':
        parent.blocks[0].text = parent.blocks[0].text.replace('synthetic', 'different')
        parent.blocks[0].sha256 = sha(parent.blocks[0].text.encode())
    elif mutation == 'window':
        window.work_id = 'arxiv:another'
    else:
        enriched.blocks[-1].text += ' altered'
        enriched.blocks[-1].sha256 = sha(enriched.blocks[-1].text.encode())
    with pytest.raises(ValueError):
        identity.verify_attachment(parent, window, enriched, index)


def test_declared_latin9_maps_decoded_coordinates_without_changing_original_bytes(tmp_path):
    text = '\\usepackage[latin9]{inputenc}\r\n\\title{Synthetic Œ and €}\r\n'
    raw = text.encode('iso-8859-15'); path = archive(tmp_path, [('main.tex', raw)])
    original = path.read_bytes()
    parent = parse_local(path, work_id='arxiv:synthetic', title='Metadata only', source_uri='synthetic:latin9', text_encoding='iso-8859-15')
    index = identity.build_index(parent); candidate = index['candidates'][0]
    selected = parent.blocks[0].text[candidate['start_char']:candidate['end_char']]
    assert selected == '\\title{Synthetic Œ and €}' and selected.encode('iso-8859-15') in raw
    assert path.read_bytes() == original and parent.documents[0].source_sha256 == sha(original)


def test_cli_prepares_new_bundle_without_model_calls_queue_or_overwrite(tmp_path, capsys):
    parent, window = example(tmp_path / 'source')
    _, pp = save_bundle(tmp_path / 'source', parent); _, wp = save_bundle(tmp_path / 'source', window)
    root = tmp_path / 'prepared'; out = tmp_path / 'identity-report.json'
    args = ['--root', str(root), 'prepare-identity-context', '--parent-bundle', str(pp), '--window-bundle', str(wp), '--out', str(out)]
    assert main(args) == 0
    notice = json.loads(capsys.readouterr().out); report = json.loads(out.read_text())
    assert notice['report_sha256'] == digest(report) and report['fresh_inventory_required']
    assert not (root / 'queue.sqlite3').exists()
    assert load_bundle(Path(report['bundle_path'])).work_id == parent.work_id
    before = out.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        main(args)
    assert out.read_bytes() == before
