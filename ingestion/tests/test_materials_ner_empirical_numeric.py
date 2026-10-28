"""Source-driven numeric regressions; synthetic assertions are not scientific Gold."""
import pytest

from ingestion.materials_ner.contract import Evidence, Quantity, Uncertainty
from ingestion.materials_ner.quantities import normalize, quantity_source_issues


def check(raw, value, error=None, *, unit="K", kind="tc", quote=None):
    q = Quantity(status="reported", raw=raw, relation="exact", value=value, lower=None,
                 upper=None, unit=unit, approximate=False,
                 uncertainty=None if error is None else Uncertainty(
                     kind="reported_unspecified", minus=error, plus=error, raw=raw))
    return q, quantity_source_issues(kind, q, [Evidence(
        block_id="synthetic", quote=raw if quote is None else quote, field="/quantity")], "/quantity")


@pytest.mark.parametrize("raw,value,error", [
    ("8.897(1)", 8.897, .001), ("6.610(7)", 6.610, .007),
    ("6.63(1) K", 6.63, .01), ("1.23(4)e2 K", 123., 4.),
    ("0.980(7) meV", .980, .007),
    ("920(10)", 920., 10.), ("920(10)e-2 K", 9.2, .1),
])
def test_parenthetical_uncertainty_preserves_reported_decimal_places(raw, value, error):
    unit, kind = ("meV", "gap_energy") if "meV" in raw else ("K", "tc")
    _, issues = check(raw, value, error, unit=unit, kind=kind)
    assert issues == []


def test_parenthetical_error_cannot_be_dropped_or_changed():
    assert check("8.897(1) K", 8.897)[1] == ["uncertainty_lost"]
    assert check("8.897(1) K", 8.897, .01)[1] == ["uncertainty_disagrees_with_raw"]


def test_possible_footnote_and_concatenated_table_header_are_not_repaired():
    assert check("8.897 (1) K", 8.897, .001)[1]
    assert check("6.610(7) [K]", 6.610, .007,
                 quote="Tc [K] 6.610(7) 6.63(1)")[1] == ["quantity_raw_not_in_field_evidence"]


def test_phonon_energy_normalization_has_explicit_convention():
    q, issues = check("74.32", 74.32, unit="meV", kind="omega_log")
    assert issues == []
    normalized = normalize("omega_log", q)["normalized"]
    assert normalized["value"] == pytest.approx(862.447787)
    assert normalized["conversion"]["convention"] == "reported phonon energy / k_B"
    assert q.unit == "meV" and q.value == 74.32


def test_millitorr_conversion_does_not_reclassify_its_condition_role():
    q, issues = check("150 mTorr", 150., unit="mTorr", kind="pressure")
    assert issues == []
    assert normalize("pressure", q)["normalized"]["value"] == pytest.approx(1.999836e-8)
    # This parser provides no ambient flag and cannot turn synthesis into measurement.
    assert "ambient" not in normalize("pressure", q)


def test_range_midpoint_and_wrong_unit_remain_rejected():
    assert check("4.20-5.11 K", 4.655)[1] == ["numeric_value_disagrees_with_raw"]
    assert check("74.32 meV", 74.32, unit="K", kind="omega_log")[1] == ["numeric_source_unit_mismatch"]


def test_integer_parenthetical_uncertainty_keeps_length_unit_and_precision():
    q,issues=check("920(10) nm",920.,10.,unit="nm",kind="penetration_depth")
    assert issues==[] and normalize("penetration_depth",q)["normalized"]["uncertainty"]["plus"]==10
    assert check("920 (10) nm",920.,10.,unit="nm",kind="penetration_depth")[1]


def test_celsius_alias_retains_affine_offset_and_never_approves_kelvin_relabeling():
    q,issues=check("740 oC",740.,unit="oC",kind="temperature")
    assert issues==[] and normalize("temperature",q)["normalized"]["value"]==1013.15
    assert check("0 °C",0.,unit="K",kind="temperature")[1]==["numeric_source_unit_mismatch"]
    assert check("273.15 K",273.15,unit="degC",kind="temperature")[1]==["numeric_source_unit_mismatch"]


def test_explicit_both_endpoint_units_preserve_interval_not_midpoint():
    q=Quantity(status="reported",raw="5 mT to 90 mT",relation="interval",lower=5.,upper=90.,unit="mT")
    evidence=[Evidence(block_id="synthetic",quote=q.raw,field="/quantity")]
    assert quantity_source_issues("magnetic_flux_density",q,evidence,"/quantity")==[]
    assert check(q.raw,47.5,unit="mT",kind="magnetic_flux_density")[1]==["numeric_value_disagrees_with_raw"]
    q.raw="5 mT to 0.09 T";evidence[0].quote=q.raw
    assert quantity_source_issues("magnetic_flux_density",q,evidence,"/quantity")==["numeric_source_unit_mismatch"]


def test_separate_values_and_frequency_cannot_be_coerced_into_a_scalar_or_delay():
    assert check("0.25 meV and 0.46 meV",.355,unit="meV",kind="gap_energy")[1]
    q,_=check("1.5625 Hz",1.5625,unit="Hz",kind="delay")
    with pytest.raises(ValueError,match="unregistered_unit"):
        normalize("delay",q)


def test_source_hyphenated_number_unit_keeps_the_literal_and_value():
    # arXiv:2604.07807v1, p.2: Film A (8-nm-thick).
    q, issues = check("8-nm", 8., unit="nm", kind="thickness",
                      quote="Film A (8-nm-thick)")
    assert issues == [] and q.raw == "8-nm" and q.value == 8.
    assert normalize("thickness", q)["normalized"]["value"] == 8.
    # The minus sign in a signed physical quantity is still numeric.
    assert check("-5-mT", -5., unit="mT", kind="magnetic_flux_density")[1] == []


@pytest.mark.parametrize("raw,value,unit", [
    ("8-nm", 8., "Å"), ("8-nm", 80., "nm"),
    ("8-nm-thick", 8., "nm"), ("8 - nm", 8., "nm"),
    ("8--nm", 8., "nm"), ("8–nm", 8., "nm"),
    ("8-9 nm", 8.5, "nm"), ("8-9-nm", 8.5, "nm"),
])
def test_hyphenated_unit_does_not_hide_wrong_units_ranges_or_extra_words(raw, value, unit):
    assert check(raw, value, unit=unit, kind="thickness")[1]


def test_hyphenated_unit_still_requires_its_own_literal_source_evidence():
    assert check("8-nm", 8., unit="nm", kind="thickness", quote="Film B is 5 nm thick.")[1] == [
        "quantity_raw_not_in_field_evidence"]


@pytest.mark.parametrize("raw", ["10 ~ 30 GPa", "10~30 GPa", "10 GPa ~ 30 GPa"])
def test_tilde_between_pressure_endpoints_keeps_bounds_and_source_units(raw):
    # arXiv:2301.01120v1 p.10 phase extent; this syntax check does not establish
    # that the range is the measurement condition of a particular Tc.
    q = Quantity(status="reported", raw=raw, relation="interval", lower=10, upper=30, unit="GPa")
    evidence = [Evidence(block_id="synthetic", quote=raw, field="/quantity")]
    assert quantity_source_issues("pressure", q, evidence, "/quantity") == []
    normalized = normalize("pressure", q)["normalized"]
    assert normalized['lower'] == 10 and normalized['upper'] == 30 and 'value' not in normalized
    assert q.raw == raw
    assert check(raw, 20, unit="GPa", kind="pressure")[1] == ["numeric_value_disagrees_with_raw"]
    q.unit = "MPa"
    assert quantity_source_issues("pressure", q, evidence, "/quantity") == ["numeric_source_unit_mismatch"]


def test_leading_tilde_remains_approximation_without_an_invented_interval():
    q = Quantity(status="reported", raw="~4.6 K", relation="exact", value=4.6, unit="K", approximate=True)
    evidence = [Evidence(block_id="synthetic", quote=q.raw, field="/quantity")]
    assert quantity_source_issues("tc", q, evidence, "/quantity") == []
    q.approximate = False
    assert quantity_source_issues("tc", q, evidence, "/quantity") == ["approximation_marker_lost"]


@pytest.mark.parametrize("raw", ["10 ~ 30 ~ 50 GPa", "10 ≈ 30 GPa", "30 ~ 10 GPa", "10 MPa ~ 30 GPa"])
def test_tilde_does_not_repair_lists_equations_reverse_bounds_or_mixed_units(raw):
    q = Quantity(status="reported", raw=raw, relation="interval", lower=10, upper=30, unit="GPa")
    assert quantity_source_issues("pressure", q, [Evidence(block_id="synthetic", quote=raw, field="/quantity")], "/quantity")
