"""Bounded source-statement candidates, never material classifications.

The grammar deliberately favours precision over recall. Each admitted statement
names one fixed composition locally, or uses a uniquely resolved local variable
formula. Neighbouring compositions, comparisons and cited assertions require
review instead of supplying a property. Missing context is not manufactured.
"""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from services._composition.formula_enrichment import enrich_formula
from services.material_enrichment import (
    _DIRECTIVE,
    AUTHORITY,
    SOURCE_KINDS,
    EnrichmentError,
    _flat,
    _formula_pattern,
    _identifier,
    canonical,
    digest,
    text_digest,
    validate_source,
)
from services.material_external_references import external_query_formula
from services.property_evidence import legacy_result_id
from services.scientific_values import parse_scientific_value

VERSION = "material-classification-candidates/1.0.0"
EXTRACTOR_VERSION = "materials-source-statement-extractor/1.0.0"
FIELDS = frozenset({"pairing_symmetry", "is_unconventional", "reported_order", "competing_order", "gap_structure"})
MAX_SEGMENT_CHARS = 1800
MAX_CANDIDATES_PER_SOURCE = 100
MAX_FINDINGS_PER_SOURCE = 100
MAX_REPORT_ROWS = 20000
STANCES = frozenset({"reported", "fitted", "proposed", "not_detected"})
_ELEMENT_TOKEN = r"[A-Z][a-z]?\s*(?:(?:\d+(?:\.\d+)?\s*(?:-\s*x)?|x)\s*)?"
_CHEMICAL = re.compile(rf"(?<![A-Za-z0-9])(?:{_ELEMENT_TOKEN}|\(\s*(?:{_ELEMENT_TOKEN}){{2,}}\)\s*\d*\s*){{2,}}(?![A-Za-z0-9])")
_X = re.compile(r"(?<!\w)x\s*=\s*(0?\.\d+|0|1)(?!\w|\.\d|\(\d)")
_COMPLEX_X = re.compile(r"(?<!\w)x\s*=\s*[0-9.]+\s*(?:±|\+/-|to|and|or|[,/]|-(?=\s*\d))\s*[0-9.]", re.I)
_PAIR = re.compile(r"\b(odd[ -]parity|even[ -]parity|[sdpf][ -]wave|s[ _]pm|s±)\s+(?:pairing(?: symmetry)?|symmetry|superconduct(?:or|ivity|ing state)|gap(?: model| structure)?)\b", re.I)
_CLASS = re.compile(r"\b(unconventional|non[ -]BCS|conventional)\s+(?:SC state|superconduct(?:ivity|or|ing (?:state|pairing)))\b", re.I)
_GAP = re.compile(r"\b(nodeless|nodal|fully[ -]gapped|full[ -]gap|double nodeless|single nodeless)\s+(?:superconducting\s+)?(?:gap(?: structure)?|electron pairing)\b", re.I)
_ORDER = re.compile(r"\b(charge[ -]density[ -]wave|charge order|CDW|antiferromagnet(?:ism|ic order)|AFM|spin[ -]density[ -]wave|SDW|pair[ -]density[ -]wave|PDW|Mott[ -]insulator)\b", re.I)
_ORDER_NAMES = {"charge order": "CDW", "cdw": "CDW", "afm": "AFM", "sdw": "SDW", "pdw": "PDW"}
_CITED = re.compile(r"\b(?:previous|earlier|prior|cited|according to|reported by|et al|Ref\.?|references?)\b|\[\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]", re.I)
_COMPARE = re.compile(r"\b(?:whereas|unlike|compared (?:to|with)|in contrast|comparison|control (?:sample|material)|parent compound)\b", re.I)
_PROPOSE = re.compile(r"\b(?:propos\w*|suggest\w*|possibly|possible|may|might|could|assuming|most likely|consistent with|points? to)\b", re.I)
_FIT = re.compile(r"\b(?:fit|fits|fitted|fitting|modelled|modeled|modelling|modeling)\b", re.I)
_NEGATIVE = re.compile(r"\b(?:no (?:evidence|indication|sign|AFM|CDW|SDW|PDW|antiferromagnetic|charge order)|not (?:observed|detected|found)|absence of|absent)\b", re.I)
_NEGATION = re.compile(r"\b(?:no|not|without|neither|never|cannot)\b", re.I)
_CONTRAST = re.compile(r"\b(?:but|however|whereas|while|yet)\b", re.I)
_ORDER_EVOLUTION = re.compile(r"\b(?:suppress\w*|vanish\w*|eliminat\w*|disappear\w*|decreas\w*|reduc\w*)\b", re.I)
_REJECTED_HYPOTHESIS = re.compile(r"\b(?:rule[sd]?\s+out|ruling\s+out|exclud\w*|disfavor\w*|disfavour\w*|inconsistent with|incompatible with|evidence against)\b", re.I)
_SINGLE_ELEMENT = r"[A-Z][a-z]?(?:\d+(?:\.\d+)?)?(?![A-Za-z0-9(+\-]|\.\d)"
_ELEMENT_SUBJECT = re.compile(rf"\b({_SINGLE_ELEMENT})\s+(?:-based\s+)?(?:substrate|sample|control|compound|superconductor|deposit\w*)\b|\b(?:and|or|on|in|from|substrate|sample|superconductor)\s+({_SINGLE_ELEMENT})\b")
_REPORT = re.compile(r"\b(?:report\w*|observ\w*|detect\w*|show\w*|find|found|has|exhibits?|is|are|occurs?|onsets?)\b", re.I)
_UNCERTAIN = re.compile(r"\b(?:whether|if|undetermined|unresolved|unclear|unknown)\b", re.I)
_METHODS = {
    "point_contact_spectroscopy": r"(?:soft\s+)?point[ -]contact (?:spectroscopy|spectra|technique)",
    "musr": r"(?:muon[ -]spin (?:rotation|relaxation)(?:/relaxation)?|[μµ]SR|muSR)",
    "arpes": r"(?:ARPES|angle[ -]resolved photoemission spectroscopy)",
    "stm": r"(?:STM|scanning tunnelling microscopy|scanning tunneling microscopy)",
    "resistivity": r"(?:resistivity|four[ -]probe(?: AC)?(?: method)?)",
    "susceptibility": r"(?:(?:AC|magnetic) susceptibility|susceptibility)",
    "neutron_diffraction": r"neutron diffraction",
    "nmr": r"(?:NMR|nuclear magnetic resonance)",
    "specific_heat": r"(?:specific heat|heat capacity)",
}
_QUANTITY = r"(?:[<>≤≥~≈]\s*)?\d+(?:\.\d+)?(?:\s*(?:±|to|–)\s*\d+(?:\.\d+)?)?"
_CONDITIONS = {
    "pressure": (re.compile(rf"({_QUANTITY})\s*(GPa|MPa|kPa|kbar|bar|Pa|atm)\b"), "pressure_gpa"),
    "temperature": (re.compile(rf"({_QUANTITY})\s*(mK|K|kelvin)\b"), "temperature_k"),
    "magnetic_field": (re.compile(rf"({_QUANTITY})\s*(mT|T|Oe|kOe)\b"), "magnetic_field_t"),
}


def _key(formula):
    parsed = enrich_formula(formula)
    return parsed["element_amounts"] if parsed["composition_status"] == "exact" else None


def _classification_segments(text):
    # Semicolons keep their neighbouring clauses together for stance/subject
    # review. The older numeric extractor's segmentation remains unchanged.
    start = 0
    for match in re.finditer(r"[\n]+|(?<=[.!?])\s+(?=[A-Z])", text):
        if text[start:match.start()].strip():
            yield start, match.start(), text[start:match.start()]
        start = match.end()
    if text[start:].strip():
        yield start, len(text), text[start:]


def _mentions(text):
    return [(match, re.sub(r"\s", "", match.group())) for match in _CHEMICAL.finditer(text)
            if ("x" in match.group() or enrich_formula(re.sub(r"\s", "", match.group()))["composition_status"] in {"exact", "variable"})
            and re.sub(r"\s", "", match.group()) not in {"SC", "II", "III", "IV", "VI"}]


def _foreign_element_subject(text, target):
    return any((key := _key(match[1] or match[2])) is not None and key != target
               for match in _ELEMENT_SUBJECT.finditer(text))


def _binding(text, formula):
    """Resolve only a locally explicit x; never use the retained doping value."""
    assignments = list(_X.finditer(text))
    values = {Decimal(match[1]) for match in assignments}
    target = _key(formula)
    matches = list(re.finditer(_formula_pattern(formula), text))
    if _COMPLEX_X.search(text):
        return None, "local_doping_expression_requires_review"
    if len(values) > 1:
        return None, "multiple_local_doping_assignments"
    mentions = _mentions(text)
    if _foreign_element_subject(text, target):
        return None, "single_element_subject_requires_review"
    resolved = []
    for match, raw in mentions:
        current = raw
        if "x" in raw:
            if len(values) != 1:
                return None, "variable_subject_requires_local_assignment"
            x = next(iter(values))
            current = current.replace("1-x", format(1-x, "f")).replace("x", format(x, "f"))
        key = _key(current)
        if key != target:
            return None, "multiple_or_nonmatching_material_subjects"
        resolved.append((match, raw))
    # A comparator with a one-element formula needs an explicit material cue.
    if re.search(r"\b(?:superconductor|sample|control)\s+[A-Z][a-z]?\b", text) and _COMPARE.search(text):
        return None, "comparison_subject_requires_review"
    if matches:
        match = matches[0]
        return {"formula_raw": match.group(), "identity_basis": "exact_formula_local",
                "start": match.start(), "end": match.end(),
                "doping_assignment_raw": assignments[0].group() if assignments else None}, None
    if resolved:
        match, raw = resolved[0]
        variable = "x" in raw
        return {"formula_raw": raw, "identity_basis": "local_variable_formula_and_explicit_assignment" if variable else "exact_composition_local",
                "start": match.start(), "end": match.end(),
                "doping_assignment_raw": assignments[0].group() if variable else None}, None
    return None, "material_identifier_not_local"


def _conditions(text):
    mentions = []
    for kind, (pattern, field) in _CONDITIONS.items():
        for match in pattern.finditer(text):
            if len(mentions) == 12:
                break
            quantity = parse_scientific_value(match[1], field, raw_unit=match[2])
            mentions.append({"kind": kind, "raw_value": match[1], "raw_unit": match[2],
                             "quantity": quantity, "association_status": "local_mention_requires_binding_review"})
    return {"mentions": mentions, "pressure_status": "explicit_ambient_statement" if re.search(r"\bambient pressure\b", text, re.I) else "mentions_require_review" if any(x["kind"] == "pressure" for x in mentions) else "not_supplied_in_local_statement",
            "measurement_window_verified": False}


def _source(source, start, end):
    url = source.get("source_url")
    parsed = urlparse(url) if isinstance(url, str) and len(url) <= 500 else None
    url = url if parsed and parsed.scheme == "https" and parsed.hostname in {"arxiv.org", "journals.aps.org", "link.aps.org", "doi.org"} and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and not any(ord(c) < 32 for c in url) else None
    basis = source.get("source_revision_basis", "source_asserted_publication_revision")
    if basis not in {"source_asserted_publication_revision", "retained_content_hash", "retained_content_capture", "captured_primary_html_bytes", "captured_source_bytes", "paper_inventory_capture_not_publication_version"}:
        basis = "unresolved_capture_revision_basis"
    return {"paper_id": source["paper_id"], "capture_id": source["id"], "kind": source["kind"],
            "source_revision": source["source_revision"], "content_sha256": source["content_sha256"],
            "locator": _public_locator(source["locator"], start, end), "span": {"char_start": start, "char_end": end,
                "text_sha256": text_digest(source["text"][start:end])},
            "source_url": url, "source_status": source.get("source_status", "unknown"),
            "source_revision_basis": basis,
            "publication_revision_verified": source.get("publication_revision_verified") is True}


def _public_locator(locator, start, end):
    """Only structural locator tokens may leave the private evidence capture.

    A free-form section title or XML annotation can contain source prose or
    reviewer notes even when the containing key is ostensibly a locator.
    Unknown strings are omitted; the exact capture/span hashes remain usable.
    """
    result = {}
    for key, value in locator.items():
        if type(value) is int and key in {"page", "row", "column", "char_start", "char_end"} and 0 <= value <= 1000000000:
            result[key] = value
        elif type(value) is str:
            if key == "chunk_id" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/\-]{0,199}", value):
                result[key] = value
            elif key in {"table", "figure", "page", "row", "column"} and re.fullmatch(r"(?:(?:Table|Figure|Fig\.)\s*)?[A-Za-z0-9.()\-]{1,30}", value):
                result[key] = value
            elif key == "section" and re.fullmatch(r"(?:(?:\d+(?:\.\d+)*|[IVXLCDM]+)[.)]?\s*)?(?:Abstract|Introduction|Methods|Materials and Methods|Results|Results and Discussion|Discussion|Conclusions?|Summary|Supplementary Information|Synthetic benchmark)", value, re.I):
                result[key] = value
            elif key == "xml_xpath" and (re.fullmatch(r"(?:/[A-Za-z][A-Za-z0-9_\-]*(?:\[\d+\])?){1,15}", value) or re.fullmatch(r"//\*\[@id=(?:'[A-Za-z0-9_.:\-]{1,100}'|\"[A-Za-z0-9_.:\-]{1,100}\")\]", value)):
                result[key] = value
    if not result:
        result = {"char_start": start, "char_end": end}
    return result


def _identity(candidate):
    return "classification:" + digest({key: value for key, value in candidate.items() if key not in {"candidate_id", "evidence_text"}})


def _statement_candidates(text):
    labels = [("pairing_symmetry", m) for m in _PAIR.finditer(text)]
    labels += [("is_unconventional", m) for m in _CLASS.finditer(text)]
    labels += [("gap_structure", m) for m in _GAP.finditer(text)]
    labels += [("reported_order", m) for m in _ORDER.finditer(text)]
    return labels


def _normalized_label(field, raw):
    """Closed grammar labels, not arbitrary source/private narrative strings."""
    patterns = {
        "pairing_symmetry": r"odd[ -]parity|even[ -]parity|[sdpf][ -]wave|s[ _]pm|s±",
        "is_unconventional": r"unconventional|non[ -]BCS|conventional",
        "gap_structure": r"nodeless|nodal|fully[ -]gapped|full[ -]gap|double nodeless|single nodeless",
    }
    if field in {"reported_order", "competing_order"}:
        if type(raw) is not str or not _ORDER.fullmatch(raw):
            return None
        return _ORDER_NAMES.get(raw.lower(), "AFM" if raw.lower().startswith("antiferromagnet") else "CDW" if raw.lower().startswith("charge") else "SDW" if raw.lower().startswith("spin") else "Mott_insulator" if raw.lower().startswith("mott") else "PDW")
    if field not in patterns or type(raw) is not str or not re.fullmatch(patterns[field], raw, re.I):
        return None
    return re.sub(r"[ _]", "-", raw.lower())


def discover_subject_bindings(material, record, sources):
    """Propose explicit source-defined sample aliases, never reviewed identity.

    Generic family formulas without a named local alias are not carried across
    captures: their x/pressure/sample scope could change elsewhere in the paper.
    """
    if external_query_formula(material["formula"], current_records=[dict(record)]) is None:
        return []
    found, definitions = {}, defaultdict(set)
    for source in sources:
        source = validate_source(source)
        if source["paper_id"] != record.get("paper_id"):
            continue
        for left, right, sentence in _classification_segments(source["text"]):
            if len(sentence) > MAX_SEGMENT_CHARS:
                continue
            flat, _ = _flat(sentence)
            flat = flat.replace("−", "-").replace("–", "-")
            if _CITED.search(flat) or _COMPARE.search(flat) or _DIRECTIVE.search(flat):
                continue
            # An inspected reuse with an unresolved assignment blocks the
            # nickname too; dropping that definition would manufacture uniqueness.
            for declared_alias in re.finditer(r"\(\s*(?P<cue>(?:(?:denoted|called|hereafter)\s+)?)\s*(?P<alias>[A-Za-z][A-Za-z0-9._+\- ]{2,44})\s*\)", flat, re.I):
                alias = declared_alias["alias"].strip()
                if not _material_alias(alias, declared_alias["cue"]):
                    continue
                prefix = flat[max(0, declared_alias.start()-120):declared_alias.start()]
                assignment_expression = re.search(r"(?<!\w)x\s*=\s*[^\n;]{1,90}$", prefix)
                if assignment_expression and not _X.fullmatch(assignment_expression.group().strip()):
                    definitions[re.sub(r"\s", "", alias).casefold()].add("ambiguous_definition")
            for assignment in _X.finditer(flat):
                alias_match = re.match(r"\s*\(\s*(?P<cue>(?:(?:denoted|called|hereafter)\s+)?)\s*(?P<alias>[A-Za-z][A-Za-z0-9._+\- ]{2,44})\s*\)", flat[assignment.end():], re.I)
                if not alias_match:
                    continue
                alias = alias_match["alias"].strip()
                # Contextual parentheses ('under pressure', 'single crystal')
                # are not aliases. Unmarked aliases need recognisable compact
                # material/sample naming syntax; an explicit naming cue also
                # supplies a pending, auditable definition.
                if not _material_alias(alias, alias_match["cue"]):
                    continue
                start = assignment.end()+alias_match.start("alias")
                end = assignment.end()+alias_match.end("alias")
                masked = flat[:start]+" "*(end-start)+flat[end:]
                alias_key = re.sub(r"\s", "", alias).casefold()
                assignments = {Decimal(m[1]) for m in _X.finditer(masked)}
                keys = set()
                if len(assignments) == 1:
                    x = next(iter(assignments))
                    for _, raw in _mentions(masked):
                        resolved = raw.replace("1-x", format(1-x, "f")).replace("x", format(x, "f"))
                        key = _key(resolved)
                        keys.add(digest(key) if key is not None else "unresolved")
                if len(keys) != 1:
                    definitions[alias_key].add("ambiguous_definition")
                    continue
                definitions[alias_key].update(keys)
                binding, reason = _binding(masked, material["formula"])
                if reason or not binding:
                    continue
                proposal = {"formula": material["formula"], "alias_raw": alias,
                            "doping_assignment_raw": assignment.group(), "source": _source(source, left, right),
                            "association_reviewed": False, "scope": "source_defined_alias_proposal"}
                proposal["binding_id"] = "classification-subject-binding:"+digest(proposal)
                found[proposal["binding_id"]] = proposal
                if len(found) > 20:
                    raise EnrichmentError("classification_subject_binding_limit")
    return [found[key] for key in sorted(found)
            if len(definitions[re.sub(r"\s", "", found[key]["alias_raw"]).casefold()]) == 1]


def _material_alias(alias, cue):
    compact = re.sub(r"\s", "", alias)
    coded = re.fullmatch(r"[A-Z][A-Za-z0-9]*(?:[._+\-][A-Za-z0-9]+)*", compact) and (any(c.isdigit() for c in alias) or sum(c.isupper() for c in alias) >= 2)
    sample = re.fullmatch(r"(?:Sample|Specimen)\s+[A-Za-z0-9_.+\-]{1,20}", alias, re.I)
    named_identifier = cue and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.+\-]{2,44}", alias)
    return bool(named_identifier or coded or sample)


def _alias_binding(text, formula, paper_id, proposals):
    for proposal in proposals:
        _validate_subject_binding(proposal)
        if proposal["formula"] != formula or proposal["source"]["paper_id"] != paper_id:
            raise EnrichmentError("classification_subject_binding_invalid")
        matches = list(re.finditer(_formula_pattern(re.sub(r"\s", "", proposal["alias_raw"])), text))
        if not matches:
            continue
        assignments = {Decimal(m[1]) for m in _X.finditer(text)}
        declared = {Decimal(m[1]) for m in _X.finditer(proposal["doping_assignment_raw"])}
        if _COMPLEX_X.search(text) or assignments and assignments != declared:
            continue
        masked = list(text)
        for match in matches:
            masked[match.start():match.end()] = " "*(match.end()-match.start())
        if _mentions("".join(masked)) or _foreign_element_subject("".join(masked), _key(formula)):
            continue
        match = matches[0]
        return {"formula_raw": match.group(), "identity_basis": "explicit_source_alias_definition_proposal",
                "start": match.start(), "end": match.end(), "doping_assignment_raw": None,
                "binding_proposal": proposal}, None
    return None, "material_identifier_not_local"


def _relation(text, order):
    # A word 'competition' elsewhere in a multi-order sentence is insufficient.
    label = re.escape(order.group())
    sc = r"(?:superconduct\w*|SC)"
    if re.search(rf"(?:{label}.{{0,45}}compet\w*.{{0,35}}{sc}|{sc}.{{0,45}}compet\w*.{{0,35}}{label})", text, re.I):
        return "competes"
    if re.search(rf"(?:{label}.{{0,45}}coexist\w*.{{0,35}}{sc}|{sc}.{{0,45}}coexist\w*.{{0,35}}{label})", text, re.I):
        return "coexists"
    return None


def _negative_targets(text, labels):
    """Admit only direct non-detection syntax targeting each actual label.

    'No evidence against X', 'no evidence of absence of X', and a negative
    statement about another property cannot establish a non-detection of X.
    Repeated mentions are left for clause-level review rather than merged.
    """
    for _, match in labels:
        label = re.escape(match.group())
        before = text[max(0, match.start()-80):match.start()]
        after = text[match.end():match.end()+80]
        before_patterns = (
            r"\bno\s+(?:(?:evidence|indication|sign)\s+(?:of|for)\s+)?(?:(?:any|a|an|detectable)\s+)?$",
            r"\babsence of\s+(?:(?:a|an|any)\s+)?$",
            r"\bnot\s+(?:observed|detected|found)\s+(?:(?:any|a|an)\s+)?$",
        )
        after_pattern = r"^\s*(?:order\s+)?(?:(?:was|were|is|are|has been)\s+)?(?:not\s+(?:observed|detected|found)|absent)\b"
        if not any(re.search(pattern, before, re.I) for pattern in before_patterns) and not re.search(after_pattern, after, re.I):
            return False
        # A direct grammatical label must still occur in the selected source.
        if not re.search(label, text, re.I):
            return False
    return True


def extract_classification_candidates(material, record, source, *, include_evidence_text=True, subject_bindings=()):
    """Return independent candidates and text-free rejected-statement findings."""
    source = validate_source(source)
    if source["paper_id"] != record.get("paper_id"):
        raise EnrichmentError("retained_source_scope_mismatch")
    formula = external_query_formula(material["formula"], current_records=[dict(record)])
    candidates, findings, total, findings_total = [], [], 0, 0
    for left, right, sentence in _classification_segments(source["text"]):
        flat, offsets = _flat(sentence)
        flat = flat.replace("−", "-").replace("–", "-")
        labels = _statement_candidates(flat)
        if not labels:
            continue
        reason = None
        binding = None
        if len(sentence) > MAX_SEGMENT_CHARS:
            reason = "classification_statement_char_limit"
        elif formula is None:
            reason = "retained_composition_identity_requires_review"
        elif _DIRECTIVE.search(flat):
            reason = "instructional_source_not_scientific_statement"
        elif _CITED.search(flat):
            reason = "cited_or_background_assertion_requires_role_review"
        elif _COMPARE.search(flat):
            reason = "comparison_subject_requires_review"
        elif _UNCERTAIN.search(flat):
            reason = "unresolved_or_conditional_assertion_requires_review"
        elif _REJECTED_HYPOTHESIS.search(flat):
            reason = "rejected_hypothesis_requires_assertion_review"
        else:
            binding, reason = _binding(flat, material["formula"])
            if reason and subject_bindings:
                binding, reason = _alias_binding(flat, material["formula"], source["paper_id"], subject_bindings)
        if not reason and _NEGATION.search(flat) and not _NEGATIVE.search(flat):
            reason = "unresolved_negation_requires_clause_review"
        if not reason and len(list(_NEGATIVE.finditer(flat))) > 1:
            reason = "multiple_or_epistemic_negations_require_clause_review"
        if not reason and _NEGATIVE.search(flat) and _CONTRAST.search(flat):
            reason = "contrasting_detection_stances_require_clause_review"
        if not reason and _NEGATIVE.search(flat) and len(labels) > len({field for field, _ in labels}):
            reason = "repeated_property_with_negation_requires_clause_review"
        if not reason and _NEGATIVE.search(flat) and not _negative_targets(flat, labels):
            reason = "negation_target_requires_clause_review"
        if not reason and sum(x["kind"] == "pressure" for x in _conditions(flat)["mentions"]) > 1:
            reason = "multiple_local_pressure_mentions_require_state_review"
        if not reason and sum(x["kind"] == "temperature" for x in _conditions(flat)["mentions"]) > 1:
            reason = "multiple_local_temperature_mentions_require_state_review"
        if not reason and any(field == "reported_order" for field, _ in labels) and _ORDER_EVOLUTION.search(flat):
            reason = "order_evolution_requires_clause_review"
        if not reason and any(len({m[1].lower() if field != "reported_order" else m.group().lower() for f, m in labels if f == field}) > 1 for field in {f for f, _ in labels}):
            reason = "multiple_property_alternatives_require_review"
        if not reason and not (_REPORT.search(flat) or _FIT.search(flat) or _PROPOSE.search(flat) or _NEGATIVE.search(flat)):
            reason = "assertion_stance_not_resolved"
        if reason:
            findings_total += 1
            if len(findings) < MAX_FINDINGS_PER_SOURCE:
                findings.append({"material_id": material["id"], "fields": sorted({field for field, _ in labels}),
                                 "source": _source(source, left, right), "reason_codes": [reason]})
            continue
        stance = "not_detected" if _NEGATIVE.search(flat) else "fitted" if _FIT.search(flat) else "proposed" if _PROPOSE.search(flat) else "reported"
        methods = [{"name": name, "value_raw": match.group()} for name, pattern in _METHODS.items()
                   if (match := re.search(pattern, flat, re.I))]
        for field, match in labels:
            # Negation or a fit spanning heterogeneous claims needs clause review.
            if len({f for f, _ in labels}) > 1 and stance in {"not_detected", "fitted"}:
                findings_total += 1
                if len(findings) < MAX_FINDINGS_PER_SOURCE:
                    findings.append({"material_id": material["id"], "fields": [field], "source": _source(source, left, right),
                                     "reason_codes": ["mixed_property_stance_requires_clause_review"]})
                continue
            raw = match[1] if field != "reported_order" else match.group()
            normalized = _normalized_label(field, raw)
            relation = _relation(flat, match) if field == "reported_order" else None
            fields = [field, "competing_order"] if relation == "competes" and stance != "not_detected" else [field]
            for out_field in fields:
                total += 1
                if len(candidates) >= MAX_CANDIDATES_PER_SOURCE:
                    continue
                candidate = {"version": VERSION, "extractor_version": EXTRACTOR_VERSION,
                    "material_id": material["id"], "field": out_field,
                    "retained_result_id": legacy_result_id(record, scope_id=material["id"]),
                    "retained_record_sha256": digest(record),
                    "subject": {"formula": material["formula"], "formula_raw": binding["formula_raw"],
                        "identity_basis": binding["identity_basis"], "doping_assignment_raw": binding["doping_assignment_raw"],
                        "sample_label": (sample[1] if (sample := re.search(r"\bsample(?: label)?\s*[:=]\s*([A-Za-z0-9_.+\-]{1,40})\b", flat, re.I)) else None),
                        "association_status": "pending_source_and_state_review",
                        "binding_span": {"char_start": left+offsets[binding["start"]], "char_end": left+offsets[binding["end"]-1]+1},
                        **({"binding_proposal": binding["binding_proposal"]} if "binding_proposal" in binding else {}),
                        "conditions": _conditions(flat), "methods": methods},
                    "claim": {"stance": stance, "normalized_value": normalized, "value_raw": raw,
                        "source_role": "author_report", "scope": "source_statement_only",
                        "relation_to_superconductivity": relation},
                    "source": _source(source, left, right), "evidence_text_sha256": text_digest(sentence),
                    "disposition": "pending", "source_content_checked": False, "material_state_reviewed": False,
                    "reason_codes": ["source_statement_is_not_scientific_acceptance", "material_state_association_requires_review"],
                    "review_requirements": ["exact_source_content_review", "assertion_role_and_stance_review", "material_state_association_review", "method_and_detection_scope_review"],
                    **AUTHORITY}
                if source["kind"] == "legacy_unknown":
                    candidate["reason_codes"].append("legacy_chunk_origin_unresolved")
                if source.get("source_status", "unknown") != "active":
                    candidate["reason_codes"].append("source_lifecycle_requires_review")
                if stance == "not_detected":
                    candidate["reason_codes"].append("scoped_non_detection_is_not_material_level_false")
                    if not methods or not candidate["subject"]["conditions"]["mentions"]:
                        candidate["reason_codes"].append("negative_method_or_tested_window_requires_review")
                if include_evidence_text:
                    candidate["evidence_text"] = sentence
                candidate["candidate_id"] = _identity(candidate)
                candidates.append(candidate)
    return {"version": VERSION, "extractor_version": EXTRACTOR_VERSION, "candidates": candidates,
            "review_findings": findings, "counts": {"candidate_statements_total": total,
                "candidate_statements_returned": len(candidates), "candidate_statements_omitted": total-len(candidates),
                "candidate_statements_truncated": total > len(candidates),
                "review_findings_total": findings_total, "review_findings_returned": len(findings),
                "review_findings_omitted": findings_total-len(findings),
                "review_findings_truncated": findings_total > len(findings)},
            "scope": "local_single_subject_source_statements_incomplete_recall"}


def deduplicate_candidates(candidates):
    groups = defaultdict(list)
    for candidate in candidates:
        basis = {key: value for key, value in candidate.items() if key not in {"candidate_id", "retained_result_id", "retained_record_sha256", "evidence_text"}}
        groups[digest(basis)].append(candidate)
    result = []
    for rows in groups.values():
        candidate = dict(sorted(rows, key=lambda row: row["candidate_id"])[0])
        refs = sorted({(row["retained_result_id"], row["retained_record_sha256"]) for row in rows})
        candidate["retained_result_refs"] = [{"result_id": identifier, "record_sha256": checksum} for identifier, checksum in refs]
        candidate["retained_reference_count"] = len(refs)
        candidate["candidate_id"] = _identity(candidate)
        result.append(candidate)
    return sorted(result, key=lambda row: row["candidate_id"])


def _validate_public_source(source):
    keys = {"paper_id", "capture_id", "kind", "source_revision", "content_sha256", "locator", "span", "source_url", "source_status", "source_revision_basis", "publication_revision_verified"}
    if type(source) is not dict or set(source) != keys:
        raise EnrichmentError("classification_source_shape")
    if any(not _identifier(source[key]) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/\-]{0,199}", source[key]) for key in ("paper_id", "capture_id", "source_revision", "source_revision_basis")) or source["kind"] not in SOURCE_KINDS or source["source_status"] not in {"active", "unknown", "retracted", "corrected", "disputed"} or type(source["publication_revision_verified"]) is not bool:
        raise EnrichmentError("classification_source_metadata_invalid")
    span = source["span"]
    if not re.fullmatch(r"[0-9a-f]{64}", str(source["content_sha256"])) or type(span) is not dict or set(span) != {"char_start", "char_end", "text_sha256"} or not re.fullmatch(r"[0-9a-f]{64}", str(span["text_sha256"])):
        raise EnrichmentError("classification_source_hash_required")
    if type(span["char_start"]) is not int or type(span["char_end"]) is not int or not 0 <= span["char_start"] < span["char_end"] <= 1000000000:
        raise EnrichmentError("classification_source_span_invalid")
    locator = source["locator"]
    if type(locator) is not dict or not locator or locator != _public_locator(locator, span["char_start"], span["char_end"]):
        raise EnrichmentError("classification_public_locator_invalid")
    url = source["source_url"]
    if url is not None:
        parsed = urlparse(url) if type(url) is str and len(url) <= 500 else None
        if not parsed or parsed.scheme != "https" or parsed.hostname not in {"arxiv.org", "journals.aps.org", "link.aps.org", "doi.org"} or parsed.username or parsed.password or parsed.query or parsed.fragment or any(ord(c) < 32 for c in url):
            raise EnrichmentError("classification_public_source_url_invalid")


def _validate_subject_binding(proposal):
    if type(proposal) is not dict or set(proposal) != {"formula", "alias_raw", "doping_assignment_raw", "source", "association_reviewed", "scope", "binding_id"} or proposal.get("association_reviewed") is not False or proposal.get("scope") != "source_defined_alias_proposal" or not _identifier(proposal.get("formula"), 500):
        raise EnrichmentError("classification_subject_binding_invalid")
    _validate_public_source(proposal["source"])
    if type(proposal["alias_raw"]) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._+\- ]{2,44}", proposal["alias_raw"]) or not _material_alias(proposal["alias_raw"], True) or _key(proposal["formula"]) is None or type(proposal["doping_assignment_raw"]) is not str or not _X.fullmatch(proposal["doping_assignment_raw"]):
        raise EnrichmentError("classification_subject_alias_invalid")
    if proposal["binding_id"] != "classification-subject-binding:"+digest({k: v for k, v in proposal.items() if k != "binding_id"}):
        raise EnrichmentError("classification_subject_binding_changed")


def _validate_subject(subject, source):
    keys = {"formula", "formula_raw", "identity_basis", "doping_assignment_raw", "sample_label", "association_status", "binding_span", "conditions", "methods"}
    if type(subject) is not dict or not keys.issubset(subject) or set(subject)-keys-{"binding_proposal"}:
        raise EnrichmentError("classification_subject_shape")
    if not _identifier(subject["formula"], 500) or not _identifier(subject["formula_raw"], 500) or subject["identity_basis"] not in {"exact_formula_local", "exact_composition_local", "local_variable_formula_and_explicit_assignment", "explicit_source_alias_definition_proposal"} or subject["association_status"] != "pending_source_and_state_review":
        raise EnrichmentError("classification_subject_identity_invalid")
    span = subject["binding_span"]
    if type(span) is not dict or set(span) != {"char_start", "char_end"} or type(span["char_start"]) is not int or type(span["char_end"]) is not int or not source["span"]["char_start"] <= span["char_start"] < span["char_end"] <= source["span"]["char_end"]:
        raise EnrichmentError("classification_subject_span_invalid")
    if subject["doping_assignment_raw"] is not None and (type(subject["doping_assignment_raw"]) is not str or not _X.fullmatch(subject["doping_assignment_raw"])):
        raise EnrichmentError("classification_subject_doping_invalid")
    if subject["sample_label"] is not None and (type(subject["sample_label"]) is not str or not re.fullmatch(r"[A-Za-z0-9_.+\-]{1,40}", subject["sample_label"])):
        raise EnrichmentError("classification_sample_label_invalid")
    target = _key(subject["formula"])
    if target is None:
        raise EnrichmentError("classification_subject_composition_invalid")
    if subject["identity_basis"] == "explicit_source_alias_definition_proposal":
        _validate_subject_binding(subject.get("binding_proposal"))
        proposal = subject["binding_proposal"]
        if proposal["formula"] != subject["formula"] or proposal["source"]["paper_id"] != source["paper_id"] or not re.fullmatch(_formula_pattern(re.sub(r"\s", "", proposal["alias_raw"])), subject["formula_raw"]):
            raise EnrichmentError("classification_subject_binding_invalid")
    elif "binding_proposal" in subject:
        raise EnrichmentError("classification_subject_binding_invalid")
    else:
        raw = re.sub(r"\s", "", subject["formula_raw"])
        if subject["identity_basis"] == "local_variable_formula_and_explicit_assignment":
            if not subject["doping_assignment_raw"] or "x" not in raw:
                raise EnrichmentError("classification_subject_doping_invalid")
            x = Decimal(_X.fullmatch(subject["doping_assignment_raw"])[1])
            raw = raw.replace("1-x", format(1-x, "f")).replace("x", format(x, "f"))
        if _key(raw) != target:
            raise EnrichmentError("classification_subject_composition_invalid")
    conditions = subject["conditions"]
    if type(conditions) is not dict or set(conditions) != {"mentions", "pressure_status", "measurement_window_verified"} or conditions["measurement_window_verified"] is not False or conditions["pressure_status"] not in {"explicit_ambient_statement", "mentions_require_review", "not_supplied_in_local_statement"} or type(conditions["mentions"]) is not list or len(conditions["mentions"]) > 12:
        raise EnrichmentError("classification_conditions_invalid")
    for mention in conditions["mentions"]:
        if type(mention) is not dict or set(mention) != {"kind", "raw_value", "raw_unit", "quantity", "association_status"} or mention["kind"] not in _CONDITIONS or mention["association_status"] != "local_mention_requires_binding_review" or type(mention["raw_value"]) is not str or not re.fullmatch(_QUANTITY, mention["raw_value"]) or type(mention["raw_unit"]) is not str:
            raise EnrichmentError("classification_condition_mention_invalid")
        expected = parse_scientific_value(mention["raw_value"], _CONDITIONS[mention["kind"]][1], raw_unit=mention["raw_unit"])
        if not _CONDITIONS[mention["kind"]][0].fullmatch(mention["raw_value"]+" "+mention["raw_unit"]) or mention["quantity"] != expected:
            raise EnrichmentError("classification_condition_quantity_changed")
    if type(subject["methods"]) is not list or len(subject["methods"]) > len(_METHODS):
        raise EnrichmentError("classification_methods_invalid")
    for method in subject["methods"]:
        if type(method) is not dict or set(method) != {"name", "value_raw"} or method["name"] not in _METHODS or type(method["value_raw"]) is not str or not re.fullmatch(_METHODS[method["name"]], method["value_raw"], re.I):
            raise EnrichmentError("classification_method_invalid")


def validate_candidate_identity(candidate: Any):
    if type(candidate) is not dict or candidate.get("version") != VERSION or candidate.get("extractor_version") != EXTRACTOR_VERSION:
        raise EnrichmentError("classification_candidate_version")
    if any(candidate.get(key) is not False for key in AUTHORITY) or candidate.get("disposition") != "pending" or candidate.get("source_content_checked") is not False or candidate.get("material_state_reviewed") is not False:
        raise EnrichmentError("classification_candidate_cannot_grant_authority")
    required = {"version", "extractor_version", "material_id", "field", "retained_result_id", "retained_record_sha256", "subject", "claim", "source", "evidence_text_sha256", "disposition", "source_content_checked", "material_state_reviewed", "reason_codes", "review_requirements", "candidate_id", *AUTHORITY}
    optional = {"evidence_text", "retained_result_refs", "retained_reference_count"}
    if not required.issubset(candidate) or set(candidate)-required-optional:
        raise EnrichmentError("classification_candidate_shape")
    claim = candidate.get("claim")
    if type(claim) is not dict or set(claim) != {"stance", "normalized_value", "value_raw", "source_role", "scope", "relation_to_superconductivity"} or claim.get("stance") not in STANCES or claim.get("source_role") != "author_report" or claim.get("scope") != "source_statement_only" or candidate.get("field") not in FIELDS or type(claim.get("normalized_value")) is not str or claim.get("relation_to_superconductivity") not in {None, "competes", "coexists"}:
        raise EnrichmentError("classification_claim_invalid")
    if any(type(claim.get(key)) is not str or not 0 < len(claim[key]) <= 100 or any(ord(c) < 32 for c in claim[key]) for key in ("normalized_value", "value_raw")):
        raise EnrichmentError("classification_claim_label_invalid")
    if _normalized_label(candidate["field"], claim["value_raw"]) != claim["normalized_value"]:
        raise EnrichmentError("classification_claim_label_invalid")
    if candidate["field"] == "competing_order" and (claim["relation_to_superconductivity"] != "competes" or claim["stance"] == "not_detected"):
        raise EnrichmentError("classification_claim_relation_invalid")
    _validate_public_source(candidate.get("source"))
    _validate_subject(candidate.get("subject"), candidate["source"])
    if not _identifier(candidate["material_id"], 100) or not _identifier(candidate["retained_result_id"]) or not re.fullmatch(r"[0-9a-f]{64}", str(candidate["retained_record_sha256"])) or not re.fullmatch(r"[0-9a-f]{64}", str(candidate["evidence_text_sha256"])):
        raise EnrichmentError("classification_retained_identity_invalid")
    for key in ("reason_codes", "review_requirements"):
        if type(candidate[key]) is not list or not 0 < len(candidate[key]) <= 20 or any(type(v) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", v) for v in candidate[key]):
            raise EnrichmentError("classification_review_metadata_invalid")
    if "retained_result_refs" in candidate:
        refs = candidate["retained_result_refs"]
        if type(refs) is not list or not 0 < len(refs) <= 5000 or type(candidate.get("retained_reference_count")) is not int or candidate["retained_reference_count"] != len(refs):
            raise EnrichmentError("classification_retained_refs_invalid")
        for ref in refs:
            if type(ref) is not dict or set(ref) != {"result_id", "record_sha256"} or not _identifier(ref["result_id"]) or not re.fullmatch(r"[0-9a-f]{64}", str(ref["record_sha256"])):
                raise EnrichmentError("classification_retained_refs_invalid")
    if "evidence_text" in candidate and text_digest(candidate["evidence_text"]) != candidate.get("evidence_text_sha256"):
        raise EnrichmentError("classification_evidence_text_changed")
    if candidate.get("candidate_id") != _identity(candidate):
        raise EnrichmentError("classification_candidate_changed")
    canonical(candidate)
