"""A shared paragraph cannot exchange physical names between frozen quantities."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ingestion.materials_ner.contract import Quantity, digest
from ingestion.materials_ner import quantity_name_witness as witness, staged_revision as revision
from ingestion.materials_ner.sources import sha
from test_materials_ner_staged_revision import fixture


def quantity(value, unit, uncertainty=None, approximate=False):
    return Quantity(status='reported', raw=str(value), relation='exact', value=value, unit=unit,
        approximate=approximate, uncertainty=None if uncertainty is None else dict(
            kind='reported_unspecified', minus=uncertainty, plus=uncertainty, level=None, raw=str(uncertainty)))


TEXT = r'''Fits give $w = 7$~$\mu$m. The offset is $|\mu_0 H_{\mathrm{shift}}| \approx 0.7$~mT.
The fit gives $\rho = 320 \pm 10~\mu\Omega\,\mathrm{cm}$ and $2AR = -0.2 \pm 0.5$~f$\Omega$m$^2$.
A different fit gives $I_cR_N(0) = 200 \pm 70$~$\mu$V.
'''


@pytest.mark.parametrize('q,name', [
    (quantity(0.7, 'mT', approximate=True), r'|\mu_0 H_{\mathrm{shift}}|'),
    (quantity(320, r'\mu\Omega\,\mathrm{cm}', 10), r'\rho'),
    (quantity(-0.2, r'\mathrm{f}\Omega\mathrm{m}^2', 0.5), '2AR'),
    (quantity(200, r'\mu V', 70), 'I_cR_N(0)'),
])
def test_names_are_selected_by_complete_shape_and_explicit_source_units(q, name):
    before = q.model_dump()
    rows = list(witness.assignments(TEXT, q))
    assert [row['name'] for row in rows] == [name]
    assert all(TEXT[row['start_char']:row['end_char']] == row['quote'] for row in rows)
    assert q.model_dump() == before


@pytest.mark.parametrize('q', [quantity(0.7, 'T', approximate=True), quantity(0.7, 'mT'),
                              quantity(320, r'\mu\Omega\,\mathrm{cm}'),
                              quantity(320, r'\mu\Omega\,\mathrm{cm}', 11), quantity(200, 'mV', 70)])
def test_unit_scale_uncertainty_and_approximation_mismatches_are_not_name_choices(q):
    assert list(witness.assignments(TEXT, q)) == []


def test_equal_numeric_assignments_remain_distinct_and_no_unit_is_inferred():
    text=r'$x=2$~nm and $y=2$~nm. A table: z & 2. $p=2$.'
    rows=list(witness.assignments(text, quantity(2,'nm')))
    assert [r['name'] for r in rows]==['x','y']
    assert rows[0]['start_char'] != rows[1]['start_char']


def test_doubled_draft_escapes_are_only_a_flagged_unit_comparison():
    q=quantity(320, r'\\mu\\Omega\\,\\mathrm{cm}', 10)
    rows=list(witness.assignments(TEXT,q))
    assert len(rows)==1 and rows[0]['declared_unit_escape_review']
    q=quantity(-0.2, r'\\mathrm{f}\\Omega\\mathrm{m}^2',0.5)
    before=q.model_dump();rows=list(witness.assignments(TEXT,q))
    assert len(rows)==1 and rows[0]['declared_unit_escape_review']
    assert q.model_dump()==before


def test_name_candidates_require_the_results_own_numeric_evidence(tmp_path):
    _,bundle,parent,_,_=fixture(tmp_path)
    graph,_=revision.resolve_parent(parent)
    obs=graph.observations[0]
    obs.result.quantity=quantity(0.7,'mT',approximate=True)
    bundle=bundle.model_copy(deep=True);bundle.blocks[0].text=TEXT;bundle.blocks[0].sha256=sha(TEXT.encode())
    obs.result.evidence=[SimpleNamespace(fields=['/quantity'],span_ids=['S1'])]
    context=witness.context(graph,'/observations/0/result/quantity_name_raw',bundle)
    assert context['observation_id']==obs.id and context['frozen_quantity_sha256']==digest(obs.result.quantity.model_dump())
    assert [r['name'] for r in context['choices'].values()]==[r'|\mu_0 H_{\mathrm{shift}}|']
    obs.result.evidence=[SimpleNamespace(fields=['/origin'],span_ids=['S1'])]
    assert not witness.context(graph,'/observations/0/result/quantity_name_raw',bundle)['choices']
    assert witness.context(graph,'/samples/0/formula_raw',bundle) is None


def test_wrong_name_or_wrong_choice_cannot_modify_a_frozen_result(tmp_path,monkeypatch):
    _,bundle,parent,request,response=fixture(tmp_path,unmapped=True)
    graph,_=revision.resolve_parent(parent);path='/observations/0/result/quantity_name_raw'
    request['fields'][0].update(path=path,expected_value_sha256=digest(graph.observations[0].result.quantity_name_raw))
    response['request_sha256']=digest(request)
    context=dict(choices={'N1':dict(name='source_symbol',source_span_ids=['S1'])})
    monkeypatch.setattr(witness,'context',lambda *_:context)
    selection=response['selections']['origin'];selection.update(value='wrong_symbol',quantity_name_witness='N1')
    before=digest(parent)
    with pytest.raises(ValueError,match='quantity_name_assignment_mismatch'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)
    selection.update(value='source_symbol',quantity_name_witness='N99')
    with pytest.raises(ValueError,match='quantity_name_assignment_mismatch'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(response),review_request=request)
    assert digest(parent)==before


@pytest.mark.parametrize('text,q,name', [
    (r'Under $H$ $\parallel$ $c$ $\geq$ $H_{c2}$ = 6 T, the state is suppressed.', quantity(6, 'T'), 'H_{c2}'),
    (r'The source gives $T_c$ = $12$ K.', quantity(12, 'K'), 'T_c'),
    (r'The source gives $T_c$ \approx 7.2 K.', quantity(7.2, 'K', approximate=True), 'T_c'),
    (r'A fit gives $p$ = -0.2 \pm 0.5 mT.', quantity(-0.2, 'mT', 0.5), 'p'),
])
def test_mixed_math_prose_assignment_preserves_source_and_frozen_quantity(text, q, name):
    before = q.model_dump()
    assert list(witness.assignments(text, q, witness.LEGACY_POLICY)) == []
    rows = list(witness.assignments(text, q))
    assert len(rows) == 1 and rows[0]['name'] == name
    row = rows[0]
    assert row['assignment_syntax'] == 'math_name_external_assignment'
    assert text[row['start_char']:row['end_char']] == row['quote']
    assert row['quote_sha256'] == sha(row['quote'].encode())
    assert text[row['numeric_start_char']:row['end_char']] == row['numeric_source_fragment']
    assert q.model_dump() == before


@pytest.mark.parametrize('text', [
    r'$x/y$ = 6 T.', r'$x$/$y$ = 6 T.', r'$x$ = $y$ = 6 T.',
    r'$x$ = 42 T/6 T.', r'$x$ = 6 T/2.', r'$x$ = 6 T and 8 T.',
    r'$x$ = 6 T, 8 T.', r'$x$ = 6 T/K.', r'$x$ = 6 mT.',
    r'$x$ = 6 \pm 1 T.', r'$x$ \approx 6 T.', r'$x$ = 6.',
    r'$x$ >= 6 T.', r'$x,y$ = 6 T.', r'$x$ may reach 6 T.',
])
def test_mixed_assignment_rejects_truncated_shapes_ratios_lists_and_inferred_units(text):
    assert list(witness.assignments(text, quantity(6, 'T'))) == []


def test_mixed_assignments_remain_tied_to_the_frozen_numeric_source(tmp_path):
    _, bundle, parent, _, _ = fixture(tmp_path)
    graph, _ = revision.resolve_parent(parent)
    graph.observations[0].result.quantity = quantity(6, 'T')
    blocks = []
    for i, name in enumerate(['Q', 'R']):
        text = f'SYNTHETIC source {name} gives ${name}$ = 6 T.'
        blocks.append(bundle.blocks[0].model_copy(update=dict(
            id=bundle.blocks[0].id + ':' + name, ordinal=i, text=text, sha256=sha(text.encode()))))
    bundle = bundle.model_copy(update={'blocks': blocks})
    first = next(alias for alias, span in revision.source_catalog(bundle)['spans'].items()
                 if span['block_id'] == blocks[0].id)
    graph.observations[0].result.evidence = [SimpleNamespace(fields=['/quantity'], span_ids=[first])]
    path = '/observations/0/result/quantity_name_raw'
    current = witness.context(graph, path, bundle)
    assert [row['name'] for row in current['choices'].values()] == ['Q']
    legacy = witness.context(graph, path, bundle, witness.LEGACY_POLICY)
    assert legacy['policy'] == witness.LEGACY_POLICY and legacy['choices'] == {}
    assert current['policy'] == witness.POLICY and not current['scientific_acceptance']
