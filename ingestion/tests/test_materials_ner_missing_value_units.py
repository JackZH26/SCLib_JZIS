"""A missing scalar must not hide a known scientific unit/type mismatch."""
from copy import deepcopy

import pytest

from ingestion.materials_ner.contract import Quantity
from ingestion.materials_ner.quantities import normalize,quantity_source_issues
from ingestion.materials_ner.validation import validate_extraction,training_exclusions
from ingestion.materials_ner.wire_v10 import DetectionExtraction
from test_materials_ner_non_detection_targets import fixture


@pytest.mark.parametrize('status',['ambiguous','conflicted','not_reported','not_accessible','not_extracted','not_applicable'])
def test_known_current_unit_is_not_a_field_unit_even_without_a_scalar(status):
    quantity=Quantity(status=status,raw='10~nA',unit='nA')
    before=quantity.model_dump()
    assert quantity_source_issues('magnetic_flux_density',quantity,[],'/quantity')==['known_unit_incompatible_with_quantity_kind']
    assert normalize('magnetic_flux_density',quantity)=={'status':status,'normalized':None}
    assert quantity.model_dump()==before


@pytest.mark.parametrize('kind,unit',[('magnetic_flux_density','mT'),('magnetic_flux_density',None),
    ('magnetic_flux_density','unregistered-unit'),('unmapped','nA'),('temperature','K'),('thickness',r'\mu$m')])
def test_absent_compatible_or_unknown_units_are_not_silently_interpreted(kind,unit):
    quantity=Quantity(status='ambiguous',raw=None,unit=unit)
    assert quantity_source_issues(kind,quantity,[],'/quantity')==[]
    assert quantity.value is None and quantity.lower is None and quantity.upper is None


@pytest.mark.parametrize('owner',['state','procedure'])
def test_full_graph_validation_quarantines_missing_value_dimension_conflicts(owner):
    bundle,_,raw=fixture()
    q=Quantity(status='ambiguous',raw='100 nm',unit='nm').model_dump()
    if owner=='state':
        raw['states'][0]['conditions'][0].update(kind='magnetic_flux_density',quantity=q)
        path='/states/0/conditions/0/quantity'
    else:
        raw['protocols'][0]['parameters']=[{'kind':'magnetic_flux_density','name_raw':'London penetration depth','quantity':q}]
        path='/protocols/0/parameters/0/quantity'
    extraction=DetectionExtraction.model_validate(raw).expand(bundle);before=deepcopy(extraction.model_dump())
    validation=validate_extraction(extraction,bundle)
    assert {'code':'known_unit_incompatible_with_quantity_kind','path':path} in validation['issues']
    assert validation['normalized'][path]['normalized'] is None
    assert not validation['valid'] and not any(r['eligible'] for r in training_exclusions(extraction,bundle,validation)['results'])
    assert extraction.model_dump()==before
