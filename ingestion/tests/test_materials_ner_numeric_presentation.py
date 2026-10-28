"""Literal syntax regressions from disclosed arXiv development cases, not Gold."""
from copy import deepcopy

import pytest

from ingestion.materials_ner.contract import Evidence, Quantity, digest
from ingestion.materials_ner.quantities import (
    numeric_presentation, quantity_source_issues, unmapped_quantity_source_issues,
)
from ingestion.materials_ner import staged_revision as revision
from test_materials_ner_staged_revision import fixture, execute


def check(raw, *, kind=None, quote=None, **values):
    q = Quantity(status='reported', raw=raw, unit='nm', **values)
    original = q.model_dump()
    evidence = [Evidence(block_id='synthetic', quote=quote or raw, field='/quantity')]
    issues = (quantity_source_issues(kind, q, evidence, '/quantity') if kind else
              unmapped_quantity_source_issues(q, evidence, '/quantity'))
    assert q.model_dump() == original
    return issues


@pytest.mark.parametrize('kind', [None, 'thickness'])
@pytest.mark.parametrize('raw,lower,upper', [
    ('1--3.5~nm', 1, 3.5), ('1 -- 3.5 nm', 1, 3.5),
    ('between 0.5 and 4.5~nm', .5, 4.5),
    ('between 0.5 nm and 4.5 nm', .5, 4.5),
])
def test_reported_intervals_preserve_both_bounds_and_never_create_a_mean(kind, raw, lower, upper):
    assert check(raw, kind=kind, relation='interval', lower=lower, upper=upper) == []
    assert check(raw, kind=kind, relation='exact', value=(lower + upper) / 2)
    assert check(raw, kind=kind, relation='interval', lower=lower, upper=upper + 1)


@pytest.mark.parametrize('kind', [None, 'thickness'])
@pytest.mark.parametrize('marker,relation,endpoint', [
    (r'\lesssim', 'le', 'upper'), ('≲', 'le', 'upper'),
    (r'\gtrsim', 'ge', 'lower'), ('≳', 'ge', 'lower'),
])
def test_approximate_bound_keeps_both_inequality_and_approximation(kind, marker, relation, endpoint):
    raw = marker + ' 0.5 nm'
    shape = dict(relation=relation, **{endpoint: .5})
    assert check(raw, kind=kind, approximate=True, **shape) == []
    assert check(raw, kind=kind, **shape) == ['approximation_marker_lost']
    assert check(raw, kind=kind, approximate=True, relation='exact', value=.5) == [
        'numeric_value_disagrees_with_raw']


@pytest.mark.parametrize('kind', [None, 'thickness'])
@pytest.mark.parametrize('raw', [
    '1---3.5 nm', '1--3.5--5 nm', '1--3.5 + 2 nm',
    'between 1 and 3.5 and 5 nm', '1 and 3.5 nm',
    'between 1 nm and 3.5 μm', 'between 3.5 and 1 nm',
    '1--3.5 μm', '1--3.5 nm-thick',
])
def test_ambiguous_lists_arithmetic_mixed_units_and_wrong_endpoints_stay_rejected(kind, raw):
    assert check(raw, kind=kind, relation='interval', lower=1, upper=3.5)


def test_signed_endpoint_and_scientific_notation_are_numbers_but_formula_is_not_rewritten():
    assert check('-2 -- -1 nm', relation='interval', lower=-2, upper=-1) == []
    assert check('1e-2--3e-2 nm', relation='interval', lower=.01, upper=.03) == []
    assert numeric_presentation('Nb--Pt--Mn5Si3') == 'Nb--Pt--Mn5Si3'
    assert check('between 1 and 3.5 nm', relation='interval', lower=1, upper=3.5,
                 quote='The source reports a different sample at 3.5 nm.') == [
        'quantity_raw_not_in_field_evidence']


def raw_request(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    graph, _ = revision.resolve_parent(parent)
    quantity = graph.observations[0].result.quantity
    assert quantity.status == 'reported' and quantity.relation == 'exact'
    path = '/observations/0/result/quantity/raw'
    request['fields'] = [dict(request['fields'][0], path=path,
                              expected_value_sha256=digest(quantity.raw))]
    response['request_sha256'] = digest(request)
    response['selections']['origin']['value'] = f'{quantity.value:g}'
    return store, bundle, parent, request, response, quantity


def test_raw_only_repair_is_replayable_and_preserves_every_numeric_field(tmp_path):
    store, bundle, parent, request, response, quantity = raw_request(tmp_path)
    graph, _ = revision.resolve_parent(parent)
    context = revision.raw_witness.context(graph, request['fields'][0]['path'], bundle)
    response['selections']['origin']['value'] = {'source_choice': next(iter(context['choices']))}
    _, packet = execute(store, bundle, parent, request, response)
    after, _ = revision.resolve_parent(packet)
    fixed = after.observations[0].result.quantity
    assert fixed.model_dump(exclude={'raw'}) == quantity.model_dump(exclude={'raw'})
    guard = packet['receipt']['revision_audit']['changes'][0]['quantity_raw_guard']
    assert guard['policy'] == revision.QUANTITY_RAW_POLICY
    assert guard['numeric_semantics_unchanged'] and guard['unit_unchanged']
    assert packet['receipt']['config']['quantity_raw_policy'] == revision.QUANTITY_RAW_POLICY
    assert not packet['receipt']['revision_audit']['scientific_acceptance']


@pytest.mark.parametrize('raw', ['999 K', '39 nm', '39 ± 2 K', 'between 38 and 40 K', '≈39 K'])
def test_raw_only_repair_cannot_borrow_another_literal_with_incompatible_shape(tmp_path, monkeypatch, raw):
    _, bundle, parent, request, response, quantity = raw_request(tmp_path)
    # This isolates numeric fidelity from quote-location verification. Source
    # location and real original text are exercised by the successful replay.
    monkeypatch.setattr(revision, 'selected_quotes', lambda *_: [{'quote': raw}])
    response['selections']['origin']['value'] = raw
    before = deepcopy(parent)
    with pytest.raises(ValueError, match='staged_field_quantity_raw_incompatible'):
        revision.apply_edits(parent, bundle, revision.NativeEdits.model_validate(response), review_request=request,
                             quantity_raw_policy='source_literal_numeric_shape_v1')
    assert parent == before
