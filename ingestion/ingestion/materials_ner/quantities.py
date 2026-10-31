"""Explicit quantity registry and strict parsing in the SOURCE's units.

Registration does not establish scientific meaning. In particular, a molar
basis, fitted exponent, component, field convention and model remain as stated
in the source and require adjudication before becoming ML features/labels.
Magnetic conversion convention: NIST SP 811 Appendix B.9. Oe maps to A/m,
G maps to T; this registry never equates H with B or silently multiplies by mu0.
"""
from __future__ import annotations

from decimal import Decimal
from math import isclose, pi
import re

from ingestion.extract.scientific_values import parse_scientific_value

REGISTRY_VERSION = "materials-quantities/1.6.8"
# Numeric notation evolves independently of physical kinds and conversions.
NUMERIC_SYNTAX_VERSION = "materials-numeric-syntax/2"

TEMP = ("K", {"K": 1.0, "mK": 0.001}, 0)
LENGTH = ("nm", {"nm": 1.0, "Å": 0.1, "pm": 0.001, "um": 1000.0, "μm": 1000.0,"mm":1e6}, 0)
FLUX = ("T", {"T": 1.0, "mT": 0.001, "μT": 1e-6, "G": 1e-4, "kG": 0.1}, 0)
FIELD = ("A/m", {"A/m": 1.0, "kA/m": 1000.0, "Oe": 1000 / (4 * pi),
                  "kOe": 1e6 / (4 * pi)}, 0)
ENERGY = ("meV", {"meV": 1.0, "eV": 1000.0}, 0)
RATIO = ("1", {"1": 1.0, "%": 0.01}, 0)
MOLAR_C_OVER_T = ("J/(mol K^2)", {"J/(mol K^2)": 1.0, "mJ/(mol K^2)": 0.001}, 0)

# (normal unit, source-unit conversion factors, lower physical domain bound)
UNITS = {
    "tc": TEMP, "model_temperature_scale": TEMP,
    # Reported phonon energy / k_B, not an arbitrary frequency-to-temperature
    # conversion. k_B is exact in SI; retain the reported source energy unit.
    "omega_log": ("K", {**TEMP[1], "meV": 11.604518121550082, "eV": 11604.518121550082}, 0),
    "debye_temperature": TEMP, "magnetic_transition_temperature": TEMP,
    "heat_capacity_maximum_temperature": TEMP, "superfluid_stiffness": TEMP,
    "temperature": ("K", {**TEMP[1], "°C": 1.0, "degC": 1.0}, 0),
    "critical_pressure": ("GPa", {"GPa": 1.0, "MPa": 0.001, "kbar": 0.1, "bar": 0.0001}, 0),
    "pressure": ("GPa", {"GPa": 1.0, "MPa": 0.001, "kbar": 0.1, "bar": 0.0001,
                         "mbar": 1e-7, "kPa": 1e-6, "Pa": 1e-9,
                         # NIST SP 811 tabulated conversion, at its stated precision.
                         "Torr": 1.333224e-7, "mTorr": 1.333224e-10}, 0),
    "hc2": FLUX, "pauli_limit_flux_density": FLUX,
    "hc2_field_strength": FIELD,
    "magnetic_flux_density": (*FLUX[:2], None), "mu0_h": (*FLUX[:2], None),
    "magnetic_field_strength": (*FIELD[:2], None),
    "hc2_flux_density_slope": ("T/K", {"T/K": 1.0, "mT/K": 0.001}, None),
    "hc2_field_strength_slope": ("A/(m K)", {"A/(m K)": 1.0,
        "Oe/K": FIELD[1]["Oe"], "kOe/K": FIELD[1]["kOe"]}, None),
    "tc_field_strength_slope": ("K/(A/m)", {"K/(A/m)": 1.0,
        "K/Oe": 1 / FIELD[1]["Oe"], "K/kOe": 1 / FIELD[1]["kOe"]}, None),
    "tc_flux_density_slope": ("K/T", {"K/T": 1.0, "K/mT": 1000.0}, None),
    "gap_energy": ENERGY, "charge_gap_energy": ENERGY,
    "electron_phonon_lambda": ("1", {"1": 1.0}, 0),
    "thickness": LENGTH, "penetration_depth": LENGTH, "coherence_length": LENGTH,
    "crystalline_domain_size": LENGTH,
    "strain": ("1", RATIO[1], None), "lattice_strain": ("1", RATIO[1], None),
    "relative_debye_temperature_change": ("1", RATIO[1], None),
    "sommerfeld_coefficient_molar": MOLAR_C_OVER_T,
    "heat_capacity_jump_over_tc_molar": MOLAR_C_OVER_T,
    "lattice_heat_capacity_beta_molar": ("J/(mol K^4)", {
        "J/(mol K^4)": 1.0, "mJ/(mol K^4)": 0.001}, 0),
    "normalized_heat_capacity_jump": RATIO, "heat_capacity_fraction": RATIO,
    "gap_amplitude_ratio": RATIO, "pairing_component_fraction": RATIO,
    "quality_factor": ("1", {"1": 1.0}, 0),
    "nmr_relaxation_power_law_exponent": ("1", {"1": 1.0}, None),
    "surface_resistance": ("Ω", {"Ω": 1.0, "mΩ": 0.001, "μΩ": 1e-6}, 0),
    "carrier_density": ("cm^-3", {"cm^-3": 1.0, "m^-3": 1e-6}, 0),
    "gate_voltage": ("V", {"V": 1.0, "mV": 0.001}, None),
    "delay": ("ps", {"ps": 1.0, "fs": 0.001, "ns": 1000.0}, None),
    "electric_current": ("A", {"A":1.0, "mA":1e-3, "uA":1e-6, "μA":1e-6, "µA":1e-6, "nA":1e-9, "pA":1e-12}, 0),
    "frequency": ("Hz", {"Hz": 1.0, "kHz": 1000.0, "MHz": 1e6}, 0),
    "coulomb_pseudopotential": ("1", {"1": 1.0}, 0),
    "resistance_fraction": RATIO,
    "radius": LENGTH,
    "gl_parameter": ("1", {"1":1.0}, 0),
    "superconducting_layer_thickness": LENGTH,
    # Explicit per-atom DOS only. No inferred spin, cell or formula-unit basis.
    "electronic_dos_per_atom": ("states/(eV atom)",{"states/(eV atom)":1.0},0),
}


def lexical(text: str) -> str:
    """Finite presentation-only transformations; no algebra/variable inference."""
    text = text.replace("$", "").replace("−", "-").replace("∼", "≈")
    for before, after in ((r"\,", " "), (r"\;", " "), (r"\!", ""),
                          (r"\%", "%"), (r"\pm", "±"), (r"\Omega", "Ω"),
                          (r"\AA", "Å"), (r"\angstrom", "Å"), (r"\muup", "μ"), (r"\mu", "μ")):
        text = text.replace(before, after)
    text = re.sub(r"\\(?:approx|simeq|sim|cong)(?![A-Za-z])", "≈", text)
    text = re.sub(r"^(?:nearly|around|roughly)\s+", "≈", text, flags=re.I)
    for words,symbol in ((r"at most|not exceeding","≤"),(r"at least|not less than","≥"),
                         (r"lower than|less than|below","<"),(r"higher than|greater than|above",">")):
        text = re.sub(r"^(?:"+words+r")\s+",symbol,text,flags=re.I)
    text = re.sub(r"\\leq?\b", "≤", text)
    text = re.sub(r"\\geq?\b", "≥", text)
    text = re.sub(r"\\(?:left|right)\b", "", text)
    text = re.sub(r"\^\{?\\circ\}?", "°", text)
    text = re.sub(r"\\(?:mathrm|textrm|text|mbox)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\rm\b", "", text)
    text = re.sub(r"\^\{\s*([-+]?)\s*(\d+)\s*\}", r"^\1\2", text)
    text = re.sub(r"\{([-+]?(?:\d+(?:\.\d*)?|\.\d+))\}", r"\1", text)
    text = re.sub(r"(?<=[\d)])~(?=[A-Za-z\\μΩÅ°])", " ", text)
    # Scientific notation only, never arbitrary TeX powers or products.
    text = re.sub(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:\\times|\\cdot|×|·)\s*10\s*\^\s*([-+]?\d+)",
                  r"\1e\2", text)
    return text.strip()


def unit_key(value: str) -> str:
    text = lexical(value).replace("²", "^2").replace("⁴", "^4")
    # The source's plain-text degree glyph in the thin-film deposition table.
    # This exact unit alias never rewrites a chemical formula or numeric token.
    if text in {"oC", "◦C"}:
        text = "°C"
    # All alternatives here have exactly the same dimensions and prefix.
    text = re.sub(r"\b(?:kelvin|Kelvin)\b", "K", text)
    text = re.sub(r"\b(?:tesla|Tesla)\b", "T", text)
    text = re.sub(r"\b(?:angstrom|angstroms)\b", "Å", text)
    # Only these registered unit fractions, not arbitrary scientific fractions.
    text = re.sub(r"\\frac\{(m?J)\}\{mol\s*K\^([24])\}", r"\1/(mol K^\2)", text)
    text = text.replace("Å", "Å").replace("mole", "mol").replace("\\cdot", "")
    text = re.sub(r"[\s(){}*·]", "", text)
    for prefix in ("mJ", "J"):
        for power in (2, 4):
            if text in {f"{prefix}/molK^{power}", f"{prefix}mol^-1K^-{power}",
                        f"{prefix}/mol/K^{power}"}:
                return f"{prefix}/molK^{power}"
    return text


def conversion(kind: str, unit: str, *, registry=None):
    units = UNITS if registry is None else registry
    if kind not in units:
        raise ValueError("unregistered_quantity")
    canonical_unit, conversions, minimum = units[kind]
    source = next((key for key in conversions if unit_key(key) == unit_key(unit)), None)
    if source is None:
        raise ValueError("unregistered_unit")
    return canonical_unit, conversions[source], minimum, source


def unit_offset(kind, source):
    return 273.15 if kind == "temperature" and source in {"°C", "degC"} else 0.0


def normalize(kind: str, quantity, *, registry=None, registry_version=REGISTRY_VERSION) -> dict:
    if quantity.status != "reported":
        return {"status": quantity.status, "normalized": None}
    if kind == 'reported_magnetic_field':
        # Preserve the source scale without equating B, H or mu0 H. Even
        # compatible unit prefixes remain unnormalized until adjudication.
        if unit_key(quantity.unit) not in {unit_key(u) for u in (*FLUX[1], *FIELD[1])}:
            raise ValueError('unregistered_reported_magnetic_field_unit')
        return {'status': 'reported', 'normalized': None,
                'reason': 'magnetic_field_convention_unresolved', 'source_unit': quantity.unit}
    unit, factor, minimum, source = conversion(kind, quantity.unit, registry=registry)
    offset = unit_offset(kind, source)
    values = {key: float(Decimal(str(getattr(quantity, key))) * Decimal(str(factor)) + Decimal(str(offset)))
              for key in ("value", "lower", "upper") if getattr(quantity, key) is not None}
    if minimum is not None and any(value < minimum for value in values.values()):
        raise ValueError("quantity_outside_domain")
    if kind in {"pairing_component_fraction","resistance_fraction"} and any(value > 1 for value in values.values()):
        raise ValueError("fraction_outside_unit_interval")
    uncertainty = quantity.uncertainty.model_dump() if quantity.uncertainty else None
    if uncertainty:
        uncertainty["minus"] *= factor
        uncertainty["plus"] *= factor
    return {"status": "reported", "normalized": {
        "relation": quantity.relation, **values, "unit": unit,
        "approximate": quantity.approximate, "uncertainty": uncertainty,
        "conversion": {"registry": registry_version, "input_unit": quantity.unit,
                       "factor": factor, "offset": offset,
                       **({"convention": "reported phonon energy / k_B"}
                          if kind == "omega_log" and source in {"meV", "eV"} else {})}}}


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
PAREN_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)\((?:\d+(?:\.\d+)?|\.\d+)\)(?:[eE][-+]?\d+)?"
NUMERIC_PREFIX = re.compile(
    rf"^((?:(?:~|≈|about\s+|approximately\s+)\s*)?"
    rf"(?:{PAREN_NUMBER}|(?:(?:<=|>=|<|>|≤|≥)\s*)?{NUMBER}"
    rf"(?:\s*(?:±|\+/-|–|—|-|to|~)\s*{NUMBER})?))\s*(.*?)$", re.I)
ENDPOINT_UNITS_RANGE = re.compile(rf"^({NUMBER})\s*(.+?)\s*(?:to|–|—|-|~)\s*({NUMBER})\s*(.+?)$", re.I)


def numeric_presentation(token):
    """Finite source-number notation, never a formula or unit rewrite.

    The literal remains unchanged. A TeX en-dash is an interval delimiter;
    an approximate inequality retains both its relation and approximation.
    Unit compatibility and full quantity shape are checked by the callers.
    """
    token = re.sub(r'^(?:\\lesssim(?![A-Za-z])|≲)\s*', '≈ ≤ ', token)
    token = re.sub(r'^(?:\\gtrsim(?![A-Za-z])|≳)\s*', '≈ ≥ ', token)
    between = re.fullmatch(rf'between\s+({NUMBER})(.*?)\s+and\s+({NUMBER})(.*?)', token, re.I)
    if between:
        token = f'{between[1]}{between[2]} to {between[3]}{between[4]}'
    # A third adjacent hyphen is ambiguous with a negative endpoint/em dash.
    # An explicitly spaced negative endpoint remains a signed number.
    interval = re.fullmatch(rf'({NUMBER})\s*(?<!-)--(?!-)\s*({NUMBER})(.*)', token)
    if interval:
        token = f'{interval[1]} to {interval[2]}{interval[3]}'
    return token


def parse_source_numeric(numeric):
    """Read adjacent parenthetical uncertainty without losing its full syntax.

    Integer digits refer to the final decimal places; a decimal expression
    specifies an absolute uncertainty on the mantissa's scale. An external
    exponent scales both. This recognizes notation, not scientific meaning.

    Do not interpret spaced parenthetical numbers (possible footnotes), assign
    a confidence level, or infer uncertainty from decimal precision alone.
    The legacy scientific-value parser and historical records remain unchanged.
    """
    # A tilde BETWEEN two numeric endpoints is a range in the source's phase
    # notation. Leading ~ remains approximation. Limit the rewrite to a complete
    # two-endpoint expression; never normalize an arbitrary formula or list.
    interval = re.fullmatch(rf"(?P<prefix>(?:(?:~|≈|about\s+|approximately\s+)\s*)?)"
                            rf"(?P<lower>{NUMBER})\s*~\s*(?P<upper>{NUMBER})", numeric, re.I)
    if interval:
        numeric = f'{interval["prefix"]}{interval["lower"]} to {interval["upper"]}'
    match = re.fullmatch(r"(?P<approx>(?:(?:~|≈|about\s+|approximately\s+)\s*)?)"
                         r"(?P<mantissa>[-+]?(?:\d+(?:\.\d*)?|\.\d+))"
                         r"\((?P<digits>\d+(?:\.\d+)?|\.\d+)\)(?:[eE](?P<exp>[-+]?\d+))?", numeric, re.I)
    if match:
        mantissa = match["mantissa"]
        exponent = int(match["exp"] or 0)
        if abs(exponent) > 300 or len(match["digits"]) > 100:
            return {"status": "invalid", "errors": ["parenthetical_numeric_bound"]}
        places = len(mantissa.split(".")[1]) if "." in mantissa else 0
        value = Decimal(mantissa).scaleb(exponent)
        uncertainty = Decimal(match["digits"]).scaleb(
            exponent if '.' in match["digits"] else exponent - places)
        numeric = f'{match["approx"]}{value} ± {uncertainty}'
    return parse_scientific_value(numeric, "lambda_eph", raw_unit="1")


def nonreported_unit_issues(kind, quantity, *, registry=None):
    """Missing numbers do not make a known foreign unit dimensionless.

    Unknown units stay unresolved; this check does not infer their dimension,
    register a new type, recover a value or mutate the source quantity.
    """
    units = UNITS if registry is None else registry
    if quantity.status == "reported" or quantity.unit is None or kind not in units:
        return []
    try:
        conversion(kind, quantity.unit, registry=registry)
    except ValueError:
        token = unit_key(quantity.unit)
        if any(token == unit_key(unit) for _, units, _ in units.values() for unit in units):
            return ["known_unit_incompatible_with_quantity_kind"]
    return []


def quantity_source_issues(kind, quantity, evidence, field, *, registry=None):
    if kind == 'reported_magnetic_field':
        return unmapped_quantity_source_issues(quantity, evidence, field)
    if quantity.status != "reported":
        return nonreported_unit_issues(kind, quantity, registry=registry)
    from .field_quantity import enabled, field_quantity_issues
    if enabled(evidence, field):
        return field_quantity_issues(quantity, evidence, field)
    quotes = [e.quote for e in evidence if e.field == field]
    if not any(" ".join(quantity.raw.split()) in " ".join(q.split()) for q in quotes):
        return ["quantity_raw_not_in_field_evidence"]
    token = numeric_presentation(lexical(quantity.raw))
    if kind == "electron_phonon_lambda":
        token = re.sub(r"^(?:\\lambda|λ)\s*=\s*", "", token)
    endpoint = ENDPOINT_UNITS_RANGE.fullmatch(token)
    if endpoint:
        low, low_unit, high, high_unit = endpoint.groups()
        try:
            conversions = [conversion(kind,u,registry=registry) for u in (low_unit,high_unit,quantity.unit)]
        except ValueError:
            # Leave ordinary one-unit ranges to the existing parser below.
            pass
        else:
            signatures={(c[1],unit_offset(kind,c[3])) for c in conversions}
            if len(signatures)!=1:
                return ["numeric_source_unit_mismatch"]
            # Both endpoint units have the same source scale and offset. This
            # does not repair mixed-unit intervals or lists joined by 'and'.
            token=f"{low} to {high} {quantity.unit}"
    match = NUMERIC_PREFIX.fullmatch(token)
    if not match:
        return ["numeric_raw_requires_review"]
    numeric, inline_unit = match.groups()
    # A source may use a number-unit adjective, e.g. "8-nm" in
    # "8-nm-thick". Only an adjacent ASCII hyphen before a registered unit
    # is punctuation here. Do not strip a range delimiter, minus sign,
    # arbitrary suffix, or a spaced/ambiguous dash. Raw evidence is unchanged.
    if inline_unit.startswith("-") and token == numeric + inline_unit:
        try:
            conversion(kind, inline_unit[1:], registry=registry)
        except ValueError:
            pass
        else:
            inline_unit = inline_unit[1:]
    if inline_unit:
        # An explicit unit disagreement is never repaired by stripping a unit.
        try:
            _, source_factor, _, source_unit = conversion(kind, inline_unit, registry=registry)
            _, declared_factor, _, declared_unit = conversion(kind, quantity.unit, registry=registry)
        except ValueError:
            return ["numeric_source_unit_mismatch"]
        if (source_factor,unit_offset(kind,source_unit)) != (declared_factor,unit_offset(kind,declared_unit)):
            return ["numeric_source_unit_mismatch"]
    return numeric_shape_issues(numeric, quantity)


def unmapped_quantity_source_issues(quantity, evidence, field):
    """Check literal numeric shape without registering a physical meaning.

    Unknown dimensions never receive conversions or domain bounds here. Units
    must match in source presentation (apart from whitespace and finite TeX
    formatting); parentheses and division scope are retained. A successful
    check is not permission to normalize or promote an unregistered quantity.
    """
    if quantity.status != "reported":
        return []
    from .field_quantity import enabled, field_quantity_issues
    if enabled(evidence, field):
        return field_quantity_issues(quantity, evidence, field)
    quotes = [e.quote for e in evidence if e.field == field]
    if not any(" ".join(quantity.raw.split()) in " ".join(q.split()) for q in quotes):
        return ["quantity_raw_not_in_field_evidence"]
    token = numeric_presentation(lexical(quantity.raw))
    unit = lambda value: re.sub(r"\s+", "", lexical(value))
    declared = unit(quantity.unit)
    endpoint = ENDPOINT_UNITS_RANGE.fullmatch(token)
    if endpoint:
        low, low_unit, high, high_unit = endpoint.groups()
        if declared and unit(low_unit) == unit(high_unit) == declared:
            token = f"{low} to {high} {quantity.unit}"
    match = NUMERIC_PREFIX.fullmatch(token)
    if not match:
        return ["numeric_raw_requires_review"]
    numeric, inline_unit = match.groups()
    issues = []
    if inline_unit and unit(inline_unit) != declared:
        issues.append("numeric_source_unit_mismatch")
    return issues + numeric_shape_issues(numeric, quantity)


def numeric_shape_issues(numeric, quantity):
    """Compare the source expression, never infer a mean or an error bar."""
    parsed = parse_source_numeric(numeric)
    if parsed["status"] != "parsed" or parsed["errors"]:
        return ["numeric_raw_requires_review"]
    def equal(left, right):
        if left is None or right is None:
            return left is right
        return isclose(left, right, rel_tol=1e-12, abs_tol=1e-15)
    if parsed["relation"] != quantity.relation or any(
            not equal(parsed.get(key), getattr(quantity, key)) for key in ("value", "lower", "upper")):
        return ["numeric_value_disagrees_with_raw"]
    if parsed["approximate"] and not quantity.approximate:
        return ["approximation_marker_lost"]
    if parsed["uncertainty"] is not None:
        if quantity.uncertainty is None:
            return ["uncertainty_lost"]
        if not all(equal(value, parsed["uncertainty"]) for value in (
                quantity.uncertainty.minus, quantity.uncertainty.plus)):
            return ["uncertainty_disagrees_with_raw"]
    elif quantity.uncertainty is not None:
        return ["uncertainty_not_in_raw_requires_review"]
    return []


REGISTRY_INSTRUCTIONS = """
QUANTITY REGISTRY (preserve the source units and exact quantity name):
tc is a superconducting transition temperature, never a magnetic ordering
temperature, Debye temperature, derivative or maximum of a broad heat capacity.
Use magnetic_transition_temperature, debye_temperature,
heat_capacity_maximum_temperature, or model_temperature_scale for those cases.
hc2 is an upper critical B or mu0H expressed in T/mT/G/kG. A value of Hc2 in
Oe/kOe/A/m uses hc2_field_strength. Never convert Oe to T in your output.
Pauli limiting fields in tesla use pauli_limit_flux_density, not measured hc2.
Use hc2_flux_density_slope (T/K), hc2_field_strength_slope (Oe/K, kOe/K),
tc_flux_density_slope (K/T), or tc_field_strength_slope (K/Oe, K/kOe) for derivatives.
Retain a printed sign; do not infer the sign of a reported suppression magnitude.
penetration_depth, coherence_length, crystalline_domain_size use Å/nm/μm etc.
superconducting gap_energy and charge_gap_energy are distinct (meV/eV).
sommerfeld_coefficient_molar is gamma (mJ/(mol K^2) or J/(mol K^2));
lattice_heat_capacity_beta_molar is beta of beta*T^3 (mJ/(mol K^4) or J/(mol K^4)).
heat_capacity_jump_over_tc_molar is Delta C/Tc (mJ/(mol K^2) or J/(mol K^2)).
Keep any printed inconsistent unit; mark ambiguous and describe the conflict.
Do not silently repair a K^2/K^4 typo or infer a molar formula-unit/atom basis.
normalized_heat_capacity_jump is Delta C/(gamma*Tc), not Delta C/C_lattice;
the latter is heat_capacity_fraction. Both are dimensionless.
lattice_strain and relative_debye_temperature_change preserve ratio or %.
gap_amplitude_ratio requires component_raw to identify numerator/denominator.
pairing_component_fraction requires component_raw to identify e.g. d-wave/s-wave.
For a printed 83%, report value=83 and unit="%", never value=83 with unit="1";
the program converts it to 0.83. Do not pre-normalize a source percentage.
surface_resistance uses Ω/mΩ/μΩ. quality_factor is dimensionless unit="1".
nmr_relaxation_power_law_exponent is only an explicit numeric power, e.g. the 3
in T^3, with raw="3", unit="1" and component_raw retaining the full scaling law.
Never turn the whole law T^3 into a numeric rate. If not resolvable, keep unmapped.
Unknown coefficients/functions/units stay unmapped or ambiguous; registration
is not permission to substitute a different physical quantity or derive a value.
"""
