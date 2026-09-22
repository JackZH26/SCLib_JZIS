"""Pure, packaged composition contracts; executed through the guarded runner."""

import copy
import hashlib
import json
import subprocess
import sys
from decimal import localcontext
from pathlib import Path

import pytest

from services._composition import formula_enrichment as parser
from services.ml_composition import ELEMENTS, FEATURE_NAMES, composition_features

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["formula_enrichment", "formula_validator"])
def test_entire_audited_source_parity_and_actual_packaged_source_hash(name):
    original = (ROOT / "ingestion/ingestion/extract" / (name + ".py")).read_bytes()
    packaged = (ROOT / "api/services/_composition" / (name + ".py")).read_bytes()
    assert packaged.replace(
        b"from services._composition import formula_validator",
        b"from ingestion.extract import formula_validator",
    ) == original
    assert composition_features({"formula": "MgB2"})["provenance"]["source_sha256"][name] == (
        hashlib.sha256(packaged).hexdigest()
    )


def test_fixed_118_element_vocabulary_and_composition_only_values():
    expected = """Ac Ag Al Am Ar As At Au B Ba Be Bh Bi Bk Br C Ca Cd Ce Cf Cl Cm
    Cn Co Cr Cs Cu Db Ds Dy Er Es Eu F Fe Fl Fm Fr Ga Gd Ge H He Hf Hg Ho Hs
    I In Ir K Kr La Li Lr Lu Lv Mc Md Mg Mn Mo Mt N Na Nb Nd Ne Nh Ni No Np
    O Og Os P Pa Pb Pd Pm Po Pr Pt Pu Ra Rb Re Rf Rg Rh Rn Ru S Sb Sc Se Sg
    Si Sm Sn Sr Ta Tb Tc Te Th Ti Tl Tm Ts U V W Xe Y Yb Zn Zr""".split()
    assert list(ELEMENTS) == expected
    assert len(expected) == 118
    result = composition_features({"formula_raw": "MgB2"})
    assert result["status"] == "computed"
    assert result["formula_raw"] == "MgB2"
    assert result["reason_codes"] == []
    assert result["feature_names"] == list(FEATURE_NAMES)
    assert len(result["values"]) == 121
    values = dict(zip(result["feature_names"], result["values"]))
    assert values["atomic_fraction_Mg"] == pytest.approx(1 / 3)
    assert values["atomic_fraction_B"] == pytest.approx(2 / 3)
    assert values["atomic_fraction_Nb"] == 0
    assert values["n_elements"] == 2
    assert values["atoms_per_formula"] == 3
    assert values["molar_mass_g_mol"] == 45.925
    assert result["provenance"]["input_hash"] == hashlib.sha256(b"str\0MgB2").hexdigest()


@pytest.mark.parametrize("formula", [
    "MgB2", "LaH10", "Nb", "Tc", "Ca(OH)2", "CuSO4·5H2O", "MgB₂",
    "La1.85Sr0.15CuO4", "DyB2", "TaB2", "YbCo", "K4[Fe(CN)6]", "Mg2B4",
])
def test_features_exactly_follow_audited_parser(formula):
    expected = parser.enrich_formula(formula)
    actual = composition_features({"formula": formula})
    assert expected["composition_status"] == actual["composition_status"] == "exact"
    values = dict(zip(actual["feature_names"], actual["values"]))
    for element in ELEMENTS:
        assert values["atomic_fraction_" + element] == expected["atomic_fractions"].get(element, 0)
    assert values["n_elements"] == expected["n_elements"]
    assert values["atoms_per_formula"] == expected["n_atoms_fu"]
    assert values["molar_mass_g_mol"] == expected["molar_mass_g_mol"]


@pytest.mark.parametrize("formula", [
    "La2-xSrxCuO4", "YBa2Cu3O7-δ", "Bi2Sr2CaCu2O8+delta", "La₂₋ₓSrₓCuO₄",
    "Ag-Au", "(La,Sc)H12", "FeSe/SrTiO3", "CuSO4.5H2O", "T_c", "T_{c}",
    "Tᶜ", "La₂Cu¹⁸O₄", "^{18}O", "[18O]2", "D2O", "LaD10", "O²⁻",
    "Al47-", "H", "C", "hydrogen", "not-a-formula", "", "unknown", "YBa2Cu3O7-",
    *parser._AUDITED_FORMULA_SHORTHANDS,
])
def test_unresolved_never_becomes_absent_element_zeroes(formula):
    expected = parser.enrich_formula(formula)
    actual = composition_features({"formula_raw": formula})
    assert actual["composition_status"] == expected["composition_status"]
    assert actual["status"] == "unavailable"
    assert actual["values"] == [None] * 121
    assert actual["formula_raw"] == formula
    assert actual["reason_codes"]


@pytest.mark.parametrize("record", [
    {"formula_raw": "La₂Cu¹⁸O₄"},
    {"raw_extraction": {"formula_raw": "La₂Cu¹⁸O₄"}},
    {"raw_extraction": {"formula": "La₂Cu¹⁸O₄"}},
    {"formula": "La₂Cu¹⁸O₄"},
])
@pytest.mark.parametrize("as_json", [False, True])
def test_raw_source_isotope_guard_survives_catalog_alias_and_stale_cache(record, as_json):
    records = [record]
    material = {
        "formula": "La2Cu18O4", "records": json.dumps(records) if as_json else records,
        "composition_data": parser.enrich_formula("La2Cu18O4"),
    }
    before = copy.deepcopy(material)
    actual = composition_features(material)
    assert material == before
    assert actual["status"] == "unavailable"
    assert actual["reason_codes"] == ["source_isotope_identity_requires_resolution"]
    assert actual["values"] == [None] * 121
    assert actual["formula_raw"] == "La2Cu18O4"
    assert actual["provenance"]["input_hash"] == parser.enrich_formula("La₂Cu¹⁸O₄")["input_hash"]


def test_no_targets_conditions_cached_features_or_input_mutation():
    first = {"formula": "MgB2", "records": [{"formula_raw": "MgB2", "tc": 39}]}
    changed = copy.deepcopy(first)
    changed.update(tc=10000, tc_kelvin=True, pressure_gpa=900, sample_state="fictional",
                   composition_data={"atomic_fractions": {"B": 0.1, "Mg": 0.9}})
    changed["records"][0].update(tc=-1, temperature=12, raw_extraction={"tc": 1000})
    before = copy.deepcopy(changed)
    assert composition_features(first) == composition_features(changed)
    assert changed == before
    assert composition_features(first) == composition_features(first)


def test_integer_reduction_fractional_formula_unit_and_decimal_context_are_explicit():
    assert composition_features({"formula": "Mg2B4"})["values"] == composition_features({"formula": "MgB2"})["values"]
    first = composition_features({"formula": "La1.85Sr0.15CuO4"})
    assert first["values"][-2] == 7
    with localcontext() as context:
        context.prec = 3
        second = composition_features({"formula": "La1.85Sr0.15CuO4"})
    assert first == second
    assert first["provenance"]["formula_unit_basis"] == "parser_reduced_integer_or_preserved_fractional"


@pytest.mark.parametrize("material", [
    None, [], True, {"formula": 123}, {"formula_raw": False, "formula": "MgB2"},
    {"formula": "MgB2", "records": {}}, {"formula": "MgB2", "records": [None]},
    {"formula": "MgB2", "records": [{"raw_extraction": []}]},
    {"formula": "MgB2", "records": [{"formula_raw": 12}]},
    {"formula": "MgB2", "records": '[{"formula_raw":"D2O","formula_raw":"MgB2"}]'},
    {"formula": "MgB2", "records": "NaN"},
    {"formula": "MgB2", "records": "["}, {"formula": "MgB2", "records": "[[[]]]"},
    {"formula": "MgB2", "records": [{}] * 1001},
    {"formula": "MgB2", "records": " " * 1_048_577},
    {"formula": "MgB2" + " " * 4097}, {"formula": "\ud800"},
])
def test_malformed_or_unbounded_identity_inputs_fail_closed(material):
    result = composition_features(material)
    assert result["status"] == "unavailable"
    assert result["values"] == [None] * 121
    assert result["reason_codes"][0] in {
        "invalid_material_input", "invalid_formula_input", "invalid_source_records",
    }
    json.dumps(result, allow_nan=False)


def test_packaged_import_does_not_load_ingestion_database_or_provider():
    code = """
import sys
before = set(sys.modules)
from services.ml_composition import composition_features
from services.ml_preprocessing import fit_transform
assert composition_features({'formula':'MgB2'})['status'] == 'computed'
assert not any(name.split('.')[0] in {'ingestion','database','sqlalchemy','google','config'}
               for name in set(sys.modules) - before)
"""
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "api",
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
