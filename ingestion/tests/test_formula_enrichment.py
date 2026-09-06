"""Phase-1 formula classification and exact-composition enrichment tests."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.extract.formula_enrichment import (
    PARSER_NAME,
    PARSER_VERSION,
    composition_cache_is_current,
    enrich_formula,
    enrich_material_composition,
)


@pytest.mark.parametrize(
    ("formula", "reduced", "anonymous", "system", "amounts", "atoms", "mass"),
    [
        (
            "MgB2",
            "MgB2",
            "AB2",
            "B-Mg",
            {"B": 2, "Mg": 1},
            3,
            45.925,
        ),
        (
            "LaH10",
            "LaH10",
            "AB10",
            "H-La",
            {"H": 10, "La": 1},
            11,
            148.98547,
        ),
    ],
)
def test_exact_superconductor_formula_enrichment(
    formula, reduced, anonymous, system, amounts, atoms, mass
):
    result = enrich_formula(formula)

    assert result["composition_status"] == "exact"
    assert result["formula_reduced"] == reduced
    assert result["formula_anonymous"] == anonymous
    assert result["chemical_system"] == system
    assert result["element_amounts"] == amounts
    assert result["n_elements"] == len(amounts)
    assert result["n_atoms_fu"] == atoms
    assert result["molar_mass_g_mol"] == pytest.approx(mass, abs=1e-6)
    assert sum(result["atomic_fractions"].values()) == pytest.approx(1.0)
    assert result["errors"] == []


def test_variable_formula_is_not_coerced_to_exact_composition():
    result = enrich_formula("La2-xSrxCuO4")

    assert result["composition_status"] == "variable"
    assert result["variable_symbols"] == ["x"]
    _assert_has_no_exact_descriptors(result)


@pytest.mark.parametrize("formula", ["YBa2Cu3O7-δ", "YBa2Cu3O7-d", "Bi2Sr2CaCu2O8+delta"])
def test_delta_notations_are_variable(formula):
    result = enrich_formula(formula)

    assert result["composition_status"] == "variable"
    assert result["variable_symbols"] == ["delta"]
    _assert_has_no_exact_descriptors(result)


def test_alloy_system_is_a_mixture_not_fictitious_agau():
    result = enrich_formula("Ag-Au")

    assert result["composition_status"] == "mixture"
    _assert_has_no_exact_descriptors(result)


def test_alternative_site_is_a_mixture_without_assumed_ratio():
    result = enrich_formula("(La,Sc)H12")

    assert result["composition_status"] == "mixture"
    _assert_has_no_exact_descriptors(result)


def test_slash_separated_materials_are_an_interface():
    result = enrich_formula("FeSe/SrTiO3")

    assert result["composition_status"] == "interface"
    _assert_has_no_exact_descriptors(result)


def test_invalid_formula_carries_machine_readable_error():
    result = enrich_formula("not-a-formula")

    assert result["composition_status"] == "invalid"
    _assert_has_no_exact_descriptors(result)
    assert result["errors"] == ["validator:no_uppercase_element"]


def test_parser_supports_groups_hydrates_and_unicode_subscripts():
    grouped = enrich_formula("Ca(OH)2")
    hydrate = enrich_formula("CuSO4·5H2O")
    unicode_formula = enrich_formula("MgB₂")

    assert grouped["element_amounts"] == {"Ca": 1, "H": 2, "O": 2}
    assert grouped["formula_reduced"] == "CaO2H2"
    assert hydrate["element_amounts"] == {"Cu": 1, "H": 10, "O": 9, "S": 1}
    assert unicode_formula["formula_reduced"] == "MgB2"


def test_ascii_hydrate_dot_is_rejected_instead_of_becoming_false_exact():
    ambiguous = enrich_formula("CuSO4.5H2O")

    assert ambiguous["composition_status"] == "invalid"
    assert ambiguous["errors"] == ["ambiguous_ascii_hydrate_separator"]
    _assert_has_no_exact_descriptors(ambiguous)


@pytest.mark.parametrize("notation", ["T_c", "T_{c}", "$T_{c}$", "Tᶜ"])
def test_tc_physical_quantity_notation_is_not_technetium(notation: str):
    result = enrich_formula(notation)

    assert result["composition_status"] == "invalid"
    assert result["errors"] == ["physical_quantity_not_formula"]
    _assert_has_no_exact_descriptors(result)

    technetium = enrich_formula("Tc")
    assert technetium["composition_status"] == "exact"
    assert technetium["formula_reduced"] == "Tc"


@pytest.mark.parametrize(
    "shorthand",
    [
        "YBCO",
        "ybco",
        "Y123",
        "Y124",
        "BSCCO",
        "Bi2212",
        "Bi2201",
        "Bi2223",
        "LSCO",
        "LBCO",
        "NCCO",
        "PCCO",
        "PCCCO",
        "LCO",
        "La214",
        "Hg1201",
        "Hg1212",
        "Hg1223",
        "Tl2201",
        "Tl2212",
        "Tl2223",
        "HBCO",
        "CSH",
    ],
)
def test_material_shorthand_is_never_parsed_as_false_exact(shorthand: str):
    result = enrich_formula(shorthand)

    assert result["composition_status"] == "invalid"
    assert result["errors"] == ["formula_shorthand_requires_resolution"]
    assert result["input_alias"] == shorthand
    _assert_has_no_exact_descriptors(result)


@pytest.mark.parametrize("element", ["Bi", "Hg", "Tl", "Nb", "Tc"])
def test_real_element_symbol_remains_exact(element: str):
    result = enrich_formula(element)

    assert result["composition_status"] == "exact"
    assert result["formula_reduced"] == element


def test_mixed_case_real_formula_does_not_collide_with_uppercase_shorthand():
    result = enrich_formula("YbCo")

    assert result["composition_status"] == "exact"
    assert result["element_amounts"] == {"Co": 1, "Yb": 1}


def test_integer_formula_is_reduced_but_fractional_occupancy_is_preserved():
    doubled = enrich_formula("Mg2B4")
    doped = enrich_formula("La1.85Sr0.15CuO4")

    assert doubled["formula_reduced"] == "MgB2"
    assert doubled["element_amounts"] == {"B": 2, "Mg": 1}
    assert doubled["n_atoms_fu"] == 3
    assert doped["formula_reduced"] == "La1.85Sr0.15CuO4"
    assert doped["n_atoms_fu"] == pytest.approx(7.0)


def test_output_is_idempotent_and_has_deterministic_provenance_and_key_order():
    first = enrich_formula("MgB2")
    second = enrich_formula("MgB2")

    assert first == second
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
    assert list(first["element_amounts"]) == ["B", "Mg"]
    assert list(first["atomic_fractions"]) == ["B", "Mg"]
    assert first["parser_name"] == PARSER_NAME
    assert first["parser_version"] == PARSER_VERSION
    assert first["input_hash"] == hashlib.sha256(b"str\0MgB2").hexdigest()


def test_none_input_is_invalid_and_still_hashable_for_audit():
    first = enrich_formula(None)  # type: ignore[arg-type]
    second = enrich_formula(None)  # type: ignore[arg-type]

    assert first == second
    assert first["composition_status"] == "invalid"
    assert first["errors"] == ["empty_formula"]
    assert len(first["input_hash"]) == 64


@pytest.mark.parametrize("formula", [
    "La₂Cu¹⁸O₄", "^{18}O", "$La_2Cu^{18}O_4$", "18O", "[18O]2",
    "D2O", "LaD10", "H0.5D0.5", "H/D", "La₂Cu¹⁶O₂¹⁸O₂", "O²⁻",
])
def test_isotope_and_charge_notation_fails_closed_before_normalization(formula):
    result = enrich_formula(formula)
    assert result["composition_status"] == "invalid"
    assert result["errors"] == ["isotope_or_charge_requires_resolution"]
    assert result["formula_raw"] == formula
    assert result["isotope_notation"]["mentions"]
    _assert_has_no_exact_descriptors(result)


def test_unicode_variables_and_ordinary_subscripts_are_not_isotope_counts():
    assert enrich_formula("La₂₋ₓSrₓCuO₄")["composition_status"] == "variable"
    assert enrich_formula("MgB₂")["element_amounts"] == {"Mg": 1, "B": 2}
    assert enrich_formula("TaB2")["composition_status"] == "exact"
    assert enrich_formula("DyB2")["composition_status"] == "exact"


def test_cached_old_or_tampered_exact_features_cannot_be_reused():
    current = enrich_formula("MgB2")
    assert composition_cache_is_current("MgB2", current)
    assert not composition_cache_is_current("MgB2", {**current, "parser_version": "1.0.3"})
    assert not composition_cache_is_current("MgB2", {**current, "atomic_fractions": {"Mg": .9, "B": .1}})
    assert not composition_cache_is_current("La₂Cu¹⁸O₄", enrich_formula("La2Cu18O4"))


def test_material_composition_does_not_override_raw_isotope_with_catalog_alias():
    result = enrich_material_composition({
        "formula": "La2Cu18O4",
        "records": [{"formula_raw": "La₂Cu¹⁸O₄"}],
    })
    assert result["composition_status"] == "invalid"
    assert result["errors"] == ["source_isotope_identity_requires_resolution"]
    assert result["catalog_formula"] == "La2Cu18O4"
    _assert_has_no_exact_descriptors(result)


def _assert_has_no_exact_descriptors(result):
    for key in (
        "formula_reduced",
        "formula_anonymous",
        "chemical_system",
        "element_amounts",
        "atomic_fractions",
        "n_elements",
        "n_atoms_fu",
        "molar_mass_g_mol",
    ):
        assert result[key] is None
