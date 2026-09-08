"""Deterministic, dependency-free composition enrichment for SCLib formulas.

The material aggregator intentionally uses a permissive grouping key.  That is
useful for search, but it is not a safe ML composition: variable stoichiometry,
alloy systems and interfaces must not be silently coerced into one exact
formula.  This module is the stricter boundary used by the Phase-1 ML export.

``enrich_formula`` first classifies an input as one of:

``exact``
    A fixed composition that the lightweight parser can fully account for.
``variable``
    A formula containing a stoichiometric variable such as ``x`` or ``delta``.
``interface``
    Two formula-like components separated by an interface slash.
``mixture``
    An alloy/system designator or an unresolved alternative site.
``invalid``
    Empty, descriptive, syntactically broken, or otherwise unparseable input.

Only ``exact`` inputs receive numeric composition descriptors.  The returned
mapping is JSON-compatible, key-stable, and contains parser provenance so a
frozen ML snapshot can be regenerated exactly.  There is deliberately no
fallback that drops punctuation and retries: doing that would turn ``Ag-Au``
into the fictitious stoichiometric compound ``AgAu``.

The parser handles ordinary element tokens, decimal amounts, parentheses,
square brackets, and middle-dot hydrate/adduct segments.  Audited cuprate
shorthands are recorded with a canonical-formula candidate but remain
``invalid`` until entity resolution confirms the intended composition.  Other
chemical acronyms (for example ``BEDT-TTF``) likewise remain ``invalid``.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from functools import reduce
from typing import Any, Literal

from services._composition import formula_validator

CompositionStatus = Literal["exact", "variable", "interface", "mixture", "invalid"]

PARSER_NAME = "sclib_formula_enrichment"
PARSER_VERSION = "1.1.0"

# Phase 1 recognizes isotope notation but deliberately does not emit exact
# isotope compositions: occupancy and isotope masses need a reviewed grammar
# and table. This guard runs BEFORE Unicode/LaTeX normalization. Unsupported
# superscripts may also be charge notation; those must not become atom counts.
_ISOTOPE_SUPERSCRIPT = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+")
_ISOTOPE_LATEX = re.compile(r"\^\s*(?:\{[^{}]*\}|[-+]?\d+)")
_ISOTOPE_PREFIX = re.compile(r"^\s*\[?\d+\s*[A-Z][a-z]?")
_ISOTOPE_BRACKET = re.compile(r"\[\s*\d+\s*[A-Z][a-z]?\s*\]")
_HYDROGEN_ISOTOPE = re.compile(r"[DT](?![a-z])")


def isotope_notation(raw: Any) -> dict[str, Any] | None:
    """Recognize isotope/charge syntax without erasing or interpreting it.

    Supported recognition: Unicode mass superscripts, LaTeX superscripts,
    bracket/prefix mass labels and D/T aliases. Ambiguous ASCII interior mass
    labels cannot be inferred retrospectively; callers must preserve raw text.
    """
    if not isinstance(raw, str):
        return None
    mentions = []
    for pattern, kind in (
        (_ISOTOPE_SUPERSCRIPT, "superscript_isotope_or_charge"),
        (_ISOTOPE_LATEX, "latex_isotope_or_charge"),
        (_ISOTOPE_PREFIX, "leading_mass_or_multiplier"),
        (_ISOTOPE_BRACKET, "bracket_mass_label"),
        (_HYDROGEN_ISOTOPE, "hydrogen_isotope_alias"),
    ):
        for match in pattern.finditer(raw):
            mentions.append(
                {"text": match.group(), "start": match.start(), "end": match.end(), "kind": kind}
            )
    return {"status": "requires_resolution", "mentions": mentions} if mentions else None


def composition_cache_is_current(raw: str, cached: Any) -> bool:
    """Fail closed for stale or tampered composition descriptors.

    Version checking alone cannot certify a cache's values. Recompute this
    cheap parser and compare the entire payload before reusing exact features.
    """
    if not isinstance(cached, dict):
        return False
    expected = enrich_formula(raw)
    candidate = dict(cached)
    # Database composition_data stores status in an adjacent column.
    if "composition_status" not in candidate:
        expected.pop("composition_status")
    return candidate == expected


def enrich_material_composition(material: Mapping[str, Any]) -> dict[str, Any]:
    """Do not certify a normalized catalog formula over raw isotope evidence.

    Catalog aliases may group records but cannot establish scientific identity.
    The offline planner and independent parity validator share this guard. It
    does not attempt to reconstruct isotope notation already lost everywhere.
    """
    formula = (
        material.get("formula_raw")
        or material.get("formula")
        or material.get("formula_normalized")
        or ""
    )
    result = enrich_formula(str(formula))
    records = material.get("records") or []
    if isinstance(records, str):
        try:
            import json

            records = json.loads(records)
        except (TypeError, ValueError):
            return _invalid(_empty_result(formula), "unreadable_source_records")
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, Mapping):
            continue
        extraction = record.get("raw_extraction")
        extraction = extraction if isinstance(extraction, Mapping) else {}
        original = (
            record.get("formula_raw")
            or extraction.get("formula_raw")
            or extraction.get("formula")
            or record.get("formula")
        )
        if isotope_notation(original):
            guarded = enrich_formula(original)
            guarded["catalog_formula"] = str(formula)
            guarded["errors"] = ["source_isotope_identity_requires_resolution"]
            return guarded
    return result


# ``CuSO4.5H2O`` is commonly an ASCII rendering of ``CuSO4·5H2O``, but it
# is also syntactically compatible with a fractional oxygen stoichiometry.
# Silently choosing either interpretation would create a false exact
# composition.  The unambiguous middle-dot form remains supported.
_AMBIGUOUS_ASCII_HYDRATE = re.compile(r"\d+\.\d+H2O(?:$|[+·])", re.IGNORECASE)
_TC_QUANTITY_NOTATION = re.compile(
    r"^\s*\$?\s*T\s*(?:_\s*\{?\s*c\s*\}?|ᶜ)\s*\$?\s*$",
    re.IGNORECASE,
)

# These strings are material-family shorthands, not parseable chemical
# formulas.  Several happen to consist entirely of valid element symbols
# (YBCO -> Y/B/C/O, Bi2212 -> Bi), so letting the token parser see them would
# manufacture exact ML compositions.  This list is intentionally maintained
# separately from the permissive NIMS grouping aliases: a grouping key may
# collapse a family for search, whereas an ML composition must fail closed
# until the particular stoichiometry/doping state has been resolved.
_AUDITED_FORMULA_SHORTHANDS: dict[str, str | None] = {
    "YBCO": "YBa2Cu3O7-delta",
    "Y-123": "YBa2Cu3O7-delta",
    "Y123": "YBa2Cu3O7-delta",
    "Y-124": "YBa2Cu4O8",
    "Y124": "YBa2Cu4O8",
    "BSCCO": "Bi2Sr2CaCu2O8+delta",
    "Bi2212": "Bi2Sr2CaCu2O8+delta",
    "Bi-2212": "Bi2Sr2CaCu2O8+delta",
    "Bi2201": "Bi2Sr2CuO6+delta",
    "Bi-2201": "Bi2Sr2CuO6+delta",
    "Bi2223": "Bi2Sr2Ca2Cu3O10+delta",
    "Bi-2223": "Bi2Sr2Ca2Cu3O10+delta",
    "LSCO": "La2-xSrxCuO4",
    "LBCO": "La2-xBaxCuO4",
    "NCCO": "Nd2-xCexCuO4",
    "PCCO": "Pr2-xCexCuO4",
    "PCCCO": "Pr2-xCexCuO4",
    "LCO": "La2CuO4",
    "La214": None,
    "Hg-1201": "HgBa2CuO4+delta",
    "Hg1201": "HgBa2CuO4+delta",
    "Hg-1212": "HgBa2CaCu2O6+delta",
    "Hg1212": "HgBa2CaCu2O6+delta",
    "Hg-1223": "HgBa2Ca2Cu3O8+delta",
    "Hg1223": "HgBa2Ca2Cu3O8+delta",
    "Tl-2201": "Tl2Ba2CuO6+delta",
    "Tl2201": "Tl2Ba2CuO6+delta",
    "Tl-2212": "Tl2Ba2CaCu2O8+delta",
    "Tl2212": "Tl2Ba2CaCu2O8+delta",
    "Tl-2223": "Tl2Ba2Ca2Cu3O10+delta",
    "Tl2223": "Tl2Ba2Ca2Cu3O10+delta",
    # Syntactically element-like family or claim abbreviations from the
    # ingestion semantic blacklist.  No unique composition is asserted.
    "HBCO": None,
    "CSH": None,
}
_AUDITED_FORMULA_SHORTHANDS_CASEFOLD = {
    key.casefold(): candidate for key, candidate in _AUDITED_FORMULA_SHORTHANDS.items()
}


# Standard atomic weights (or the conventional mass number for elements with
# no standard atomic weight).  Keeping this small table local avoids pulling
# pymatgen's scientific dependency tree into the ingestion container merely to
# validate formulas.  Values are only used after a formula is fully parsed.
_ATOMIC_MASS: dict[str, Decimal] = {
    "Ac": Decimal(227),
    "Ag": Decimal("107.8682"),
    "Al": Decimal("26.9815385"),
    "Am": Decimal(243),
    "Ar": Decimal("39.948"),
    "As": Decimal("74.921595"),
    "At": Decimal(210),
    "Au": Decimal("196.966569"),
    "B": Decimal("10.81"),
    "Ba": Decimal("137.327"),
    "Be": Decimal("9.0121831"),
    "Bh": Decimal(270),
    "Bi": Decimal("208.98040"),
    "Bk": Decimal(247),
    "Br": Decimal("79.904"),
    "C": Decimal("12.011"),
    "Ca": Decimal("40.078"),
    "Cd": Decimal("112.414"),
    "Ce": Decimal("140.116"),
    "Cf": Decimal(251),
    "Cl": Decimal("35.45"),
    "Cm": Decimal(247),
    "Cn": Decimal(285),
    "Co": Decimal("58.933194"),
    "Cr": Decimal("51.9961"),
    "Cs": Decimal("132.90545196"),
    "Cu": Decimal("63.546"),
    "Db": Decimal(268),
    "Ds": Decimal(281),
    "Dy": Decimal("162.500"),
    "Er": Decimal("167.259"),
    "Es": Decimal(252),
    "Eu": Decimal("151.964"),
    "F": Decimal("18.998403163"),
    "Fe": Decimal("55.845"),
    "Fl": Decimal(289),
    "Fm": Decimal(257),
    "Fr": Decimal(223),
    "Ga": Decimal("69.723"),
    "Gd": Decimal("157.25"),
    "Ge": Decimal("72.630"),
    "H": Decimal("1.008"),
    "He": Decimal("4.002602"),
    "Hf": Decimal("178.49"),
    "Hg": Decimal("200.592"),
    "Ho": Decimal("164.93033"),
    "Hs": Decimal(269),
    "I": Decimal("126.90447"),
    "In": Decimal("114.818"),
    "Ir": Decimal("192.217"),
    "K": Decimal("39.0983"),
    "Kr": Decimal("83.798"),
    "La": Decimal("138.90547"),
    "Li": Decimal("6.94"),
    "Lr": Decimal(266),
    "Lu": Decimal("174.9668"),
    "Lv": Decimal(293),
    "Mc": Decimal(290),
    "Md": Decimal(258),
    "Mg": Decimal("24.305"),
    "Mn": Decimal("54.938044"),
    "Mo": Decimal("95.95"),
    "Mt": Decimal(278),
    "N": Decimal("14.007"),
    "Na": Decimal("22.98976928"),
    "Nb": Decimal("92.90637"),
    "Nd": Decimal("144.242"),
    "Ne": Decimal("20.1797"),
    "Nh": Decimal(286),
    "Ni": Decimal("58.6934"),
    "No": Decimal(259),
    "Np": Decimal(237),
    "O": Decimal("15.999"),
    "Og": Decimal(294),
    "Os": Decimal("190.23"),
    "P": Decimal("30.973761998"),
    "Pa": Decimal("231.03588"),
    "Pb": Decimal("207.2"),
    "Pd": Decimal("106.42"),
    "Pm": Decimal(145),
    "Po": Decimal(209),
    "Pr": Decimal("140.90766"),
    "Pt": Decimal("195.084"),
    "Pu": Decimal(244),
    "Ra": Decimal(226),
    "Rb": Decimal("85.4678"),
    "Re": Decimal("186.207"),
    "Rf": Decimal(267),
    "Rg": Decimal(282),
    "Rh": Decimal("102.90550"),
    "Rn": Decimal(222),
    "Ru": Decimal("101.07"),
    "S": Decimal("32.06"),
    "Sb": Decimal("121.760"),
    "Sc": Decimal("44.955908"),
    "Se": Decimal("78.971"),
    "Sg": Decimal(269),
    "Si": Decimal("28.085"),
    "Sm": Decimal("150.36"),
    "Sn": Decimal("118.710"),
    "Sr": Decimal("87.62"),
    "Ta": Decimal("180.94788"),
    "Tb": Decimal("158.92535"),
    "Tc": Decimal(98),
    "Te": Decimal("127.60"),
    "Th": Decimal("232.0377"),
    "Ti": Decimal("47.867"),
    "Tl": Decimal("204.38"),
    "Tm": Decimal("168.93422"),
    "Ts": Decimal(294),
    "U": Decimal("238.02891"),
    "V": Decimal("50.9415"),
    "W": Decimal("183.84"),
    "Xe": Decimal("131.293"),
    "Y": Decimal("88.90584"),
    "Yb": Decimal("173.045"),
    "Zn": Decimal("65.38"),
    "Zr": Decimal("91.224"),
}

_ELEMENTS = frozenset(_ATOMIC_MASS)
_NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)")
_LATEX_BRACED_SCRIPT = re.compile(r"_\{([^{}]*)\}")
_LATEX_PLAIN_SUBSCRIPT = re.compile(r"_(\d+(?:\.\d+)?)")
_VARIABLE_WORD = re.compile(r"delta", re.IGNORECASE)
_VARIABLE_DELTA_D = re.compile(r"[+\-±]d(?=$|[A-Z(\[])")
_VARIABLE_AFTER_OPERATOR = re.compile(r"(?:^|[+\-±(,])\s*([xyz])(?=$|[^a-z])", re.IGNORECASE)
_VARIABLE_AFTER_ELEMENT = re.compile(r"[A-Z][a-z]?([xyz])(?=$|[A-Z(\[+\-])")
_VARIABLE_SUFFIX = re.compile(r"\d([xyz])(?=$|[A-Z(\[+\-])", re.IGNORECASE)
_ELEMENT_SYSTEM = re.compile(r"^[A-Z][a-z]?(?:-[A-Z][a-z]?)+$")


class _FormulaParseError(ValueError):
    """Stable parser error carrying a machine-readable code."""

    def __init__(self, code: str, position: int | None = None) -> None:
        self.code = code
        self.position = position
        suffix = "" if position is None else f"@{position}"
        super().__init__(f"{code}{suffix}")


class _FormulaParser:
    """Small recursive-descent parser for fixed inorganic formulas."""

    def __init__(self, formula: str) -> None:
        self.formula = formula
        self.pos = 0
        self.order: list[str] = []

    def parse(self) -> tuple[dict[str, Decimal], list[str]]:
        counts = self._sequence(stop=None)
        if self.pos != len(self.formula):
            raise _FormulaParseError("trailing_input", self.pos)
        if not counts:
            raise _FormulaParseError("no_elements")
        return dict(counts), self.order

    def _sequence(self, stop: str | None) -> defaultdict[str, Decimal]:
        counts: defaultdict[str, Decimal] = defaultdict(Decimal)
        found_item = False

        while self.pos < len(self.formula):
            char = self.formula[self.pos]
            if stop and char == stop:
                break
            if char in ")]":
                raise _FormulaParseError("unmatched_closing_bracket", self.pos)

            if char in "([":
                opening = char
                closing = ")" if opening == "(" else "]"
                self.pos += 1
                inner = self._sequence(stop=closing)
                if self.pos >= len(self.formula) or self.formula[self.pos] != closing:
                    raise _FormulaParseError("unclosed_bracket", self.pos)
                if not inner:
                    raise _FormulaParseError("empty_group", self.pos)
                self.pos += 1
                multiplier = self._amount_or_one()
                for element, amount in inner.items():
                    counts[element] += amount * multiplier
                found_item = True
                continue

            if not char.isupper() or not char.isascii():
                raise _FormulaParseError("unexpected_character", self.pos)

            start = self.pos
            self.pos += 1
            if self.pos < len(self.formula) and self.formula[self.pos].islower():
                self.pos += 1
            element = self.formula[start : self.pos]
            if element not in _ELEMENTS:
                raise _FormulaParseError("unknown_element", start)
            if element not in self.order:
                self.order.append(element)
            counts[element] += self._amount_or_one()
            found_item = True

        if stop and not found_item:
            return defaultdict(Decimal)
        return counts

    def _amount_or_one(self) -> Decimal:
        match = _NUMBER.match(self.formula, self.pos)
        if match is None:
            return Decimal(1)
        token = match.group(0)
        self.pos = match.end()
        try:
            value = Decimal(token)
        except InvalidOperation as exc:  # defensive; regex already constrains the token
            raise _FormulaParseError("invalid_amount", match.start()) from exc
        if not value.is_finite() or value <= 0:
            raise _FormulaParseError("non_positive_amount", match.start())
        return value


def enrich_formula(raw: str) -> dict[str, Any]:
    """Classify and, only when exact, enrich one material formula.

    The function has no I/O and no mutable global state.  Repeating it with the
    same input therefore returns an equal mapping, suitable for idempotent DB
    upserts keyed by ``input_hash`` + ``parser_version``.
    """

    result = _empty_result(raw)
    if not isinstance(raw, str) or not raw.strip():
        return _invalid(result, "empty_formula")
    if _TC_QUANTITY_NOTATION.fullmatch(raw):
        return _invalid(result, "physical_quantity_not_formula")

    isotopes = isotope_notation(raw)
    if isotopes:
        result["isotope_notation"] = isotopes
        return _invalid(result, "isotope_or_charge_requires_resolution")

    formula = _clean_input(raw)
    if not formula:
        return _invalid(result, "empty_formula")
    if _AMBIGUOUS_ASCII_HYDRATE.search(formula):
        return _invalid(result, "ambiguous_ascii_hydrate_separator")
    is_shorthand, shorthand_candidate = _formula_shorthand_candidate(formula)
    if is_shorthand:
        result["input_alias"] = formula
        result["canonical_formula_candidate"] = shorthand_candidate
        return _invalid(result, "formula_shorthand_requires_resolution")

    # Recognize structured non-exact inputs before the legacy validator.  In
    # particular, Sr-Ru-O is intentionally invalid as a *compound* in that
    # validator, but is a valid composition-system record for this classifier.
    if _is_interface(formula):
        result["composition_status"] = "interface"
        return result
    if _is_mixture(formula):
        result["composition_status"] = "mixture"
        return result

    valid, reason = formula_validator.validate_formula(formula)
    if not valid:
        return _invalid(result, f"validator:{reason}")

    variables = _variable_symbols(formula)
    if variables:
        result["composition_status"] = "variable"
        result["variable_symbols"] = variables
        return result

    try:
        counts, order = _parse_formula(formula)
    except _FormulaParseError as exc:
        suffix = "" if exc.position is None else f"@{exc.position}"
        return _invalid(result, f"parse:{exc.code}{suffix}")

    reduced = _reduce_fixed_composition(counts)
    sorted_elements = sorted(reduced)
    total = sum(reduced.values(), Decimal(0))
    if total <= 0:  # should be unreachable, retained as an ML-export safety rail
        return _invalid(result, "parse:non_positive_total")

    result.update(
        {
            "composition_status": "exact",
            "formula_reduced": _formula_string(reduced, order),
            "formula_anonymous": _anonymous_formula(reduced),
            "chemical_system": "-".join(sorted_elements),
            "element_amounts": {
                element: _json_number(reduced[element]) for element in sorted_elements
            },
            "atomic_fractions": {
                element: float(reduced[element] / total) for element in sorted_elements
            },
            "n_elements": len(sorted_elements),
            "n_atoms_fu": _json_number(total),
            "molar_mass_g_mol": round(
                float(
                    sum(
                        (reduced[element] * _ATOMIC_MASS[element] for element in reduced),
                        Decimal(0),
                    )
                ),
                6,
            ),
        }
    )
    return result


def _empty_result(raw: Any) -> dict[str, Any]:
    return {
        "composition_status": "invalid",
        "formula_raw": raw if isinstance(raw, str) else None,
        "isotope_notation": None,
        "formula_reduced": None,
        "formula_anonymous": None,
        "chemical_system": None,
        "element_amounts": None,
        "atomic_fractions": None,
        "n_elements": None,
        "n_atoms_fu": None,
        "molar_mass_g_mol": None,
        "variable_symbols": [],
        "input_alias": None,
        "canonical_formula_candidate": None,
        "parser_name": PARSER_NAME,
        "parser_version": PARSER_VERSION,
        "input_hash": _hash_input(raw),
        "errors": [],
    }


def _invalid(result: dict[str, Any], error: str) -> dict[str, Any]:
    result["composition_status"] = "invalid"
    result["errors"] = [error]
    return result


def _hash_input(raw: Any) -> str:
    if isinstance(raw, str):
        payload = "str\0" + unicodedata.normalize("NFC", raw)
    else:
        payload = f"{type(raw).__qualname__}\0{raw!r}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _formula_shorthand_candidate(formula: str) -> tuple[bool, str | None]:
    """Resolve known display shorthands without conflating real formulas.

    Exact display forms and uniformly cased database-normalized variants are
    denied. Mixed-case strings retain chemical meaning: for example ``YbCo``
    is an ytterbium-cobalt formula and must not collide with ``YBCO`` merely
    because both case-fold to the same text.
    """
    if formula in _AUDITED_FORMULA_SHORTHANDS:
        return True, _AUDITED_FORMULA_SHORTHANDS[formula]
    if formula.islower() or formula.isupper():
        key = formula.casefold()
        if key in _AUDITED_FORMULA_SHORTHANDS_CASEFOLD:
            return True, _AUDITED_FORMULA_SHORTHANDS_CASEFOLD[key]
    return False, None


def _clean_input(raw: str) -> str:
    # NFKC converts Unicode sub/superscript digits to their ASCII forms.
    formula = unicodedata.normalize("NFKC", raw).strip()
    formula = formula.replace("−", "-").replace("⋅", "·")
    formula = formula.replace("$", "")
    formula = _LATEX_BRACED_SCRIPT.sub(r"\1", formula)
    formula = _LATEX_PLAIN_SUBSCRIPT.sub(r"\1", formula)
    formula = formula.replace("{", "").replace("}", "")
    return re.sub(r"\s+", "", formula)


def _top_level_separators(formula: str, separators: frozenset[str]) -> list[int]:
    positions: list[int] = []
    depth = 0
    pairs = {"(": ")", "[": "]"}
    closing = frozenset(pairs.values())
    for index, char in enumerate(formula):
        if char in pairs:
            depth += 1
        elif char in closing:
            depth = max(0, depth - 1)
        elif depth == 0 and char in separators:
            positions.append(index)
    return positions


def _is_interface(formula: str) -> bool:
    slash_positions = _top_level_separators(formula, frozenset({"/"}))
    if len(slash_positions) != 1:
        return False
    index = slash_positions[0]
    left, right = formula[:index], formula[index + 1 :]
    # Guard against fractional stoichiometry such as Li5/6BC.
    return (
        len(left) >= 2
        and len(right) >= 2
        and left[0].isalpha()
        and right[0].isalpha()
        and any(char.isupper() for char in left)
        and any(char.isupper() for char in right)
    )


def _is_mixture(formula: str) -> bool:
    # Alternative occupancy, e.g. (La,Sc)H12, cannot determine either
    # element's atomic fraction without a sample-specific mixing ratio.
    if "," in formula:
        return True
    # Binary/ternary system and unspecified-alloy notation, e.g. Ag-Au.
    return bool(_ELEMENT_SYSTEM.fullmatch(formula))


def _variable_symbols(formula: str) -> list[str]:
    symbols: set[str] = set()
    if (
        "δ" in formula
        or "Δ" in formula
        or _VARIABLE_WORD.search(formula)
        or _VARIABLE_DELTA_D.search(formula)
    ):
        symbols.add("delta")
    symbols.update(match.group(1).lower() for match in _VARIABLE_AFTER_OPERATOR.finditer(formula))
    # Regex backtracking must not reinterpret the valid element Dy as D+y.
    symbols.update(
        match.group(1).lower()
        for match in _VARIABLE_AFTER_ELEMENT.finditer(formula)
        if match.group(0) not in _ELEMENTS
    )
    symbols.update(match.group(1).lower() for match in _VARIABLE_SUFFIX.finditer(formula))
    return sorted(symbols)


def _parse_formula(formula: str) -> tuple[dict[str, Decimal], list[str]]:
    total: defaultdict[str, Decimal] = defaultdict(Decimal)
    order: list[str] = []
    segments = formula.split("·")
    if any(not segment for segment in segments):
        raise _FormulaParseError("empty_adduct_segment")

    for segment_index, segment in enumerate(segments):
        coefficient = Decimal(1)
        if segment_index > 0:
            match = _NUMBER.match(segment)
            if match:
                coefficient = Decimal(match.group(0))
                segment = segment[match.end() :]
                if not segment or coefficient <= 0:
                    raise _FormulaParseError("invalid_adduct_multiplier")
        parser = _FormulaParser(segment)
        counts, segment_order = parser.parse()
        for element, amount in counts.items():
            total[element] += coefficient * amount
        for element in segment_order:
            if element not in order:
                order.append(element)
    return dict(total), order


def _reduce_fixed_composition(counts: dict[str, Decimal]) -> dict[str, Decimal]:
    # Integer formula units have an unambiguous greatest common divisor.
    # Fractional site occupancies are preserved verbatim: expanding
    # La1.85Sr0.15CuO4 to La37Sr3Cu20O80 is mathematically reducible but much
    # less useful to materials researchers and changes the formula-unit scale.
    if not all(amount == amount.to_integral_value() for amount in counts.values()):
        return dict(counts)
    integers = [int(amount) for amount in counts.values()]
    divisor = reduce(math.gcd, integers)
    return {element: amount / divisor for element, amount in counts.items()}


def _formula_string(counts: dict[str, Decimal], original_order: list[str]) -> str:
    return "".join(
        element + ("" if counts[element] == 1 else _format_decimal(counts[element]))
        for element in original_order
        if element in counts
    )


def _anonymous_formula(counts: dict[str, Decimal]) -> str:
    # Sorting by amount makes the representation independent of element
    # identity while the symbol tie-breaker makes equal occupancies stable.
    ordered = sorted(counts.items(), key=lambda item: (item[1], item[0]))
    return "".join(
        _anonymous_symbol(index) + ("" if amount == 1 else _format_decimal(amount))
        for index, (_element, amount) in enumerate(ordered)
    )


def _anonymous_symbol(index: int) -> str:
    # Excel-style sequence: A..Z, AA..AZ, BA... (26 elements is already
    # beyond plausible exact compounds, but this keeps the helper total).
    value = index + 1
    chars: list[str] = []
    while value:
        value, remainder = divmod(value - 1, 26)
        chars.append(chr(ord("A") + remainder))
    return "".join(reversed(chars))


def _format_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


__all__ = [
    "PARSER_NAME",
    "PARSER_VERSION",
    "CompositionStatus",
    "composition_cache_is_current",
    "enrich_formula",
    "enrich_material_composition",
    "isotope_notation",
]
