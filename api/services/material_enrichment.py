"""Source-scoped, reproducible candidate extraction for materials enrichment.

This module reads no database and makes no network requests. A local literal
match is a retrieval/extraction observation, never a reviewed material-state
association or scientific acceptance. In particular it does not turn absent
pressure into ambient pressure, merge samples, overwrite retained records, or
require a CIF before retaining a source-backed text structure candidate.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from decimal import Decimal
from itertools import islice
from typing import Any

from services.claim_support import is_derived_source_hint
from services.property_evidence import legacy_result_id
from services.result_semantics import classify_result
from services.scientific_values import FIELD_UNITS, parse_scientific_value, record_quantity

VERSION = "materials-enrichment/1.0.0"
EXTRACTOR_VERSION = "materials-literal-extractor/1.1.1"
MAX_MATERIALS = 1000
MAX_SOURCES = 10000
MAX_SOURCE_CHARS = 200000
MAX_CANDIDATES = 20000
RECORD_COVERAGE_VERSION = "materials-record-field-coverage/1.0.0"
MAX_RECORD_COVERAGE_RECORDS = 32
MAX_RECORD_COVERAGE_TOTAL = 1_000_000
AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False,
             "public_release": False, "database_changed": False}
SOURCE_KINDS = {"original_passage", "abstract", "table", "fulltext", "legacy_unknown"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_VALUE = rf"(?:[<>≤≥~≈]|about\s+|approximately\s+)?\s*{_NUMBER}(?:\s*(?:±|\+/-|to|–|—)\s*{_NUMBER})?"
_TEMPERATURE = re.compile(rf"(?<![\w.])({_VALUE})\s*(mK|K|kelvin)\b")
_PRESSURE = re.compile(rf"(?<![\w.])({_VALUE})\s*(GPa|MPa|kPa|kbar|bar|Pa|atm)\b")
_TC = re.compile(r"T\s*[_{}]*\s*c\b|\bcritical temperature\b|\bsuperconducting transition\b", re.I)
_CRITERIA = {
    "onset": re.compile(r"\bonsets?\b", re.I),
    "zero_resistance": re.compile(r"\bzero[ -]resistance\b", re.I),
    "midpoint": re.compile(r"\bmidpoint\b|\b50\s*%", re.I),
    "diamagnetic": re.compile(r"\bdiamagnetic (?:onset|transition)\b", re.I),
    "heat_capacity": re.compile(r"\bheat.capacity (?:anomaly|transition)\b", re.I),
}
_MEASUREMENT_METHODS = {
    "resistivity": re.compile(r"\bresistiv\w*\b|\bresistance\b|four[ -]probe", re.I),
    "susceptibility": re.compile(r"\bsusceptibility\b", re.I),
    "specific_heat": re.compile(r"\b(?:specific heat|heat capacity)\b", re.I),
    "x_ray_diffraction": re.compile(r"\bx.ray.diffraction\b|\bXRD\b", re.I),
}
_TC_CALCULATION_METHODS = {
    "eliashberg": re.compile(r"\b(?:isotropic[ -])?(?:Migdal[ -])?Eliashberg\b", re.I),
    "allen_dynes": re.compile(r"\bAllen[ -]Dynes\b", re.I),
}
_CALCULATION_HINTS = {**_TC_CALCULATION_METHODS,
    "dft": re.compile(r"\bDFT\b|\bdensity.functional\b|\bfirst.principles\b", re.I)}
_COMPUTED = re.compile(r"\b(?:calculated|computed|predicted|theoretical|DFT|DFPT|Eliashberg|Allen[ -]Dynes)\b", re.I)
_OBSERVED = re.compile(r"\b(?:measured|observed|experimental|resistivity|resistance|susceptibility|specific heat)\b", re.I)
_CAUTION = re.compile(r"\b(?:previous|earlier|prior|cited|according to|reported by|et al|not detected|no superconduct|not superconduct|hypothetical|possibly)\b|\[\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]", re.I)
_DIRECTIVE = re.compile(r"ignore.{0,20}(?:instruction|rule)|(?:system|developer|assistant)\s*:|you must|必须回答|忽略.{0,12}(?:指令|规则)", re.I)
_FORMULA = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][a-z]?(?:\s*\d+(?:\.\d+)?(?:\(\d+\))?)?)(?:\s*[A-Z][a-z]?(?:\s*\d+(?:\.\d+)?(?:\(\d+\))?)?)+(?![A-Za-z0-9])")
_ELEMENTS = frozenset("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split())
_SG_TOKEN = r"[PIFRABC][0-9mncabde/\-]{1,18}"
_SG = re.compile(rf"\b(?:space[ -]group|spacegroup)\s*(?:is|of|:|=)?\s*({_SG_TOKEN})\b", re.I)
_SG_PREFIX = re.compile(rf"\b({_SG_TOKEN})\s+(?:space[ -]group|structure|phase)\b")
_LATTICE = re.compile(rf"(?<!\w)([abc]|alpha|beta|gamma)\s*(?:\((angstrom|Å|nm|pm|degree|deg|°)\))?\s*=\s*({_NUMBER}(?:\(\d+\)|\s*±\s*{_NUMBER})?)\s*(angstrom|Å|nm|pm|degree|deg|°)?\b", re.I)
_NUMERIC_LABELS = {
    "lambda_eph": r"(?:electron.phonon coupling(?: constant)?|lambda_eph|λ)",
    "omega_log_source_value": r"(?:omega_log|ωlog|ω_log|logarithmic(?: average)? phonon frequency)",
    "mu_star": r"(?:mu_star|μ\*|Coulomb pseudopotential)",
    "hc2_tesla": r"(?:Hc2|H_c2|upper critical field)",
    "lambda_london_nm": r"(?:London penetration depth|penetration depth)",
    "xi_gl_nm": r"(?:coherence length)",
}
# Routes are suggestions. An external chemical formula match is not a state match.
FIELD_ROUTES = {
    "tc_kelvin": ["source_fulltext_and_supplement", "supercon_source_lookup", "new_calculation_or_experiment"],
    "pressure_gpa": ["source_fulltext_and_supplement"],
    "tc_criterion": ["source_fulltext_and_supplement", "supercon_source_lookup"],
    "measurement_method": ["source_fulltext_and_supplement", "supercon_source_lookup"],
    "calculation_method": ["source_fulltext_and_supplement", "nomad_state_matched_calculation"],
    "sample_form": ["source_fulltext_and_supplement", "supercon_source_lookup"],
    "space_group": ["source_fulltext_and_supplement", "cod_structure_lookup", "mp_state_matched_structure", "new_structure_calculation"],
    "crystal_structure": ["source_fulltext_and_supplement", "cod_structure_lookup", "mp_state_matched_structure"],
    "lattice_a": ["source_table_and_supplement", "cod_structure_lookup", "mp_state_matched_structure", "new_structure_calculation"],
    "lattice_b": ["source_table_and_supplement", "cod_structure_lookup", "mp_state_matched_structure", "new_structure_calculation"],
    "lattice_c": ["source_table_and_supplement", "cod_structure_lookup", "mp_state_matched_structure", "new_structure_calculation"],
    "measurement_temperature_k": ["source_table_and_supplement"],
    "atomic_sites": ["source_table_and_supplement", "cod_structure_lookup", "mp_state_matched_structure", "new_structure_calculation"],
    "site_occupancies": ["source_table_and_supplement", "new_composition_characterization"],
    "composition_identity": ["source_fulltext_and_supplement", "new_composition_characterization"],
    "pairing_symmetry": ["source_fulltext_and_supplement", "specialist_mechanism_study"],
    "is_unconventional": ["source_fulltext_and_supplement", "specialist_mechanism_study"],
    "gap_structure": ["source_fulltext_and_supplement", "specialist_mechanism_study"],
    "reported_order": ["source_fulltext_and_supplement", "specialist_experiment"],
    "competing_order": ["source_fulltext_and_supplement", "specialist_experiment"],
    "lambda_eph": ["source_fulltext_and_supplement", "nomad_state_matched_calculation", "new_electron_phonon_calculation"],
    "omega_log_source_value": ["source_fulltext_and_supplement", "nomad_state_matched_calculation", "new_electron_phonon_calculation"],
    "mu_star": ["source_fulltext_and_supplement", "new_calculation_declared_assumption"],
    "hc2_tesla": ["source_fulltext_and_supplement", "supercon_source_lookup", "new_experiment_or_model_estimate"],
    "lambda_london_nm": ["source_fulltext_and_supplement", "supercon_source_lookup", "new_experiment_or_model_estimate"],
    "xi_gl_nm": ["source_fulltext_and_supplement", "supercon_source_lookup", "new_experiment_or_model_estimate"],
}
# Historical grouping names remain compatible with offline callers. These
# fields now have bounded paper grammars; a reference route is still not a hit.
REFERENCE_ONLY_FIELDS = frozenset({
    "hc1_source_value", "gap_energy_source_value", "gap_ratio_source_value",
    "electronic_specific_heat_coefficient_source_value", "debye_temperature_source_value",
    "isotope_effect_exponent", "dtc_dp_source_value", "maximum_applied_pressure_source_value",
    "meissner_fraction_percent", "transition_width_source_value", "minimum_temperature_k",
})
for _field in REFERENCE_ONLY_FIELDS:
    FIELD_ROUTES[_field] = ["source_fulltext_and_supplement", "supercon_source_lookup"]
for _field in ("space_group", "crystal_structure", "lattice_a", "lattice_b", "lattice_c"):
    FIELD_ROUTES[_field] = [*FIELD_ROUTES[_field], "supercon_source_lookup"]
PAPER_UNIMPLEMENTED_FIELDS = frozenset({"t_cdw_k", "t_afm_k", "t_sdw_k"})
for _field in PAPER_UNIMPLEMENTED_FIELDS:
    FIELD_ROUTES[_field] = ["source_fulltext_and_supplement", "specialist_experiment"]
SPECIALIST_EXTRACTION_FIELDS = frozenset({"pairing_symmetry", "is_unconventional", "reported_order", "competing_order", "gap_structure"})
LITERAL_SOURCE_FIELDS = REFERENCE_ONLY_FIELDS | PAPER_UNIMPLEMENTED_FIELDS

# These are source values, deliberately outside the canonical scientific-value
# registry. Never infer a unit, convert a value, or interpret printed uncertainty.
_SOURCE_POINT = r"[-+−]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?:\(\d+\))?"
_SOURCE_AMOUNT = rf"(?:(?:<=|>=|[<>≤≥~≈]|below|above|at most|at least|around|about|approximately|up to|as high as|reaches|reached)\s*)?{_SOURCE_POINT}(?:\s*(?:±|\+/-|to|–|—|-)\s*{_SOURCE_POINT})?"
_SOURCE_LINK = r"\s*(?:(?:=|:)|(?:is|was|of|at))?\s*"
_HEAT_UNIT = r"(?:mJ|[µμ]J|uJ|J)(?:[/·⋅*\s(]{0,6}(?:mol(?:[ -]at\.)?|K)(?:\s*\^?\s*[-−]?\d{1,2})?[)]?){1,3}"
_SOURCE_FIELD_SPECS = {
    "hc1_source_value": (r"(?:[µμ]0\s*)?(?:H\s*c\s*1(?:\(0\))?|lower critical field)", r"(?:mT|T|kOe|Oe|gauss|G)", "reported_property"),
    "gap_energy_source_value": (r"(?:superconducting(?: energy)? gap|(?:energy gap|gap energy)|(?:Δ|\\Delta)(?:\(0\)|0)?)", r"(?:meV|[µμ]eV|ueV|eV|K)", "reported_property"),
    "gap_ratio_source_value": (r"(?:superconducting gap ratio|gap ratio|2\s*(?:Δ|\\Delta)(?:\(0\)|0)?\s*/\s*k\s*B\s*T\s*c)", None, "reported_property"),
    "electronic_specific_heat_coefficient_source_value": (r"(?:electronic specific[ -]heat coefficient|Sommerf(?:eld|ield) (?:coefficient|constant)|(?:γ|\\gamma|gamma)(?:\s*n)?)", _HEAT_UNIT, "reported_property"),
    "debye_temperature_source_value": (r"(?:Debye temperature|(?:[Θθ]|\\Theta|\\theta)\s*D)", r"(?:mK|K|kelvin)", "reported_property"),
    "isotope_effect_exponent": (r"(?:isotope(?:[ -]effect)? (?:exponent|coefficient)|α|\\alpha|alpha)", None, "reported_property"),
    "dtc_dp_source_value": (r"(?:d\s*T\s*c\s*/\s*d\s*P|pressure derivative of T\s*c)", r"(?:mK|K)\s*(?:/\s*(?:GPa|MPa|kbar|bar|Pa)|(?:GPa|MPa|kbar|bar|Pa)\s*\^?[-−]1)", "reported_property"),
    "maximum_applied_pressure_source_value": (r"(?:(?:maximum|highest)(?: applied)? pressure|pressures?\s+up to|(?:measurements?|experiments?)\s+(?:were\s+)?(?:performed|carried out)\s+up to)", r"(?:GPa|MPa|kPa|kbar|bar|Pa|atm)", "study_extent"),
    "meissner_fraction_percent": (r"(?:Meissner (?:fraction|volume fraction)|field[ -]cooled Meissner fraction)", r"(?:%|percent)", "reported_property"),
    "transition_width_source_value": (r"(?:(?:superconducting|resistive|resistance) transition width|superconducting width|transition width|(?:Δ|\\Delta)\s*T\s*c?)", r"(?:mK|K|kelvin)", "reported_property"),
    "minimum_temperature_k": (r"(?:(?:lowest|minimum)(?: measurement)? temperature|(?:measured|measurements|measurements were performed|resistivity|resistance|susceptibility|heat capacity)\s+down to)", r"(?:mK|K|kelvin)", "measurement_limit"),
    "t_cdw_k": (r"(?:T\s*CDW|(?:charge[ -]density[ -]wave|CDW)(?: ordering| transition)?(?: temperature)?)", r"(?:mK|K|kelvin)", "reported_order_transition"),
    "t_afm_k": (r"(?:T\s*N|N[ée]el temperature|(?:antiferromagnetic|AFM)(?: ordering| transition)(?: temperature)?)", r"(?:mK|K|kelvin)", "reported_order_transition"),
    "t_sdw_k": (r"(?:T\s*SDW|(?:spin[ -]density[ -]wave|SDW)(?: ordering| transition)?(?: temperature)?)", r"(?:mK|K|kelvin)", "reported_order_transition"),
}


def _source_field_pattern(field):
    cue, unit, _ = _SOURCE_FIELD_SPECS[field]
    # Unit-less quantities are admitted only for explicitly named ratios and
    # exponents. Other fields require the complete printed unit token.
    suffix = rf"[\s~]*(?P<unit>{unit})(?![A-Za-z0-9])" if unit else r"(?:\s*(?P<unit>dimensionless))?(?![\w(]|\.\d)(?!\s*(?:±|\+/-|to\b|–|—|-\s*\d|[×x]\s*10))"
    return re.compile(rf"(?<!\w)(?P<cue>{cue})(?![A-Za-z]){_SOURCE_LINK}(?P<amount>{_SOURCE_AMOUNT}){suffix}", re.I)


_SOURCE_FIELD_PATTERNS = {field: _source_field_pattern(field) for field in _SOURCE_FIELD_SPECS}
_SOURCE_UNIT_TAIL = re.compile(r"\s*(?:[/^·⋅*]|[-−]\s*\d|(?:K|mK|meV|[µμ]eV|eV|J|mJ|mol|T|mT|nm|Å|GPa|MPa|kPa|Pa|kbar|bar|atm|s|ms|[µμ]s|m|cm|mm|kg|g|Hz|kHz|MHz|GHz|N|W|A|V|C|H|F|S|Oe|kOe|G|gauss|percent|degrees?|deg|Ω)(?!\w)|%)")
_SOURCE_DIMENSIONLESS_END = re.compile(
    r"\s*(?:$|[.,;!?)]|(?:and|or|with|as|from|for|by|at|in|is|was|were|which|that|where|while|although|whereas|compared|consistent|rather|according)(?!\w))",
    re.I,
)
_SOURCE_ELEMENT_COMPARISON = re.compile(
    r"\b(?i:compared (?:with|to)|rather than|versus|vs\.?|whereas|and)\s+(?:"
    + "|".join(sorted(_ELEMENTS, key=lambda token: (-len(token), token)))
    + r")(?![A-Za-z0-9])(?!\s*[=:<>≤≥])")


def _source_field_matches(text):
    """Finite local source grammar; no normalization or scientific entailment."""
    for field, pattern in _SOURCE_FIELD_PATTERNS.items():
        for match in pattern.finditer(text):
            cue = match.group("cue")
            before = text[max(0, match.start()-80):match.start()]
            if re.search(r"\b(?:no|not|without|absence of|absent|undetected|not detected)\b[^.;]*$", before, re.I):
                continue
            if field == "gap_energy_source_value" and (re.search(r"\b(?:band|semiconductor|CDW|charge[ -]density[ -]wave) gap\b", text, re.I)
                    or not re.search(r"\b(?:superconduct|BCS|pairing|tunneling)\w*\b", text, re.I)
                    or not re.search(r"\b(?:gap|gap energy)\b", text, re.I)):
                continue
            if field == "gap_energy_source_value" and re.match(r"(?:Δ|\\Delta)", cue) and not re.search(r"\b(?:gap(?: energy| size)?|energy gap)\s*[,(:]?\s*$", before, re.I):
                continue
            if field == "isotope_effect_exponent" and not re.search(r"\bisotope(?:[ -]effect)? (?:exponent|coefficient)\b", text, re.I):
                continue
            if field == "isotope_effect_exponent" and re.fullmatch(r"(?:α|\\alpha|alpha)", cue, re.I) and not re.search(r"\bisotope(?:[ -]effect)? (?:exponent|coefficient)\s*[,(:]?\s*$", before, re.I):
                continue
            if field == "transition_width_source_value" and not re.search(r"\b(?:superconduct|resistiv|resistance)\w*\b|\bT\s*c\b", text, re.I):
                continue
            if field == "transition_width_source_value" and not re.search(r"\b(?:width|broadening)\b", text, re.I):
                continue
            if field == "transition_width_source_value" and re.match(r"(?:Δ|\\Delta)", cue) and not re.search(r"\b(?:transition width|transition broadening|superconducting width)\s*[,(:]?\s*$", before, re.I):
                continue
            if field in PAPER_UNIMPLEMENTED_FIELDS:
                # A lower measurement bound or an XRD temperature is never an
                # ordering temperature, even beside a named transition.
                if re.search(r"\b(?:down to|diffraction|XRD|measured at|measurement temperature|transition width)\b", text, re.I):
                    continue
                if field == "t_afm_k" and re.fullmatch(r"T\s*N", cue, re.I) and not re.search(r"\b(?:antiferromagnet|AFM|N[ée]el)\w*\b", text, re.I):
                    continue
            if field == "electronic_specific_heat_coefficient_source_value":
                unit = match.group("unit")
                if not re.search(r"mol", unit, re.I) or not re.search(r"K", unit):
                    continue
                if re.match(r"(?:γ|\\gamma|gamma)", cue, re.I) and not re.search(r"\b(?:electronic specific[ -]heat coefficient|Sommerf(?:eld|ield) (?:coefficient|constant))\s*[,(:]?\s*$", before, re.I):
                    continue
                compact_unit = re.sub(r"[\s^(){}·⋅*]", "", unit).replace("−", "-")
                if not re.fullmatch(r"(?:mJ|[µμ]J|uJ|J)(?:/(?:mol(?:-at\.)?)/?K2|(?:mol(?:-at\.)?)-1K-2|K-2(?:mol(?:-at\.)?)-1)", compact_unit):
                    continue
            if match.groupdict().get("unit") is not None and _SOURCE_UNIT_TAIL.match(text[match.end():]):
                continue
            # The finite unit list is not a complete scientific grammar. A
            # ratio/exponent needs a complete expression ending or a separated
            # prose connector, never an unknown unit or clipped scale factor.
            if field in {"gap_ratio_source_value", "isotope_effect_exponent"} and not _SOURCE_DIMENSIONLESS_END.match(text[match.end():]):
                continue
            yield field, match


def _extent_pressure(text, match):
    matched = any(found.start() <= match.start() and match.end() <= found.end()
                  for found in _SOURCE_FIELD_PATTERNS["maximum_applied_pressure_source_value"].finditer(text))
    # Recognizable apparatus/range extents are withheld from Tc conditions even
    # when their wording is outside the narrower applied-maximum grammar.
    before = text[max(0, match.start()-100):match.start()]
    other_extent = re.search(r"\b(?:pressure range\s+(?:extends(?: up)? to|reaches)|pressure\s+(?:was\s+)?(?:increased|raised|swept)(?:\s+up)?\s+to|(?:pressure cell|cell|instrument)\s+(?:capacity|limit|rated(?: to| for)?))\s*(?:is|of|=|:)?\s*$", before, re.I)
    return matched or other_extent is not None


class EnrichmentError(ValueError):
    """Static input failure; do not log source text or sensitive metadata."""


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise EnrichmentError("enrichment_json_invalid") from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bounded_source_rows(rows, limit=100, id_key="candidate_id"):
    """Select a reproducible source-fair response window without changing facts.

    Small inventories keep their existing sorted-ID order. For an overflowing
    inventory, papers take turns, as do each paper's captures and each capture's
    fields. This avoids one prolific source taking the entire response window.
    The selected rows retain their original IDs and payloads; callers must still
    disclose counts and omissions. A source group is not an independent study.
    """
    if type(limit) is not int or limit < 0:
        raise EnrichmentError("candidate_window_limit_invalid")
    # Review findings have no declared ID. A digest is only a deterministic
    # selection key and is never inserted into their source-owned payload.
    key = (lambda row: row[id_key]) if id_key is not None else digest
    ordered = sorted(rows, key=key)
    if len(ordered) <= limit:
        return ordered
    if limit == 0:
        return []

    def round_robin(streams):
        active = deque(iter(stream) for stream in streams)
        while active:
            stream = active.popleft()
            try:
                row = next(stream)
            except StopIteration:
                continue
            active.append(stream)
            yield row

    papers = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in ordered:
        source = row.get("source") or {}
        papers[source.get("paper_id") or ""][source.get("capture_id") or ""][row.get("field") or ""].append(row)
    paper_streams = []
    for paper in sorted(papers):
        capture_streams = []
        for capture in sorted(papers[paper]):
            fields = papers[paper][capture]
            capture_streams.append(round_robin([fields[field] for field in sorted(fields)]))
        paper_streams.append(round_robin(capture_streams))
    # Retain that selection order so a compact frontend prefix also represents
    # the other inspected papers. This order does not rank scientific evidence.
    return list(islice(round_robin(paper_streams), limit))


def _identifier(value: Any, limit: int = 200) -> bool:
    return type(value) is str and 0 < len(value) <= limit and value == value.strip() and not any(ord(c) < 32 for c in value)


def normalize_formula(value: str) -> str:
    """Formatting normalization only; no parent/sample or composition equivalence."""
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\\(?:mathrm|text|ce)\s*\{([^{}]*)\}", r"\1", value)
    return re.sub(r"[\s${}_]", "", value)


def _flat(text: str) -> tuple[str, list[int]]:
    """Keep offsets into captured source bytes' decoded text, despite TeX spacing."""
    chars, positions = [], []
    # Control words are omitted with their braces; actual formula/property text remains.
    skips = {i for match in re.finditer(r"\\(?:mathrm|text|ce|AA|rm|operatorname)\b", text)
             for i in range(*match.span())}
    for i, char in enumerate(text):
        if i in skips or char in "${}_":
            continue
        normalized = unicodedata.normalize("NFKC", char)
        if char in "\u00a0\u2009\u202f":
            normalized = " "
        for child in normalized:
            chars.append(child)
            positions.append(i)
    return "".join(chars), positions


def validate_source(source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise EnrichmentError("source_object_required")
    result = json.loads(canonical(dict(source)))
    required = ("id", "paper_id", "text", "content_sha256", "source_revision", "locator", "kind")
    if any(key not in result for key in required):
        raise EnrichmentError("source_capture_fields_required")
    if not _identifier(result["id"]) or not _identifier(result["paper_id"], 100):
        raise EnrichmentError("source_identity_invalid")
    text = result["text"]
    if type(text) is not str or not 0 < len(text) <= MAX_SOURCE_CHARS:
        raise EnrichmentError("source_text_limit")
    if not _SHA.fullmatch(str(result["content_sha256"])) or text_digest(text) != result["content_sha256"]:
        raise EnrichmentError("source_content_changed")
    if not _identifier(result["source_revision"]):
        raise EnrichmentError("source_revision_required")
    if result["kind"] not in SOURCE_KINDS:
        raise EnrichmentError("original_source_required_not_derived_fact")
    locator_section = result["locator"].get("section") if type(result["locator"]) is dict else None
    if is_derived_source_hint(section=result.get("section") or locator_section, paper_id=result["paper_id"], text=text):
        raise EnrichmentError("generated_source_not_original_evidence")
    if type(result["locator"]) is not dict or not result["locator"] or len(canonical(result["locator"])) > 4096:
        raise EnrichmentError("source_locator_required")
    allowed = {"page", "table", "figure", "section", "row", "column", "chunk_id", "char_start", "char_end", "xml_xpath"}
    if set(result["locator"]) - allowed or any(type(v) not in {str, int} or type(v) is str and not _identifier(v, 300)
                                              or type(v) is int and not 0 <= v <= 1000000000
                                              for v in result["locator"].values()):
        raise EnrichmentError("source_locator_invalid")
    if ("char_start" in result["locator"]) != ("char_end" in result["locator"]):
        raise EnrichmentError("source_locator_span_invalid")
    if "char_start" in result["locator"] and result["locator"]["char_start"] >= result["locator"]["char_end"]:
        raise EnrichmentError("source_locator_span_invalid")
    if result.get("source_status", "unknown") not in {"active", "unknown", "retracted", "corrected", "disputed"}:
        raise EnrichmentError("source_status_invalid")
    return result


def source_captures_from_chunks(chunks: Sequence[Mapping[str, Any]], papers: Sequence[Mapping[str, Any]]) -> tuple[list[dict], dict]:
    """Adapt actual retained SQL exports without upgrading unknown chunk lineage.

    Generated Facts/derived chunks are excluded. A paper-row capture hash is
    explicitly an inventory revision, never a verified publication version.
    If actual original-passage revision metadata exists, its kind/locator is
    retained; all other source prose stays `legacy_unknown`.
    """
    by_id = {paper["id"]: paper for paper in papers}
    captures, excluded = [], Counter()
    for chunk in chunks:
        paper = by_id.get(chunk.get("paper_id"))
        if paper is None:
            excluded["paper_capture_unavailable"] += 1
            continue
        evidence = chunk.get("evidence_revision") or {}
        if not isinstance(evidence, Mapping):
            evidence = {}
        if is_derived_source_hint(section=chunk.get("section"), paper_id=chunk.get("paper_id"), text=chunk.get("text")) or evidence.get("chunk_kind") == "derived_fact":
            excluded["derived_fact_not_original_source"] += 1
            continue
        text = chunk.get("text")
        if not isinstance(text, str) or not text or len(text) > MAX_SOURCE_CHARS:
            excluded["source_text_unavailable_or_over_limit"] += 1
            continue
        actual_hash = text_digest(text)
        exported_hash = chunk.get("text_utf8_sha256", actual_hash)
        if exported_hash != actual_hash:
            raise EnrichmentError("exported_chunk_content_changed")
        kind = evidence.get("chunk_kind") if evidence.get("chunk_kind") in {"original_passage", "abstract"} and chunk.get("evidence_record_hash_valid") is True else "legacy_unknown"
        locator = evidence.get("source_locator") if kind != "legacy_unknown" else None
        locator = {key: value for key, value in (locator or {}).items() if key in {"page", "table", "figure", "section", "row", "column", "char_start", "char_end", "xml_xpath"}}
        locator["chunk_id"] = chunk["id"]
        if chunk.get("section"):
            locator.setdefault("section", chunk["section"])
        revision = "paper-row-capture:" + paper.get("capture_revision_sha256", digest(paper))
        source_url = "https://arxiv.org/abs/" + paper["arxiv_id"] if paper.get("arxiv_id") else "https://doi.org/" + paper["doi"] if paper.get("doi") else None
        source = {"id": chunk["id"], "paper_id": chunk["paper_id"], "text": text,
                  "content_sha256": actual_hash, "source_revision": revision, "locator": locator, "kind": kind,
                  "source_url": source_url, "source_status": "retracted" if paper.get("status") == "retracted" else "unknown",
                  "source_revision_basis": "paper_row_capture_not_publication_version",
                  "publication_revision_verified": False}
        captures.append(validate_source(source))
    return captures, {"source_captures": len(captures), "excluded_chunks": dict(excluded),
                      "verified_publication_versions": 0, **AUTHORITY}


def _segments(text: str):
    # Decimal dots are retained. Offsets always refer to the original captured text.
    start = 0
    for match in re.finditer(r"[\n;]+|(?<=[.!?])\s+(?=[A-Z])", text):
        if text[start:match.start()].strip():
            yield start, match.start(), text[start:match.start()]
        start = match.end()
    if text[start:].strip():
        yield start, len(text), text[start:]


def _formulas(text):
    return [match for match in _FORMULA.finditer(text)
            if all(element in _ELEMENTS for element in re.findall(r"[A-Z][a-z]?", match.group()))]


def _formula_pattern(formula):
    # Presentation spacing may occur inside math formula tokens. No changes to
    # coefficients, signs, uncertainty or element order are made.
    return r"(?<![A-Za-z0-9])" + r"\s*".join(re.escape(char) for char in formula) + r"(?![A-Za-z0-9.(])"


def _sample_form_match(text, formula, *, require_direct_binding=False):
    """Keep physical form descriptions separate from bulk scientific properties.

    The caller supplies a locally matched formula. A form remains a pending
    literal candidate; it does not establish a sample association. In particular
    bulk superconductivity, thermodynamic evidence and a bulk superconducting
    transition say nothing about the specimen's physical form.
    """
    target = _formula_pattern(formula)
    physical_noun = r"(?i:samples?|specimens?|materials?|crystals?|pellets?)\b"
    negation = re.compile(
        rf"\b(?i:no|not|without|rather than|instead of)\s+"
        rf"(?:(?i:a|an|any)\s+)?(?:{target}\s+)?$"
    )
    forms = []
    for match in re.finditer(r"\b(single[ -]crystals?|thin[ -]films?|polycrystalline|bulk)\b", text, re.I):
        if negation.search(text[:match.start()]):
            continue
        raw = match.group().lower()
        if raw == "bulk":
            # Only an explicit physical noun (optionally following this exact
            # formula) admits bulk. Mere nearby scientific keywords do not.
            if not re.match(rf"[ -]+(?:{target}\s+)?{physical_noun}", text[match.end():]):
                continue
            value = "bulk"
        else:
            value = "single_crystal" if "single" in raw else "thin_film" if "film" in raw else "polycrystal"
        if require_direct_binding:
            # In a comparison, retain an explicit "NbN thin film" or
            # "thin films of NbN" noun phrase without inheriting the other
            # compound's form. A physical bulk noun may sit between bulk and
            # "of NbN", or follow the exact formula in "bulk NbN samples".
            before = text[:match.start()]
            after = text[match.end():]
            bound_before = re.search(rf"{target}[ -]+$", before)
            bound_after = re.match(rf"[ -]+(?i:of)[ -]+{target}", after)
            if raw == "bulk":
                bound_after = bound_after or re.match(rf"[ -]+{physical_noun}[ -]+(?i:of)[ -]+{target}", after)
                bound_after = bound_after or re.match(rf"[ -]+{target}[ -]+{physical_noun}", after)
            if not (bound_before or bound_after):
                continue
        forms.append((value, match))
    # A single-crystal statement is more specific than a physical bulk noun;
    # sentence order must not let an earlier bulk property hide that statement.
    return next((form for form in forms if form[0] == "single_crystal"), forms[0] if forms else None)


def _simple_composition(formula):
    formula = normalize_formula(re.sub(r"(?<=[0-9])\(\d+\)", "", formula))
    parts = re.findall(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)?", formula)
    if not parts or "".join(element + number for element, number in parts) != formula:
        return None
    composition = {}
    for element, number in parts:
        if element not in _ELEMENTS or element in composition:
            return None
        composition[element] = Decimal(number or "1")
    return composition


def discover_identity_candidates(material, record, sources):
    """Propose nominal/refined sample links from explicit refinement context.

    A nearby composition alone is insufficient: this requires a source block
    explicitly discussing refinement and an uncertainty-bearing formula whose
    central coefficients match the catalogue. The relation stays pending and
    its exact source capture travels with every downstream field candidate.
    """
    target = _simple_composition(material["formula"])
    if target is None:
        return []
    results = []
    for source in sources:
        if source["paper_id"] != record.get("paper_id") or source.get("table") is not None:
            continue
        flat, _ = _flat(source["text"])
        if not re.search(r"\b(?:refined|refinement|x.ray analysis)\b", flat, re.I) or _DIRECTIVE.search(flat):
            continue
        mentions = _formulas(flat)
        refined = [m.group() for m in mentions if re.search(r"(?<=\d)\(\d+\)", m.group()) and _simple_composition(m.group()) == target]
        if not refined:
            continue
        nominal = {}
        for mention in mentions:
            formula = normalize_formula(mention.group())
            composition = _simple_composition(formula)
            if composition is None or set(composition) != set(target) or composition == target or "(" in formula:
                continue
            # This is a bounded candidate search tolerance, never equivalence.
            if all(abs(composition[element] - target[element]) <= Decimal("0.02") for element in target):
                nominal[formula] = mention.group()
        for formula, raw_formula in nominal.items():
            value = {"catalogue_formula": material["formula"], "source_formula": formula,
                     "refined_formula_raw": refined[0], "nominal_formula_raw": raw_formula,
                     "relation": "nominal_refined_same_sample_proposal", "association_reviewed": False}
            candidate = _candidate(material=material, record=record, source=source,
                field="composition_identity", raw_value=value, start=0, end=len(source["text"]),
                sentence=source["text"], context=_context(flat),
                identity_basis="source_refinement_context_proposal",
                reasons=["nominal_refined_composition_binding_requires_review", "near_composition_is_not_identity", "source_lifecycle_requires_review"])
            results.append(candidate)
            ratio = re.search(rf"\b([A-Z][a-z]?)\s*:\s*([A-Z][a-z]?)\s+ratio\s+of\s+({_NUMBER}(?:\(\d+\))?)\s*:\s*({_NUMBER}(?:\(\d+\))?)", flat)
            if ratio and re.search(r"\bsame site\b", flat, re.I):
                fractions = {ratio[1]: ratio[3], ratio[2]: ratio[4]}
                site_value = {"site_elements": [ratio[1], ratio[2]], "fractions_raw": fractions,
                              "interpretation": "source_reported_refined_same_site_ratio",
                              "occupancy_and_structure_binding_reviewed": False}
                site = _candidate(material=material, record=record, source=source, field="site_occupancies",
                    raw_value=site_value, start=0, end=len(source["text"]), sentence=source["text"],
                    context=_context(flat), identity_basis="source_refinement_context_proposal",
                    reasons=["source_refined_site_ratio_requires_review", "nominal_refined_composition_binding_requires_review"])
                site["identity_candidate"] = {"candidate_id": candidate["candidate_id"],
                                              "source": candidate["source"], "association_reviewed": False}
                site["candidate_id"] = "enrichment:" + digest({key: val for key, val in site.items() if key not in {"candidate_id", "evidence_text"}})
                results.append(site)
    return results


def _quantity(raw: str, field: str, unit: str | None = None) -> dict[str, Any]:
    # Parenthetical crystallographic uncertainty is absolute in the last digits.
    original = raw
    match = re.fullmatch(rf"({_NUMBER})\((\d+)\)", raw.strip())
    if match:
        uncertainty = Decimal(match[2]) * Decimal(10) ** Decimal(Decimal(match[1]).as_tuple().exponent)
        raw = f"{match[1]} ± {uncertainty}"
    quantity = parse_scientific_value(raw, field, raw_unit=unit)
    quantity["raw_value"] = original
    if match and quantity["status"] == "parsed":
        quantity["uncertainty_interpretation"] = "source_parenthetical_last_digits_unspecified_statistical_basis"
        quantity["normalization_version"] = EXTRACTOR_VERSION
    return quantity


def _label(text: str, patterns: Mapping[str, re.Pattern]) -> str | None:
    labels = [key for key, pattern in patterns.items() if pattern.search(text)]
    return labels[0] if len(labels) == 1 else None


def _tc_calculation_match(text):
    """Finite explicit Tc-to-solver relation, not paper-wide method inheritance.

    DFT/DFPT may supply structure, bands or EPC inputs and are not Tc solvers.
    Unrecognized, cross-clause, multi-subject and alternative-method relations
    deliberately remain unresolved. A match is still a pending source reading.
    """
    anchors = list(_TC.finditer(text))
    methods = [(key, match) for key, pattern in _TC_CALCULATION_METHODS.items()
               for match in pattern.finditer(text)]
    if len(anchors) != 1 or len(methods) != 1 or len({normalize_formula(m.group()) for m in _formulas(text)}) > 1:
        return None
    key, method = methods[0]
    anchor = anchors[0]
    prefix = text[max(0, min(method.start(), anchor.start()) - 80):min(method.start(), anchor.start())]
    if re.search(r"\b(?:not|no|never|without|neither)\b", prefix, re.I):
        return None
    gap = text[anchor.end():method.start()] if anchor.end() <= method.start() else text[method.end():anchor.start()]
    # This small vocabulary excludes negation, comparisons, alternatives and
    # other named properties. A solver appearing elsewhere cannot fill Tc.
    words = r"temperature|is|was|were|of|at|a|an|the|calculated|computed|estimated|predicted|obtained|evaluated|determined|using|used|from|via|with|by|to|calculate|compute|estimate|predict|evaluate|determine|solve|solving|equations?|formula|formalism|gives?|yields?|predicts?|calculates?|estimates?|K|kelvin|mK|GPa|MPa|kbar"
    allowed = rf"(?:[\s=():,]|{_VALUE}|\b(?:{words})\b)*"
    relation = r"\b(?:calculated|computed|estimated|predicted|obtained|evaluated|determined|using|from|via|with|by|calculate|compute|estimate|predict|evaluate|determine|solve|solving|gives?|yields?|predicts?|calculates?|estimates?)\b"
    if not gap or len(gap) > 200 or re.fullmatch(allowed, gap, re.I) is None or re.search(relation, gap, re.I) is None:
        return None
    return key, method


def _tc_measurement_match(text):
    methods = [(key, match) for key, pattern in _MEASUREMENT_METHODS.items()
               for match in pattern.finditer(text) if key != "x_ray_diffraction"]
    anchors = list(_TC.finditer(text))
    formulas = _formulas(text)
    if len(methods) != 1 or len(anchors) != 1 or len({normalize_formula(m.group()) for m in formulas}) > 1:
        return None
    key, method = methods[0]
    anchor = anchors[0]
    start, end = (anchor.end(), method.start()) if anchor.end() <= method.start() else (method.end(), anchor.start())
    gap = text[start:end]
    # A directly named formula is permitted in e.g. "resistivity of NbN
    # shows Tc". Arbitrary narrative, normal-state quantities and comparisons
    # are excluded instead of inheriting the paper's measurement inventory.
    for formula in formulas:
        if start <= formula.start() and formula.end() <= end:
            gap = gap.replace(formula.group(), " ")
    prefix = text[max(0, min(method.start(), anchor.start()) - 80):min(method.start(), anchor.start())]
    if re.search(r"\b(?:not|no|never|without|neither)\b", prefix, re.I):
        return None
    words = r"temperature|is|was|were|of|at|a|an|the|measured|measurement|measurements|observed|determined|detected|obtained|using|used|from|via|with|by|to|measure|shows?|gives?|yields?|confirms?|reveals?|indicates?|K|kelvin|mK|GPa|MPa|kbar"
    allowed = rf"(?:[\s=():,]|{_VALUE}|\b(?:{words})\b)*"
    relation = r"\b(?:measured|observed|determined|detected|obtained|using|from|via|with|by|measure|shows?|gives?|yields?|confirms?|reveals?|indicates?)\b"
    if not gap or len(gap) > 200 or re.fullmatch(allowed, gap, re.I) is None or re.search(relation, gap, re.I) is None:
        return None
    return key


def _tc_method_context(context, text=None):
    # Generic source-method statements (notably diffraction) are not Tc
    # measurements. A directly bound Tc solver has its own calculation role.
    return {**context, "measurement_method": _tc_measurement_match(text)
            if text and not context.get("calculation_method") else None}


def _direct_quantity_binding(text, anchor, quantity):
    if anchor.end() > quantity.start():
        return False
    gap = text[anchor.end():quantity.start()]
    return len(gap) <= 45 and re.fullmatch(r"(?:[\s=():,]|\b(?:temperature|is|was|of|at|a|an|the|by|up|to|below|above|reaches|reached|approximately|around|about|as|high)\b)*", gap, re.I) is not None


def _context(text: str) -> dict[str, Any]:
    pressures = [_quantity(match[1], "pressure_gpa", match[2]) for match in _PRESSURE.finditer(text)
                 if not _extent_pressure(text, match)]
    ambient = bool(re.search(r"\b(?:ambient|atmospheric) pressure\b", text, re.I))
    pressure = pressures[0] if len(pressures) == 1 else None
    if ambient and not pressures:
        pressure = _quantity("0", "pressure_gpa", "GPa")
    state = "explicit_ambient" if ambient and not pressures else "reported" if len(pressures) == 1 else "ambiguous" if pressures else "not_reported"
    if ambient and pressures:
        state = "ambiguous"
    labels = {}
    for key in ("sample", "state", "phase", "run"):
        found = re.findall(rf"\b{key}(?:\s+(?:id|label))?\s*[:=]\s*([A-Za-z0-9_.+\-]+)", text, re.I)
        if len(set(found)) == 1:
            labels[key + "_label"] = found[0]
    computed, observed = bool(_COMPUTED.search(text)), bool(_OBSERVED.search(text))
    calculation = _tc_calculation_match(text)
    return {"pressure_state": state, "pressure_quantity": pressure,
            "knowledge_origin": "Computed" if computed and not observed else "Observed" if observed and not computed else "Unknown",
            "measurement_method": _label(text, _MEASUREMENT_METHODS),
            "calculation_method": calculation[0] if calculation else None, **labels}


def _candidate(*, material, record, source, field, raw_value, quantity=None,
               start, end, sentence, context, reasons, identity_basis="exact_formula_local"):
    result = {
        "version": VERSION, "extractor_version": EXTRACTOR_VERSION,
        "material_id": material["id"], "retained_result_id": legacy_result_id(record, scope_id=material["id"]),
        "retained_record_sha256": digest(record), "field": field, "raw_value": raw_value,
        "quantity": quantity, "value": quantity.get("value") if quantity else raw_value,
        "subject": {"formula": material["formula"], "identity_basis": identity_basis,
                    "association_status": "pending_source_and_state_review", **context},
        "source": {"paper_id": source["paper_id"], "capture_id": source["id"],
                   "kind": source["kind"], "source_revision": source["source_revision"],
                   "content_sha256": source["content_sha256"], "locator": source["locator"],
                   "span": {"char_start": start, "char_end": end, "text_sha256": text_digest(source["text"][start:end])},
                   "source_url": source.get("source_url"), "capture_sha256": source.get("capture_sha256"),
                   "source_status": source.get("source_status", "unknown")},
        # Private candidates retain the short context. Reports can omit it.
        "evidence_text": sentence, "evidence_text_sha256": text_digest(sentence),
        "disposition": "pending", "reason_codes": sorted(set(reasons)),
        "source_content_checked": False, "material_state_reviewed": False,
        "coordinates_validated": False, **AUTHORITY,
    }
    result["source"]["source_revision_basis"] = source.get("source_revision_basis", "source_asserted_publication_revision")
    result["source"]["publication_revision_verified"] = source.get("publication_revision_verified", False)
    if field in {"space_group", "crystal_structure"}:
        result["review_requirements"] = ["exact_source_content_review", "material_state_association_review"]
    else:
        result["review_requirements"] = ["exact_source_content_review", "material_state_association_review", "quantity_and_method_review"]
    result["candidate_id"] = "enrichment:" + digest({key: value for key, value in result.items() if key != "evidence_text"})
    return result


def extract_source_candidates(material: Mapping[str, Any], record: Mapping[str, Any], source: Mapping[str, Any]) -> list[dict]:
    """Extract a narrow grammar from this retained record's own original source."""
    source = validate_source(source)
    if source["paper_id"] != record.get("paper_id"):
        raise EnrichmentError("retained_source_scope_mismatch")
    formula = normalize_formula(material["formula"])
    candidates = []
    for left, right, sentence in _segments(source["text"]):
        flat, offsets = _flat(sentence)
        # Formula uncertainty is not discarded to claim exact identity.
        target_pattern = _formula_pattern(formula)
        matches = list(re.finditer(target_pattern, flat))
        if not matches or _DIRECTIVE.search(flat):
            continue
        all_formulas = {normalize_formula(m.group()) for m in _formulas(flat)}
        reasons = ["literal_extraction_not_source_review"]
        if len(all_formulas) > 1:
            reasons.append("multiple_materials_in_local_context")
        if _CAUTION.search(flat):
            reasons.append("cited_negative_or_qualified_context")
        if source.get("source_status", "unknown") != "active":
            reasons.append("source_lifecycle_requires_review")
        if source["kind"] == "legacy_unknown":
            reasons.append("legacy_chunk_origin_unresolved")
        context = _context(flat)
        if context["pressure_state"] == "ambiguous":
            reasons.append("multiple_or_conflicting_pressure_context")

        def add(field, raw_value, match=None, quantity=None, local_context=None, extra=(), *,
                _left=left, _right=right, _offsets=offsets, _sentence=sentence,
                _context=context, _reasons=tuple(reasons)):
            start = _left + _offsets[match.start()] if match is not None else _left
            end = _left + _offsets[match.end() - 1] + 1 if match is not None else _right
            proposed = _candidate(material=material, record=record, source=source, field=field,
                raw_value=raw_value, quantity=quantity, start=start, end=end, sentence=_sentence,
                context=local_context or _context, reasons=[*_reasons, *extra])
            if quantity is not None and quantity["status"] != "parsed":
                proposed["reason_codes"].append("quantity_parser_review")
                proposed["candidate_id"] = "enrichment:" + digest({k: v for k, v in proposed.items() if k not in {"candidate_id", "evidence_text"}})
            candidates.append(proposed)

        tc_matches = list(_TC.finditer(flat))
        criterion_matches = [(key, match) for key, pattern in _CRITERIA.items() for match in pattern.finditer(flat)]
        temperatures = list(_TEMPERATURE.finditer(flat))
        respective_pair = re.search(rf"({_VALUE})\s*(?:K)?\s+and\s+({_VALUE})\s*(K|kelvin)\b", flat)
        formula_mentions = _formulas(flat)
        respective = bool(re.search(r"\brespectively\b", flat, re.I))
        aligned = respective and respective_pair is not None and len(formula_mentions) == 2 and len(all_formulas) == 2 and len(tc_matches) == 1
        if aligned:
            target_index = next((i for i, mention in enumerate(formula_mentions) if normalize_formula(mention.group()) == formula), None)
            if target_index is not None:
                raw = respective_pair[target_index+1].strip()
                add("tc_kelvin", raw + " " + respective_pair[3], respective_pair,
                    _quantity(raw, "tc_kelvin", respective_pair[3]),
                    {**_tc_method_context(context, flat), "tc_criterion": "unknown", "respective_alignment": target_index},
                    extra=("explicit_respectively_alignment_requires_review",))
        for match in temperatures if not aligned and len(all_formulas) <= 1 else []:
            anchors = [(abs(match.start() - tc.end()), "unknown", tc) for tc in tc_matches if _direct_quantity_binding(flat, tc, match)]
            anchors += [(abs(match.start() - cr.end()), key, cr) for key, cr in criterion_matches if _direct_quantity_binding(flat, cr, match)]
            # A structural measurement temperature is not a Tc.
            if not anchors or min(distance for distance, _, _ in anchors) > 85:
                continue
            distance, criterion, anchor = min(anchors, key=lambda item: (item[0], item[1] == "unknown"))
            between = flat[min(anchor.end(), match.start()):max(anchor.end(), match.start())]
            if re.search(r"\b(?:width|Delta|measurement temperature|diffraction at|down to)\b|ΔT", between, re.I):
                continue
            if re.search(r"\b(?:width|measurement temperature|diffraction at|down to)\b|ΔT", flat[max(0, match.start()-35):match.start()], re.I):
                continue
            nearest_criteria = sorted(criterion_matches, key=lambda item: abs(match.start() - item[1].end()))
            if criterion == "unknown" and nearest_criteria and abs(match.start() - nearest_criteria[0][1].end()) < 45:
                criterion = nearest_criteria[0][0]
            quantity = _quantity(match[1], "tc_kelvin", match[2])
            if quantity["status"] == "parsed" and any(quantity.get(k) is not None and quantity[k] <= 0 for k in ("value", "lower", "upper")):
                continue
            local = {**_tc_method_context(context, flat), "tc_criterion": criterion}
            add("tc_kelvin", match.group(), match, quantity, local)
            if criterion != "unknown":
                add("tc_criterion", criterion, anchor, local_context=local)
        pressure_matches = list(_PRESSURE.finditer(flat))
        for match in pressure_matches:
            if _extent_pressure(flat, match):
                continue
            # Multiple conditions in a multi-material statement cannot be
            # assigned by mere sentence cooccurrence. Retain only a pressure
            # following this exact formula before the next different formula.
            if len(pressure_matches) > 1 and len(all_formulas) > 1:
                attributable = any(target.end() <= match.start() and not any(
                    other.start() >= target.end() and other.start() < match.end()
                    and normalize_formula(other.group()) != formula for other in formula_mentions)
                    for target in matches)
                if not attributable:
                    continue
            add("pressure_gpa", match.group(), match, _quantity(match[1], "pressure_gpa", match[2]))
        if context["pressure_state"] == "explicit_ambient":
            add("pressure_gpa", "ambient pressure", quantity=context["pressure_quantity"])
        direct_structure = list(re.finditer(rf"\b({_SG_TOKEN})\s*[-−]\s*{target_pattern}", flat))
        generic_structure = list(_SG.finditer(flat)) + list(_SG_PREFIX.finditer(flat)) if len(all_formulas) <= 1 else []
        for match in direct_structure + generic_structure:
            add("space_group", match[1], match, extra=("text_structure_coordinates_separate",))
        crystal = re.search(r"\b(tetragonal|orthorhombic|hexagonal|cubic|monoclinic|triclinic|trigonal|rhombohedral)\b", flat, re.I)
        if crystal and re.search(r"\b(?:structure|phase|space.group|crystall)\b", flat, re.I):
            add("crystal_structure", crystal.group().lower(), crystal, extra=("text_structure_coordinates_separate",))
        for match in _LATTICE.finditer(flat):
            field = "lattice_" + match[1].lower()
            unit = match[2] or match[4]
            if not unit or field not in FIELD_UNITS:
                continue
            add(field, match.group(), match, _quantity(match[3], field, unit))
        for field, label in _NUMERIC_LABELS.items():
            pattern = re.compile(rf"{label}\s*(?:=|is|of|:|approximately)?\s*({_VALUE})\s*(K|meV|THz|cm\^-1|T|mT|nm|angstrom|Å)?", re.I)
            for match in pattern.finditer(flat):
                if field == "lambda_eph" and match.group().lstrip().startswith("λ") and not re.search(r"\b(?:electron[ -]phonon|EPC)\b", flat, re.I):
                    continue
                unit = match[2]
                if FIELD_UNITS[field] != "1" and not unit:
                    continue
                add(field, match.group(), match, _quantity(match[1], field, unit))
        for field, match in _source_field_matches(flat):
            # Only a preceding foreign subject can own this property. Scientific
            # assignments such as B=2 T or Tc=16 K are not elemental subjects.
            if _SOURCE_ELEMENT_COMPARISON.search(flat[:match.start()]):
                continue
            if len(all_formulas) > 1 and not any(target.end() <= match.start() and not any(
                    other.start() >= target.end() and other.start() < match.end()
                    and normalize_formula(other.group()) != formula for other in formula_mentions)
                    and re.fullmatch(r"\s*(?:has|shows|exhibits|:)\s*", flat[target.end():match.start()], re.I)
                    for target in matches):
                continue
            def original_span(a, z, _left=left, _offsets=offsets):
                start, end = _left + _offsets[a], _left + _offsets[z-1] + 1
                # Flattening removed presentation braces. Include closing TeX
                # delimiters belonging to this token; do not cut H_{c1} or K^{-2}.
                depth = source["text"][start:end].count("{") - source["text"][start:end].count("}")
                if 0 < depth <= 8 and source["text"][end:end+depth] == "}" * depth:
                    end += depth
                return {"char_start": start, "char_end": end,
                        "text_sha256": text_digest(source["text"][start:end])}
            value_span = original_span(match.start("amount"), match.end("amount"))
            unit_span = original_span(match.start("unit"), match.end("unit")) if match.groupdict().get("unit") is not None else None
            if unit_span is not None:
                unit_start, unit_end = unit_span["char_start"], unit_span["char_end"]
                wrapper = re.search(r"\\(?:mathrm|text|rm)\s*\{\s*$", source["text"][max(left, unit_start-24):unit_start])
                if wrapper is not None and source["text"][unit_end:unit_end+1] == "}":
                    unit_start = max(left, unit_start-24) + wrapper.start()
                    depth = source["text"][unit_start:unit_end].count("{") - source["text"][unit_start:unit_end].count("}")
                    if 0 < depth <= 8 and source["text"][unit_end:unit_end+depth] == "}" * depth:
                        unit_end += depth
                    unit_span = {"char_start": unit_start, "char_end": unit_end,
                                 "text_sha256": text_digest(source["text"][unit_start:unit_end])}
            end = (unit_span or value_span)["char_end"]
            # Recover from captured text, not NFKC/TeX-flattened presentation.
            raw = source["text"][value_span["char_start"]:end].strip()
            amount = source["text"][value_span["char_start"]:value_span["char_end"]]
            uncertainty = re.search(r"\(\d+\)|(?:±|\+/-)\s*[-+−]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", amount)
            role = _SOURCE_FIELD_SPECS[field][2]
            qualifiers = []
            if _CAUTION.search(flat):
                qualifiers.append("cited_negative_or_qualified_context")
            if _COMPUTED.search(flat):
                qualifiers.append("model_or_calculation_context")
            if re.search(r"\b(?:fit|fitted|estimate|estimated|extrapolat)\w*\b", flat, re.I):
                qualifiers.append("fit_or_estimate_context")
            if re.search(r"\b(?:model|inferred|deduced|rather than measured|not measured)\b", flat, re.I):
                qualifiers.append("inference_or_unmeasured_context")
            proposed = _candidate(material=material, record=record, source=source, field=field,
                raw_value=raw, start=value_span["char_start"], end=end, sentence=sentence,
                context={**context, "field_role": role},
                reasons=[*reasons, "raw_source_value_not_normalized", "reported_scope_requires_review"])
            proposed["source_value"] = {"raw_value": raw,
                "raw_unit": source["text"][unit_span["char_start"]:unit_span["char_end"]].strip() if unit_span else None,
                "raw_uncertainty": uncertainty.group() if uncertainty else None,
                "normalization": "none", "role": role, "qualifiers": qualifiers,
                "field_cue": source["text"][original_span(match.start("cue"), match.end("cue"))["char_start"]:original_span(match.start("cue"), match.end("cue"))["char_end"]],
                "value_span": value_span, "unit_span": unit_span,
                "cue_span": original_span(match.start("cue"), match.end("cue"))}
            proposed["candidate_id"] = "enrichment:" + digest({k: v for k, v in proposed.items() if k not in {"candidate_id", "evidence_text"}})
            candidates.append(proposed)
        if context["measurement_method"]:
            add("measurement_method", context["measurement_method"],
                _MEASUREMENT_METHODS[context["measurement_method"]].search(flat),
                local_context={**context, "field_role": "source_measurement_method"})
        calculation = _tc_calculation_match(flat)
        if calculation:
            add("calculation_method", calculation[0], calculation[1],
                local_context={**_tc_method_context(context), "field_role": "tc_calculation_method"})
        # Multiple formula-like tokens require an explicit local noun-phrase
        # binding. They must not erase a directly named subject's own form or
        # allow another compound's form to transfer by mere cooccurrence.
        form = _sample_form_match(flat, formula, require_direct_binding=len(all_formulas) > 1)
        if form:
            add("sample_form", form[0], form[1])
    return list({row["candidate_id"]: row for row in candidates}.values())


def extract_table_candidates(material, record, source):
    """Column-bound rectangular tables; comparison columns never cross-fill.

    The source adapter supplies cells + exact spans into its captured table text.
    Headers require an exact formula. Nominal/refined compositions remain
    separate until a reviewer establishes their relation.
    """
    source = validate_source(source)
    table = source.get("table")
    if table is None:
        return []
    if source["paper_id"] != record.get("paper_id") or source["kind"] != "table" or type(table) is not dict:
        raise EnrichmentError("table_source_scope_invalid")
    headers, rows = table.get("headers"), table.get("rows")
    if type(headers) is not list or type(rows) is not list or len(headers) > 30 or len(rows) > 500:
        raise EnrichmentError("table_shape_invalid")
    columns = [i for i, header in enumerate(headers) if normalize_formula(str(header)) == normalize_formula(material["formula"])]
    if len(columns) != 1:
        return []
    column = columns[0]
    result, context = [], {"pressure_state": "not_reported", "pressure_quantity": None,
                          "knowledge_origin": "Unknown", "measurement_method": None,
                          "table_column_formula": headers[column], "table_column": column}
    labels = {"space group": "space_group", "structure": "crystal_structure", "temperature": "measurement_temperature_k"}
    previous_label = None
    for row_index, row in enumerate(rows):
        if type(row) is not dict or type(row.get("cells")) is not list or len(row["cells"]) != len(headers):
            raise EnrichmentError("table_row_shape_invalid")
        cell = row["cells"][column]
        if type(cell) is not dict or set(cell) != {"text", "char_start", "char_end"}:
            raise EnrichmentError("table_cell_capture_required")
        start, end = cell["char_start"], cell["char_end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"]) or source["text"][start:end] != cell["text"]:
            raise EnrichmentError("table_cell_source_changed")
        label = re.sub(r"\s+", " ", str(row.get("label", ""))).strip().lower()
        value = cell["text"].strip()
        field, quantity = labels.get(label), None
        if field == "measurement_temperature_k":
            quantity = _quantity(value, field)
        elif label.startswith(("a(", "a (", "b(", "b (", "c(", "c (")):
            field = "lattice_" + label[0]
            unit_match = re.search(r"(angstrom|Å|Å|nm|pm)", str(row["label"]))
            if not unit_match or value.startswith("="):
                # a=b is a relation, not a reported b scalar.
                continue
            quantity = _quantity(value, field, unit_match[1])
        elif label in {"ba", "fe/pt", "as", "fe", "pt"}:
            field = "atomic_sites"
        elif label in {"", "—", "-"} and previous_label in {"ba", "fe/pt", "as", "fe", "pt"} and re.fullmatch(rf"[xyz]\s*=\s*{_NUMBER}(?:\(\d+\))?", value):
            field = "atomic_sites"
            value = {"site": previous_label, "fractional_coordinate_raw": value,
                     "full_coordinates_and_symmetry_reviewed": False}
        elif "occupanc" in label:
            field = "site_occupancies"
        previous_label = label
        if field is None or not value or isinstance(value, str) and value in {"—", "-"}:
            continue
        row_source = {**source, "locator": {**source["locator"], "row": row_index, "column": column}}
        candidate = _candidate(material=material, record=record, source=row_source, field=field,
            raw_value=value, quantity=quantity, start=start, end=end,
            sentence=source["text"][start:end], context=context,
            identity_basis="exact_table_column_formula",
            reasons=["column_bound_extraction_not_source_review", "table_state_association_requires_review"])
        candidate["table_row_label"] = row["label"]
        # Table metadata is part of identity, never mutable annotation.
        candidate["candidate_id"] = "enrichment:" + digest({k: v for k, v in candidate.items() if k not in {"candidate_id", "evidence_text"}})
        result.append(candidate)
    return result


def extract_retained_quantity_matches(material, record, source):
    """Locate retained Tc values in the same paper when the sentence is anaphoric.

    This is a search hit with unresolved subject binding. It does not insert a
    new value, claim a source statement about this material, or infer a missing
    criterion. It supplies a concrete locator for review of e.g. `x=0.10 sample`.
    """
    quantity = record_quantity(record, "tc_kelvin", "tc")
    if quantity["status"] != "parsed" or quantity["relation"] != "exact" or source.get("table") is not None:
        return []
    if source["paper_id"] != record.get("paper_id"):
        raise EnrichmentError("retained_source_scope_mismatch")
    candidates = []
    for left, _right, sentence in _segments(source["text"]):
        flat, offsets = _flat(sentence)
        if _DIRECTIVE.search(flat) or re.search(_formula_pattern(normalize_formula(material["formula"])), flat):
            continue
        anchors = list(_TC.finditer(flat))
        criteria = [(key, match) for key, pattern in _CRITERIA.items() for match in pattern.finditer(flat)]
        for match in _TEMPERATURE.finditer(flat):
            proposed = _quantity(match[1], "tc_kelvin", match[2])
            if proposed["status"] != "parsed" or proposed["relation"] != "exact" or proposed["value"] != quantity["value"]:
                continue
            near = [(abs(match.start()-anchor.end()), "unknown") for anchor in anchors if _direct_quantity_binding(flat, anchor, match)]
            near += [(abs(match.start()-anchor.end()), key) for key, anchor in criteria if _direct_quantity_binding(flat, anchor, match)]
            if not near or min(distance for distance, _ in near) > 65 or re.search(r"\b(?:width|down to|measurement temperature)\b|ΔT", flat[max(0, match.start()-35):match.start()], re.I):
                continue
            _, criterion = min(near, key=lambda item: (item[0], item[1] == "unknown"))
            # Equal retained values locate a source window, not the subject of
            # that window. Its methods cannot fill this material's Tc method.
            context = {**_tc_method_context(_context(flat)), "tc_criterion": criterion,
                       "measurement_method": None, "calculation_method": None}
            reasons = ["retained_quantity_match_not_material_entailment", "material_identifier_not_local",
                       "exact_source_and_sample_association_requires_review"]
            if source["kind"] == "legacy_unknown":
                reasons.append("legacy_chunk_origin_unresolved")
            if _CAUTION.search(flat):
                reasons.append("cited_negative_or_qualified_context")
            candidates.append(_candidate(material=material, record=record, source=source,
                field="tc_kelvin", raw_value=match.group(), quantity=proposed,
                start=left+offsets[match.start()], end=left+offsets[match.end()-1]+1,
                sentence=sentence, context=context, reasons=reasons,
                identity_basis="retained_quantity_source_scoped_search_hit"))
    return candidates


def _present(record, field):
    raw = record.get("raw_extraction") if isinstance(record.get("raw_extraction"), Mapping) else record
    if field in FIELD_UNITS:
        if field.startswith("lattice_"):
            axis = field.removeprefix("lattice_")
            lattice = raw.get("lattice_params")
            return isinstance(lattice, Mapping) and lattice.get(axis) is not None or record_quantity(raw, field)["status"] == "parsed"
        return record_quantity(raw, field, *(("tc",) if field == "tc_kelvin" else ()))["status"] == "parsed"
    if field in {"measurement_method", "calculation_method"}:
        keys = ("measurement_method", "measurement") if field == "measurement_method" else ("calculation_method",)
        opposite = _CALCULATION_HINTS if field == "measurement_method" else _MEASUREMENT_METHODS
        for key in keys:
            value = raw.get(key)
            if value is not None and str(value).strip().lower() not in {"", "unknown", "none", "n/a", "not_reported"}:
                if not any(pattern.search(str(value).replace("_", " ")) for pattern in opposite.values()):
                    return True
        # Legacy generic method is usable only when its method role is explicit
        # in the token itself. Unknown protocols must not fill both roles.
        method = str(raw.get("method") or "").replace("_", " ")
        patterns = _MEASUREMENT_METHODS if field == "measurement_method" else _CALCULATION_HINTS
        return _label(method, patterns) is not None and not any(pattern.search(method) for pattern in opposite.values())
    aliases = {"tc_criterion": ("tc_criterion", "tc_definition", "tc_type")}
    return any(raw.get(key) is not None and str(raw[key]).strip().lower() not in {"", "unknown", "none", "n/a", "not_reported"}
               for key in aliases.get(field, (field,)))


def build_record_field_coverage(material_id, records, *, records_total=None, record_offsets=None):
    """Describe retained values in an exact bounded subset, without source claims.

    This independently hashed DTO is intentionally outside enrichment report
    and candidate identities. Missing means no retained value, not absence in
    a paper. Uninspected occurrences remain unchecked even if another record
    supplies the same field. Opposite method roles are excluded only for a
    missing value with an unambiguous, resolved result origin.
    """
    if not _identifier(material_id, 100) or "\x7f" in material_id:
        raise EnrichmentError("record_coverage_material_id_invalid")
    if (type(records) is not list or len(records) > MAX_RECORD_COVERAGE_RECORDS
            or any(not isinstance(record, Mapping) for record in records)):
        raise EnrichmentError("record_coverage_records_invalid")
    total = len(records) if records_total is None else records_total
    if type(total) is not int or not len(records) <= total <= MAX_RECORD_COVERAGE_TOTAL:
        raise EnrichmentError("record_coverage_total_invalid")
    offsets = list(range(len(records))) if record_offsets is None else record_offsets
    if (type(offsets) is not list or len(offsets) != len(records)
            or any(type(offset) is not int or not 0 <= offset < total for offset in offsets)
            or len(set(offsets)) != len(offsets)):
        raise EnrichmentError("record_coverage_offsets_invalid")
    unchecked = total - len(records)
    # The legacy route registry includes set-derived insertion order. Give the
    # independent DTO a stable order without changing existing report hashes.
    fields = tuple(sorted(FIELD_ROUTES))
    field_counts = {field: {"present": 0, "missing": 0, "unchecked": unchecked,
                            "not_applicable": 0} for field in fields}
    unknown_applicability = dict.fromkeys(fields, 0)
    rows = []
    for offset, record in zip(offsets, records):
        origin = classify_result(record)
        resolved = origin.classification_status == "resolved" and origin.source_role != "conflicted"
        values = []
        for field in fields:
            # Preserve actual retained role values before applying an exclusion.
            if _present(record, field):
                status = "present"
                reasons = ["retained_value_not_independent_source_or_state_review"]
            elif (resolved and ((field == "measurement_method" and origin.knowledge_origin == "Computed")
                               or (field == "calculation_method" and origin.knowledge_origin == "Observed"))):
                status = "not_applicable"
                reasons = ["resolved_computed_result_has_no_retained_measurement_method"
                           if field == "measurement_method" else
                           "resolved_observed_result_has_no_retained_calculation_method"]
            else:
                status = "missing"
                reasons = ["no_retained_value_in_inspected_record"]
                if (field in {"measurement_method", "calculation_method"}
                        and (not resolved or origin.knowledge_origin not in {"Observed", "Computed"})):
                    unknown_applicability[field] += 1
                    reasons.append("method_role_applicability_unresolved")
            field_counts[field][status] += 1
            values.append({"field": field, "status": status, "reason_codes": reasons})
        paper_id = record.get("paper_id")
        rows.append({"record_offset": offset, "result_id": legacy_result_id(record, scope_id=material_id),
                     "record_sha256": digest(record),
                     "paper_id": paper_id if _identifier(paper_id, 100) and "\x7f" not in paper_id else None,
                     "knowledge_origin": origin.knowledge_origin,
                     "classification_status": origin.classification_status,
                     "fields": values})
    result = {"version": RECORD_COVERAGE_VERSION, "material_id": material_id,
              "record_denominator": "current_eligible_retained_records",
              "records_total": total, "records_inspected": len(records),
              "records_unchecked": unchecked, "records_limit": MAX_RECORD_COVERAGE_RECORDS,
              "records": rows,
              "fields": [{"field": field, "counts": field_counts[field],
                          "applicability_unknown": unknown_applicability[field]} for field in fields],
              "limitations": ["retained_value_presence_is_not_scientific_acceptance",
                              "missing_retained_value_is_not_source_absence",
                              "unchecked_records_have_no_field_or_applicability_assessment",
                              "method_role_exclusions_do_not_assert_a_joint_sample_or_run"], **AUTHORITY}
    result["coverage_sha256"] = digest(result)
    return result


def _deduplicate_source_facts(candidates):
    """One source fact may point to multiple retained records, never many studies."""
    groups = defaultdict(list)
    for candidate in candidates:
        basis = {key: value for key, value in candidate.items()
                 if key not in {"candidate_id", "retained_result_id", "retained_record_sha256", "evidence_text"}}
        if "identity_candidate" in basis:
            basis["identity_candidate"] = {key: value for key, value in basis["identity_candidate"].items() if key != "candidate_id"}
        groups[digest(basis)].append(candidate)
    merged, aliases = [], {}
    for rows in groups.values():
        rows = sorted(rows, key=lambda row: row["candidate_id"])
        candidate = json.loads(canonical(rows[0]))
        candidate["retained_result_refs"] = sorted({(row["retained_result_id"], row["retained_record_sha256"]) for row in rows})
        candidate["retained_result_refs"] = [{"result_id": identifier, "record_sha256": checksum}
                                             for identifier, checksum in candidate["retained_result_refs"]]
        candidate["retained_reference_count"] = len(candidate["retained_result_refs"])
        candidate["candidate_id"] = "enrichment:" + digest({key: value for key, value in candidate.items() if key not in {"candidate_id", "evidence_text"}})
        for row in rows:
            aliases[row["candidate_id"]] = candidate["candidate_id"]
        merged.append(candidate)
    for candidate in merged:
        identity = candidate.get("identity_candidate")
        if identity is not None:
            identity["candidate_id"] = aliases[identity["candidate_id"]]
            candidate["candidate_id"] = "enrichment:" + digest({key: value for key, value in candidate.items() if key not in {"candidate_id", "evidence_text"}})
    return sorted(merged, key=lambda row: row["candidate_id"])


def build_enrichment_report(materials: Sequence[Mapping[str, Any]], sources: Sequence[Mapping[str, Any]], *,
                            source_coverage: Mapping[str, Any] | None = None, include_evidence_text=True) -> dict:
    """Return candidates and actionable missing reasons, accounting for every row.

    Coverage declarations describe what was supplied, not scientific review or
    guaranteed recall. No automatic search outcome uses `not_reported`.
    """
    from services import material_classification_candidates as classification

    if len(materials) > MAX_MATERIALS or len(sources) > MAX_SOURCES:
        raise EnrichmentError("enrichment_inventory_limit")
    paper_sources = defaultdict(list)
    validated = [validate_source(source) for source in sources]
    if len({source["id"] for source in validated}) != len(validated):
        raise EnrichmentError("duplicate_source_capture")
    for source in validated:
        paper_sources[source["paper_id"]].append(source)
    all_candidates, coverage_rows = {}, []
    all_classifications, all_findings = {}, {}
    classification_total, classification_omitted = 0, 0
    classification_findings_total, classification_findings_omitted = 0, 0
    if len({m.get("id") for m in materials}) != len(materials):
        raise EnrichmentError("duplicate_material")
    for material in materials:
        if not _identifier(material.get("id"), 100) or not _identifier(material.get("formula"), 500):
            raise EnrichmentError("material_identity_required")
        records = material.get("records", [])
        if type(records) is not list or len(records) > 5000 or any(not isinstance(r, Mapping) for r in records):
            raise EnrichmentError("retained_records_invalid")
        material_candidates, material_classifications, material_findings = {}, [], {}
        retained_papers = sorted({r["paper_id"] for r in records if _identifier(r.get("paper_id"), 100)})
        for record in records:
            record_sources = paper_sources.get(record.get("paper_id"), [])
            subject_bindings = classification.discover_subject_bindings(material, record, record_sources)
            identity_candidates = discover_identity_candidates(material, record, record_sources)
            for identity in identity_candidates:
                material_candidates[identity["candidate_id"]] = identity
            aliases = {identity["raw_value"]["source_formula"]: identity for identity in identity_candidates if identity["field"] == "composition_identity"}
            for source in record_sources:
                statements = classification.extract_classification_candidates(material, record, source, include_evidence_text=include_evidence_text, subject_bindings=subject_bindings)
                if len(material_classifications)+len(statements["candidates"]) > classification.MAX_REPORT_ROWS:
                    raise EnrichmentError("classification_report_row_limit")
                material_classifications.extend(statements["candidates"])
                classification_total += statements["counts"]["candidate_statements_total"]
                classification_omitted += statements["counts"]["candidate_statements_omitted"]
                classification_findings_total += statements["counts"]["review_findings_total"]
                classification_findings_omitted += statements["counts"]["review_findings_omitted"]
                for finding in statements["review_findings"]:
                    material_findings[digest(finding)] = finding
                    if len(material_findings) > classification.MAX_REPORT_ROWS:
                        raise EnrichmentError("classification_report_row_limit")
                candidates = extract_table_candidates(material, record, source) if source.get("table") is not None else extract_source_candidates(material, record, source)
                candidates.extend(extract_retained_quantity_matches(material, record, source))
                for alias, identity in aliases.items():
                    proxy = {**material, "formula": alias}
                    alias_candidates = extract_table_candidates(proxy, record, source) if source.get("table") is not None else extract_source_candidates(proxy, record, source)
                    for candidate in alias_candidates:
                        candidate["subject"].update(formula=material["formula"], source_formula=alias,
                                                    identity_basis="nominal_refined_composition_proposal")
                        candidate["identity_candidate"] = {"candidate_id": identity["candidate_id"],
                                                           "source": identity["source"], "association_reviewed": False}
                        candidate["reason_codes"] = sorted(set(candidate["reason_codes"]) | {"nominal_refined_composition_binding_requires_review"})
                        candidate["candidate_id"] = "enrichment:" + digest({k: v for k, v in candidate.items() if k not in {"candidate_id", "evidence_text"}})
                    candidates.extend(alias_candidates)
                for candidate in candidates:
                    material_candidates[candidate["candidate_id"]] = candidate
        material_candidates = {candidate["candidate_id"]: candidate for candidate in _deduplicate_source_facts(material_candidates.values())}
        material_classifications = classification.deduplicate_candidates(material_classifications)
        if len(all_classifications) + len(material_classifications) > classification.MAX_REPORT_ROWS or len(all_findings) + len(material_findings) > classification.MAX_REPORT_ROWS:
            raise EnrichmentError("classification_report_row_limit")
        all_classifications.update({row["candidate_id"]: row for row in material_classifications})
        all_findings.update(material_findings)
        if len(all_candidates) + len(material_candidates) > MAX_CANDIDATES:
            raise EnrichmentError("enrichment_candidate_limit")
        all_candidates.update(material_candidates)
        local_sources = [s for paper in retained_papers for s in paper_sources.get(paper, [])]
        declared_coverage = {paper: (source_coverage or {}).get(paper, {}) for paper in retained_papers}
        fields = []
        for field, routes in FIELD_ROUTES.items():
            count = sum(candidate["field"] == field for candidate in material_candidates.values())
            count += sum(candidate["field"] == field for candidate in material_classifications)
            findings_count = sum(field in finding["fields"] for finding in material_findings.values())
            present = any(_present(record, field) for record in records)
            reasons = []
            if present:
                status = "retained_present"
                reasons.append("retained_value_source_location_and_state_may_require_review")
            elif count:
                status = "pending_review"
                reasons.append("source_candidates_available")
            elif not retained_papers:
                status = "source_unavailable"
                reasons.append("retained_source_identity_missing")
            elif not local_sources:
                status = "not_extracted"
                reasons.append("original_source_capture_not_supplied")
                if field in REFERENCE_ONLY_FIELDS:
                    reasons.append("external_reference_route_is_not_a_lookup_hit")
            else:
                status = "not_found_in_checked_sources"
                reasons.append("bounded_extractor_did_not_find_local_candidate")
                if field in LITERAL_SOURCE_FIELDS:
                    reasons.append("bounded_source_value_grammar_has_incomplete_recall")
                if field in SPECIALIST_EXTRACTION_FIELDS:
                    reasons.append("bounded_specialist_grammar_has_incomplete_recall")
                    if findings_count:
                        status = "not_extracted"
                        reasons.append("source_assertion_subject_or_scope_requires_review")
                if any(not declared_coverage[paper].get("fulltext_checked", False) for paper in retained_papers):
                    reasons.append("fulltext_coverage_incomplete")
                if any(not declared_coverage[paper].get("supplement_checked", False) for paper in retained_papers):
                    reasons.append("supplement_coverage_incomplete")
            fields.append({"field": field, "status": status, "retained_present": present,
                           "candidate_count": count, "reason_codes": reasons, "routes": routes,
                           **({"classification_review_finding_count": findings_count} if field in SPECIALIST_EXTRACTION_FIELDS else {})})
        coverage_rows.append({"material_id": material["id"], "formula": material["formula"],
                              "retained_record_count": len(records), "retained_paper_ids": retained_papers,
                              "source_capture_count": len(local_sources), "source_coverage": declared_coverage,
                              "fields": fields})
    candidates = [all_candidates[key] for key in sorted(all_candidates)]
    # Compute identity before optional private-context redaction.
    if not include_evidence_text:
        candidates = [{key: value for key, value in candidate.items() if key != "evidence_text"} for candidate in candidates]
    counts = Counter(candidate["field"] for candidate in candidates)
    result = {"version": VERSION, "extractor_version": EXTRACTOR_VERSION,
              "input_sha256": digest({"materials": list(materials), "sources": validated,
                                      "source_coverage": source_coverage or {}}),
              "candidates": candidates, "coverage": coverage_rows,
              "classification_candidates": [all_classifications[key] for key in sorted(all_classifications)],
              "classification_review_findings": [all_findings[key] for key in sorted(all_findings)],
              "classification_version": classification.VERSION,
              "classification_extractor_version": classification.EXTRACTOR_VERSION,
              "classification_counts": {"source_record_statement_matches": classification_total,
                  "candidate_facts": len(all_classifications), "source_record_matches_omitted": classification_omitted,
                  "source_record_matches_truncated": classification_omitted > 0,
                  "review_findings": len(all_findings), "report_row_limit": classification.MAX_REPORT_ROWS,
                  "source_record_review_findings_total": classification_findings_total,
                  "source_record_review_findings_omitted": classification_findings_omitted,
                  "source_record_review_findings_truncated": classification_findings_omitted > 0,
                  "candidate_fields": dict(sorted(Counter(row["field"] for row in all_classifications.values()).items())),
                  "promoted_facts": 0},
              "counts": {"materials": len(materials), "retained_records": sum(len(m.get("records", [])) for m in materials),
                         "source_captures": len(validated), "candidate_facts": len(candidates),
                         "candidate_retained_references": sum(candidate["retained_reference_count"] for candidate in candidates),
                         "candidate_fields": dict(sorted(counts.items())), "promoted_facts": 0},
              "limitations": ["literal_matches_are_not_source_review", "bounded_grammar_has_incomplete_recall",
                              "pressure_missing_is_not_ambient", "text_structure_does_not_assert_coordinates",
                              "external_formula_match_is_not_state_association"], **AUTHORITY}
    result["report_sha256"] = digest(result)
    return result


def validate_candidate_identity(candidate: dict) -> None:
    if type(candidate) is not dict or candidate.get("version") != VERSION:
        raise EnrichmentError("enrichment_candidate_version")
    if any(candidate.get(key) is not False for key in AUTHORITY):
        raise EnrichmentError("candidate_cannot_grant_authority")
    if candidate.get("disposition") != "pending" or candidate.get("source_content_checked") is not False or candidate.get("material_state_reviewed") is not False:
        raise EnrichmentError("candidate_cannot_claim_review")
    if "evidence_text" in candidate and text_digest(candidate["evidence_text"]) != candidate.get("evidence_text_sha256"):
        raise EnrichmentError("candidate_evidence_text_changed")
    expected = "enrichment:" + digest({key: value for key, value in candidate.items() if key not in {"candidate_id", "evidence_text"}})
    if candidate.get("candidate_id") != expected:
        raise EnrichmentError("enrichment_candidate_changed")


def pending_tc_records(candidates: Sequence[dict]) -> list[dict]:
    """Review handoff records compatible with existing typed-claim mapper.

    Never an insert payload. Candidates remain additive pending records, and
    no original retained value or structure is changed. Different Tc criteria
    have separate records. The importing reviewer must verify source hashes
    and current lifecycle, then use the existing ingestion/claim review path.
    """
    records = []
    for candidate in candidates:
        validate_candidate_identity(candidate)
        if candidate["field"] != "tc_kelvin" or not candidate.get("quantity") or candidate["quantity"]["status"] != "parsed":
            continue
        subject, source = candidate["subject"], candidate["source"]
        pressure = subject["pressure_quantity"]
        record = {"formula_raw": subject["formula"], "paper_id": source["paper_id"],
                  "tc_kelvin": candidate["raw_value"], "tc_criterion": subject.get("tc_criterion", "unknown"),
                  "tc_definition": subject.get("tc_criterion", "unknown"),
                  "knowledge_origin": subject["knowledge_origin"], "measurement_method": subject["measurement_method"],
                  "calculation_method": subject.get("calculation_method"),
                  "pressure_state": subject["pressure_state"], "validity_status": "pending",
                  "source_locator": {**source["locator"], "char_start": source["span"]["char_start"], "char_end": source["span"]["char_end"]},
                  "enrichment_candidate_id": candidate["candidate_id"],
                  "enrichment_provenance": {"version": VERSION, "retained_result_id": candidate["retained_result_id"],
                      "retained_record_sha256": candidate["retained_record_sha256"], "source": source,
                      "retained_result_refs": candidate.get("retained_result_refs", []),
                      "source_content_checked": False, "material_state_reviewed": False}}
        if pressure is not None and subject["pressure_state"] in {"reported", "explicit_ambient"}:
            record["pressure_gpa"] = pressure["raw_value"] + " " + (pressure.get("raw_unit") or pressure["unit"])
        if subject["pressure_state"] == "explicit_ambient":
            record["pressure_type"] = "ambient"
        for key in ("sample_label", "state_label", "phase_label", "run_label"):
            if key in subject:
                record[key] = subject[key]
        records.append({"material_id": candidate["material_id"], "record": record,
                        "import_status": "requires_source_and_state_review", **AUTHORITY})
    return records
