"""Device descriptors from arXiv:1808.07865v2, Table S1 and Figure S8.

Keep the reported signed angle without wrapping/modulo or lattice-symmetry
reduction. D in V/nm is retained on the source scale; it is not converted to
electric field, gate voltage or SI displacement without a reviewed convention.
Historical registries are unchanged.
"""
from . import quantities as base, quantities_v3 as previous

REGISTRY_VERSION = 'materials-quantities/4.0.0'
ADDITIONS = {'twist_angle': ('deg', {'deg': 1.0, '°': 1.0}, None)}
UNITS = {**previous.UNITS, **ADDITIONS}
DISPLACEMENT_UNITS = ('V/nm',)


def normalize(kind, quantity):
    if kind == 'reported_displacement_field':
        if quantity.status != 'reported':
            return dict(status=quantity.status, normalized=None)
        if base.unit_key(quantity.unit) not in {base.unit_key(u) for u in DISPLACEMENT_UNITS}:
            raise ValueError('unregistered_reported_displacement_field_unit')
        return dict(status='reported', normalized=None,
                    reason='displacement_field_convention_unresolved', source_unit=quantity.unit)
    return base.normalize(kind, quantity, registry=UNITS, registry_version=REGISTRY_VERSION)


def quantity_source_issues(kind, quantity, evidence, field):
    if kind == 'reported_displacement_field':
        return base.unmapped_quantity_source_issues(quantity, evidence, field)
    return base.quantity_source_issues(kind, quantity, evidence, field, registry=UNITS)
