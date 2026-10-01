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
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from services.claim_support import is_derived_source_hint
from services.property_evidence import legacy_result_id
from services.scientific_values import FIELD_UNITS, parse_scientific_value, record_quantity

VERSION = "materials-enrichment/1.0.0"
EXTRACTOR_VERSION = "materials-literal-extractor/1.0.0"
MAX_MATERIALS = 1000
MAX_SOURCES = 10000
MAX_SOURCE_CHARS = 200000
MAX_CANDIDATES = 20000
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
_METHODS = {
    "resistivity": re.compile(r"\bresistiv|\bresistance|four[ -]probe", re.I),
    "susceptibility": re.compile(r"\bsusceptibility\b", re.I),
    "specific_heat": re.compile(r"\b(?:specific heat|heat capacity)\b", re.I),
    "x_ray_diffraction": re.compile(r"\bx.ray.diffraction\b|\bXRD\b", re.I),
    "eliashberg": re.compile(r"\bEliashberg\b", re.I),
    "allen_dynes": re.compile(r"\bAllen[ -]Dynes\b", re.I),
    "dft": re.compile(r"\bDFT\b|\bdensity.functional\b|\bfirst.principles\b", re.I),
}
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
    "tc_criterion": ["source_fulltext_and_supplement"],
    "measurement_method": ["source_fulltext_and_supplement"],
    "sample_form": ["source_fulltext_and_supplement"],
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
    "competing_order": ["source_fulltext_and_supplement", "specialist_experiment"],
    "lambda_eph": ["source_fulltext_and_supplement", "nomad_state_matched_calculation", "new_electron_phonon_calculation"],
    "omega_log_source_value": ["source_fulltext_and_supplement", "nomad_state_matched_calculation", "new_electron_phonon_calculation"],
    "mu_star": ["source_fulltext_and_supplement", "new_calculation_declared_assumption"],
    "hc2_tesla": ["source_fulltext_and_supplement", "new_experiment_or_model_estimate"],
    "lambda_london_nm": ["source_fulltext_and_supplement", "new_experiment_or_model_estimate"],
    "xi_gl_nm": ["source_fulltext_and_supplement", "new_experiment_or_model_estimate"],
}
# These routes require a specialist extraction workflow. The literal parser
# does not infer mechanism or order from family, keywords, or their negation.
SPECIALIST_EXTRACTION_FIELDS = frozenset({"pairing_symmetry", "competing_order"})


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


def _direct_quantity_binding(text, anchor, quantity):
    if anchor.end() > quantity.start():
        return False
    gap = text[anchor.end():quantity.start()]
    return len(gap) <= 45 and re.fullmatch(r"(?:[\s=():,]|\b(?:temperature|is|was|of|at|a|an|the|by|up|to|below|above|reaches|reached|approximately|around|about|as|high)\b)*", gap, re.I) is not None


def _context(text: str) -> dict[str, Any]:
    pressures = [_quantity(match[1], "pressure_gpa", match[2]) for match in _PRESSURE.finditer(text)]
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
    return {"pressure_state": state, "pressure_quantity": pressure,
            "knowledge_origin": "Computed" if computed and not observed else "Observed" if observed and not computed else "Unknown",
            "measurement_method": _label(text, _METHODS), **labels}


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
                    {**context, "tc_criterion": "unknown", "respective_alignment": target_index},
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
            local = {**context, "tc_criterion": criterion}
            add("tc_kelvin", match.group(), match, quantity, local)
            if criterion != "unknown":
                add("tc_criterion", criterion, anchor, local_context=local)
        pressure_matches = list(_PRESSURE.finditer(flat))
        for match in pressure_matches:
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
                unit = match[2]
                if FIELD_UNITS[field] != "1" and not unit:
                    continue
                add(field, match.group(), match, _quantity(match[1], field, unit))
        if context["measurement_method"]:
            add("measurement_method", context["measurement_method"])
        form = re.search(r"\b(single[ -]crystals?|thin[ -]films?|polycrystalline|bulk)\b", flat, re.I)
        if form:
            value = "single_crystal" if "single" in form.group().lower() else "thin_film" if "film" in form.group().lower() else "polycrystal" if "poly" in form.group().lower() else "bulk"
            add("sample_form", value, form)
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
            context = {**_context(flat), "tc_criterion": criterion}
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
    aliases = {"tc_criterion": ("tc_criterion", "tc_definition", "tc_type"),
               "measurement_method": ("measurement_method", "measurement", "method", "calculation_method")}
    return any(raw.get(key) is not None and str(raw[key]).strip().lower() not in {"", "unknown", "none", "n/a", "not_reported"}
               for key in aliases.get(field, (field,)))


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
    if len(materials) > MAX_MATERIALS or len(sources) > MAX_SOURCES:
        raise EnrichmentError("enrichment_inventory_limit")
    paper_sources = defaultdict(list)
    validated = [validate_source(source) for source in sources]
    if len({source["id"] for source in validated}) != len(validated):
        raise EnrichmentError("duplicate_source_capture")
    for source in validated:
        paper_sources[source["paper_id"]].append(source)
    all_candidates, coverage_rows = {}, []
    if len({m.get("id") for m in materials}) != len(materials):
        raise EnrichmentError("duplicate_material")
    for material in materials:
        if not _identifier(material.get("id"), 100) or not _identifier(material.get("formula"), 500):
            raise EnrichmentError("material_identity_required")
        records = material.get("records", [])
        if type(records) is not list or len(records) > 5000 or any(not isinstance(r, Mapping) for r in records):
            raise EnrichmentError("retained_records_invalid")
        material_candidates = {}
        retained_papers = sorted({r["paper_id"] for r in records if _identifier(r.get("paper_id"), 100)})
        for record in records:
            record_sources = paper_sources.get(record.get("paper_id"), [])
            identity_candidates = discover_identity_candidates(material, record, record_sources)
            for identity in identity_candidates:
                material_candidates[identity["candidate_id"]] = identity
            aliases = {identity["raw_value"]["source_formula"]: identity for identity in identity_candidates if identity["field"] == "composition_identity"}
            for source in record_sources:
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
        if len(all_candidates) + len(material_candidates) > MAX_CANDIDATES:
            raise EnrichmentError("enrichment_candidate_limit")
        all_candidates.update(material_candidates)
        local_sources = [s for paper in retained_papers for s in paper_sources.get(paper, [])]
        declared_coverage = {paper: (source_coverage or {}).get(paper, {}) for paper in retained_papers}
        fields = []
        for field, routes in FIELD_ROUTES.items():
            count = sum(candidate["field"] == field for candidate in material_candidates.values())
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
            elif field in SPECIALIST_EXTRACTION_FIELDS:
                status = "specialist_extraction_needed"
                reasons.append("specialist_extractor_not_implemented")
                if not local_sources:
                    reasons.append("original_source_capture_not_supplied")
            elif not local_sources:
                status = "not_extracted"
                reasons.append("original_source_capture_not_supplied")
            else:
                status = "not_found_in_checked_sources"
                reasons.append("bounded_extractor_did_not_find_local_candidate")
                if any(not declared_coverage[paper].get("fulltext_checked", False) for paper in retained_papers):
                    reasons.append("fulltext_coverage_incomplete")
                if any(not declared_coverage[paper].get("supplement_checked", False) for paper in retained_papers):
                    reasons.append("supplement_coverage_incomplete")
            fields.append({"field": field, "status": status, "retained_present": present,
                           "candidate_count": count, "reason_codes": reasons, "routes": routes})
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
                  "knowledge_origin": subject["knowledge_origin"], "measurement_method": subject["measurement_method"],
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
