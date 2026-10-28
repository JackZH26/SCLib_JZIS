"""Opt-in source-tested pressure slopes and longitudinal electrical resistivity.

This registry belongs to native contract 12. Historical registry 1.6.8 and
all historical native contracts keep their original meanings and hashes.
"""
from . import quantities as previous

REGISTRY_VERSION = 'materials-quantities/2.0.0'
ADDITIONS = {
    'tc_pressure_slope': ('K/GPa', {
        'K/GPa': 1.0, 'K GPa^-1': 1.0, 'K GPa-1': 1.0, 'K GPa⁻¹': 1.0,
        'K/kbar': 10.0, 'mK/GPa': .001}, None),
    'electrical_resistivity': ('Ω m', {
        'Ω m': 1.0, 'Ω cm': .01, 'mΩ cm': 1e-5,
        'μΩ cm': 1e-8, 'µΩ cm': 1e-8, 'uΩ cm': 1e-8, 'µΩ·cm': 1e-8}, 0),
}
UNITS = {**previous.UNITS, **ADDITIONS}
DEFINITIONS = {
    'tc_pressure_slope': {
        'definition': 'Reported pressure derivative or local pressure slope of a source-defined superconducting transition temperature.',
        'domain': 'signed', 'tc_prediction_feature': False,
        'required_context': 'Tc definition, pressure range or regime when reported, method, specimen scope and cited/current provenance.'},
    'electrical_resistivity': {
        'definition': 'Reported longitudinal electrical resistivity; not resistance, sheet resistance, Hall resistivity or an uncalibrated normalized trace.',
        'domain': 'nonnegative', 'tc_prediction_feature': False,
        'required_context': 'Temperature, pressure, current direction and specimen scope when reported; retain normalization-reference relationships separately.'},
}


def conversion(kind, unit):
    return previous.conversion(kind, unit, registry=UNITS)


def normalize(kind, quantity):
    return previous.normalize(kind, quantity, registry=UNITS, registry_version=REGISTRY_VERSION)


def quantity_source_issues(kind, quantity, evidence, field):
    return previous.quantity_source_issues(kind, quantity, evidence, field, registry=UNITS)
