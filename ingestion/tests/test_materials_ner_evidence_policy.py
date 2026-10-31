"""Shared rules retain required witnesses and never create source assertions."""
from copy import deepcopy
from ingestion.materials_ner import evidence_policy as p


def test_sparse_sample_only_requires_asserted_fields():
    sample=dict(formula_raw=None,composition_basis='unresolved',identity_resolution='unresolved',
        target_kind='unresolved',isotopes=[],variables=[],additional_formula_assertions=[],
        label=None,form_raw=None,substrate_raw=None)
    assert p.required('sample',sample)==[]
    sample.update(formula_raw='X',composition_basis='measured',identity_resolution='conflicted',
        target_kind='film',substrate_raw='Y',variables=[{}],additional_formula_assertions=[{},{}])
    assert p.required('sample',sample)==['/formula_raw','/composition_basis','/variables/0',
        '/additional_formula_assertions/0','/additional_formula_assertions/1','/identity_resolution',
        '/target_kind','/substrate_raw']


def test_pressure_and_condition_requirements_do_not_infer_ambient_or_missing_values():
    state=dict(sample_id='s',conditions=[dict(quantity=dict(status='reported')),dict(quantity=dict(status='not_extracted'))],
        pressure=dict(availability='not_reported',regime='unknown',basis_raw=None))
    assert p.required('state',state)==['/sample_id','/conditions/0']
    assert p.required('pressure',state)==[]
    before=deepcopy(state);p.render();assert state==before
    state['pressure'].update(availability='reported',basis_raw='ambient pressure')
    assert p.required('pressure',state)==['/pressure','/pressure/basis_raw']


def test_definition_and_negative_target_requirements_keep_separate_assertions():
    result=dict(definition=dict(criterion='resistance_fraction',criterion_raw='source words',parameters=[{}]),
        qualifiers=[dict(kind='conditional_existence',tc_bound=dict(status='reported')),
            dict(kind='non_detection',window_condition_ids=['floor'],sensitivities=[{},{}])])
    assert p.required('definition',result)==['/definition/criterion','/definition/criterion_raw','/definition/parameters/0']
    assert p.required('qualifiers',result)==['/qualifiers/0','/qualifiers/1','/qualifiers/0/tc_bound']
    assert p.required('non_detection_window',result)==['/qualifiers/1/window_condition_ids']
    assert p.required('non_detection_sensitivity',result)==['/qualifiers/1/sensitivities/0','/qualifiers/1/sensitivities/1']


def test_raw_field_walk_ignores_evidence_and_numeric_raw():
    value=dict(formula_raw='X',evidence=[dict(quote='ignored',other_raw='ignored')],
        conditions=[dict(basis_raw='words',quantity=dict(raw='7 K'))],substrate_raw=None)
    assert list(p.raw_fields(value))==[('/formula_raw','X'),('/conditions/0/basis_raw','words')]


def test_model_policy_contains_same_machine_rules_used_by_validator():
    from ingestion.materials_ner.contract import canonical
    assert canonical(p.RULES) in p.render()
    assert 'context_quote' in p.render() and 'child binding does not automatically satisfy its parent' in p.render()
