"""Opt-in inverse-square penetration depth, native contract /14.

Source case: arXiv:0804.4026v3, the paragraph beginning 'By smoothly
extrapolating'. The source gives lambda(0)^-2 in inverse square micrometres.
SI prefixes: https://www.nist.gov/pml/owm/metric-si-prefixes
1 micrometre = 1000 nanometres, hence 1 micrometre^-2 = 1e-6 nm^-2.
Only unit scaling occurs here. No reciprocal, square root, carrier-density,
effective-mass or stiffness conversion is inferred.
"""
from . import quantities as base, quantities_v2 as previous

REGISTRY_VERSION = 'materials-quantities/3.0.0'
ADDITIONS = {
    'inverse_square_penetration_depth': ('nm^-2', {
        'nm^-2': 1.0, 'nm⁻²': 1.0,
        'μm^-2': 1e-6, 'µm^-2': 1e-6, 'um^-2': 1e-6,
        'μm⁻²': 1e-6, 'µm⁻²': 1e-6,
        'm^-2': 1e-18, 'm⁻²': 1e-18,
    }, 0),
}
UNITS = {**previous.UNITS, **ADDITIONS}
DEFINITIONS = {
    'inverse_square_penetration_depth': {
        'definition': 'The reported inverse square of a magnetic penetration depth, lambda^-2.',
        'dimension': 'length^-2', 'domain': 'nonnegative',
        'tc_prediction_feature': False,
        'required_context': 'Reported penetration-depth definition, spatial component or averaging, temperature role, method, specimen and primary/cited attribution. Retain derivation dependencies.',
        'not_equivalent_to': ['dimensionless normalized superfluid density', 'carrier number density',
                              'energy or temperature-valued superfluid stiffness'],
    },
}


def conversion(kind, unit):
    return base.conversion(kind, unit, registry=UNITS)


def normalize(kind, quantity):
    return base.normalize(kind, quantity, registry=UNITS, registry_version=REGISTRY_VERSION)


def quantity_source_issues(kind, quantity, evidence, field):
    return base.quantity_source_issues(kind, quantity, evidence, field, registry=UNITS)
