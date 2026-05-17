"""Lock the formula validator: garbage stays rejected, real (incl.
exotic) formulas stay accepted.

This is also the lockstep anchor referenced by
formula_validator.py's module docstring. The validator's rules are
mirrored in api/main.py (hourly audit) and api/alembic/versions/
0020 + 0034 (Postgres regex); when you extend any rule, extend the
MUST_REJECT / MUST_PASS tables here too.

Pure functions, no DB. Run: ``pytest ingestion/tests/`` (or this file
directly).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from ingestion.extract import formula_validator as V  # noqa: E402


# Real formulas — incl. exotic — that MUST keep validating. This table
# guards against false-rejection regressions (the main risk of any
# validator tightening).
MUST_PASS = [
    "MgB2", "FeSe", "Nb3Sn", "V3Si", "PbMo6S8", "YNi2B2C",
    "YBa2Cu3O7-δ", "YBa2Cu3O7-d", "La1.85Sr0.15CuO4",
    "Bi2Sr2CaCu2O8+δ", "Hg0.8Tl0.2Ba2Ca2Cu3O8",
    "Pr1.85Ce0.15CuO4", "Nd2-xCexCuO4", "RuSr2(YCe2)Cu2O12.25",
    "Ba(Fe0.92Co0.08)2As2", "Ca10(Ir4As8)(Fe2As2)5",
    "CaLuH12", "H3S", "LaH10", "Li2MgH16",
    "Rb3C60", "K3C60",
    "(TMTSF)2ClO4", "κ-(BEDT-TTF)2Cu[N(CN)2]Br",
    "Sr2RuO4", "UPt3", "CeCoIn5", "LiFeAs", "FeTe0.5Se0.5",
    "La3Ni2O7",
]

# Strings that MUST be rejected, with the expected reason constant.
MUST_REJECT = [
    # --- Round 4: concatenated descriptors (boundary blacklist missed)
    ("TaNSmonolayer", V.DESCRIPTIVE_WORD),
    ("Y-dopedBi2Sr2CaCu2O8", V.DESCRIPTIVE_WORD),
    ("NbSe2monolayer", V.DESCRIPTIVE_WORD),
    ("MoS2heterostructure", V.DESCRIPTIVE_WORD),
    ("WTe2bilayer", V.DESCRIPTIVE_WORD),
    ("FeSeSrTiO3substrate", V.DESCRIPTIVE_WORD),
    ("Bi2Se3thinfilm", V.DESCRIPTIVE_WORD),
    # --- pre-existing rules (regression guard for the rest)
    ("High-Tccuprates", V.GENERIC_FAMILY_NAME),
    # _CONCAT_DESCRIPTOR ("bilayer"/"graphene", "nanotubes") now catches
    # these before the generic long-lowercase rule — more specific tag.
    ("Bernalbilayergraphene", V.DESCRIPTIVE_WORD),
    ("Single-walledcarbonnanotubes", V.DESCRIPTIVE_WORD),
    ("Sr-Ru-O", V.SYSTEM_DESIGNATOR),
    ("Oxygen", V.DESCRIPTIVE_WORD),
    ("cuprates", V.GENERIC_FAMILY_NAME),
    ("H", V.SINGLE_ELEMENT),
    ("None", V.LITERAL_PLACEHOLDER),
    ("YBa2Cu3O7-", V.INCOMPLETE_FORMULA),
]


@pytest.mark.parametrize("formula", MUST_PASS)
def test_valid_formulas_pass(formula):
    ok, reason = V.validate_formula(V.normalize_whitespace(formula))
    assert ok, f"{formula!r} wrongly rejected: {reason}"


@pytest.mark.parametrize("formula,reason", MUST_REJECT)
def test_garbage_rejected(formula, reason):
    ok, got = V.validate_formula(V.normalize_whitespace(formula))
    assert not ok, f"{formula!r} wrongly accepted"
    assert got == reason, f"{formula!r}: expected {reason}, got {got}"


def test_concat_descriptor_does_not_touch_clean_formulas():
    # The substring rule must never fire on a real formula.
    for f in MUST_PASS:
        assert not V._CONCAT_DESCRIPTOR.search(V.normalize_whitespace(f)), (
            f"_CONCAT_DESCRIPTOR false-positive on {f!r}"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
