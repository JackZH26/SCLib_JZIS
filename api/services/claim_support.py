"""Bounded deterministic support checks for narrowly attributable Tc reports.

Supported means a cited original excerpt explicitly contains the same reported
tuple. It is never scientific truth, acceptance, independent replication, or a
general natural-language entailment score. Unknown grammar fails closed.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from services.material_visibility import MATERIAL_VISIBILITY_VERSION
from services.result_semantics import classify_result
from services.scientific_values import parse_scientific_value

SUPPORT_POLICY_VERSION = "scientific-claim-support/1.0.0"
LIMITS = {
    "answer_chars": 12000, "claims": 32, "claim_chars": 800, "sources": 24,
    "source_chars": 6000, "source_sentences": 32, "evidence_per_claim": 3,
    "excerpt_chars": 500,
    "material_evidence": 50,
}
_CITATION = re.compile(r"\[(\d{1,5}(?:\s*,\s*\d{1,5})*)\]")
_SENTENCES = re.compile(r"(?<=[.!?])\s+|[。！？;；\n]+")
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_PREFIX = r"(?:<=|>=|[<>≤≥~≈]|about\s+|approximately\s+|below\s+|above\s+|less than\s+|more than\s+|at least\s+|at most\s+|低于|高于|小于|大于|不超过|不少于|约)?\s*"
_QUANTITY = re.compile(rf"(?<![A-Za-z0-9]){_PREFIX}{_NUMBER}(?:\s*(?:±|\+/-|–|—|-|to)\s*{_NUMBER})?\s*(?:mK|Kelvin|kelvin|K|GPa|MPa|kPa|kbar|Pa|bar|atm)(?![A-Za-z])")
_TC = re.compile(r"(?<![A-Za-z0-9])T_?c(?![A-Za-z0-9])|\b(?:superconducting\s+)?critical temperature\b|\btransition temperature\b|超导临界温度|临界温度", re.I)
_TRANSITION = re.compile(r"\bsuperconducting transition\b|超导转变", re.I)
_AMBIENT = re.compile(r"\b(?:ambient|atmospheric) pressure\b|常压|大气压|环境压力", re.I)
_FORMULA = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?)+(?![A-Za-z0-9])")
_ELEMENTS = frozenset("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split())
_NEGATION = re.compile(r"\b(?:no|not|never|neither|without)\b|未观察到|未观测到|没有|并未|并非|不是|未发现|未见|未出现|不具有|无", re.I)
_ORIGINS = {
    "Observed": re.compile(r"\b(?:observed|measured|experimental|experimentally)\b|实验|测得|观测到|观察到", re.I),
    "Computed": re.compile(r"\b(?:computed|calculated|theoretical|DFT|DFPT)\b|计算|理论", re.I),
    "Inferred": re.compile(r"\binferred\b|推断", re.I),
    "AI-Proposed": re.compile(r"\b(?:AI.proposed|LLM.generated)\b|人工智能提出", re.I),
}
_ROLES = {
    "cited": re.compile(r"\b(?:cited(?: prior)? work|prior work|previous work|earlier work)\b|引用(?:的)?(?:前人)?研究|前人研究", re.I),
    "primary": re.compile(r"\b(?:our (?:own )?(?:result|work|measurement)|this paper.s own result)\b|本研究|本文", re.I),
}
_CRITERIA = {
    "onset": re.compile(r"\bonset\b|起始", re.I),
    "zero_resistance": re.compile(r"\bzero[ -]resistance\b|零电阻", re.I),
    "midpoint": re.compile(r"\bmidpoint\b|中点", re.I),
    "offset": re.compile(r"\boffset\b|终止", re.I),
}
_FORMS = {
    "bulk": re.compile(r"\bbulk\b|块体", re.I),
    "film": re.compile(r"\b(?:thin )?film\b|薄膜", re.I),
    "single_crystal": re.compile(r"\bsingle crystal\b|单晶", re.I),
    "polycrystal": re.compile(r"\bpolycrystal(?:line)?\b|多晶", re.I),
}
_IDENTIFIERS = re.compile(r"\b(sample|state|phase)(?:\s+id)?\s*[:=]?\s+([A-Za-z0-9_.+-]{1,40})\b|(?:样品|状态|相)\s*[:=]?\s*([A-Za-z0-9_.+-]{1,40})", re.I)
_CONNECTOR = re.compile(r"(?:\s|[=:,，()]|\b(?:is|was|of|at|a|an|the|has|had|equal|to)\b|为|是|等于|在|的)*", re.I)
_EN_ALLOWED = frozenset("a an the has have had is was were are of at under with and pressure superconducting transition critical temperature tc showed shows show exhibited exhibits exhibit reported reports report found for in to equal equals does did not no never without it its as according an".split())
_ZH_ALLOWED = re.compile(r"(?:超导|临界|转变|温度|压力|显示|表现|具有|出现|发生|报道|报告|发现|为|是|在|的|和|与|下|有|于|其|等于|表明)")
_UNTRUSTED_DIRECTIVE = re.compile(r"(?:ignore (?:all |previous |prior )?(?:instructions|rules)|(?:system|developer|assistant)\s*:|you must|must (?:say|answer|report)|忽略.{0,12}(?:指令|规则)|必须回答)", re.I)
_NONASSERTIVE = re.compile(r"\b(?:hypothetical|suppose|assuming|assume|illustrative|unverified|example|if|may|might|could|possibly|suggests?|estimated|predicted)\b|假设|示例|假如|如果|可能|未验证|估计|预测", re.I)
_REFUSALS = frozenset({
    "i could not find enough evidence", "i couldn't find enough evidence",
    "i cannot answer from the supplied sources", "i cannot verify this claim",
    "insufficient evidence", "insufficient sources", "not enough evidence",
    "the supplied sources do not establish the requested claim",
    "证据不足", "信息不足", "没有足够证据", "无法根据所提供的来源回答",
})
_SOURCE_CAUTION = re.compile(r"\b(?:retracted|withdrawn|refuted|disputed|not (?:confirmed|established|verified|reproduced)|failed to (?:confirm|reproduce)|correction|erratum)\b|撤稿|撤回|未获证实|未被证实|无法复现|未能复现|存在争议|勘误", re.I)
_Q_FIELDS = ("relation", "value", "lower", "upper", "uncertainty", "uncertainty_interpretation", "approximate", "unit")


@dataclass(frozen=True)
class _Tuple:
    material: str
    quantity: dict
    temperature_role: str
    pressure: dict
    polarity: str
    origin: str
    role: str
    criterion: str
    state: tuple


def _get(source: Any, key: str, default: Any = None) -> Any:
    return source.get(key, default) if isinstance(source, Mapping) else getattr(source, key, default)


def _normal(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("−", "-").replace("T_c", "Tc")


def _segments(text: str) -> list[str]:
    return [part.strip(" \t-*#") for part in _SENTENCES.split(text) if part.strip(" \t-*#")]


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _one_label(text: str, patterns: Mapping[str, re.Pattern]) -> tuple[str, list[tuple[int, int]]]:
    labels, spans = [], []
    for label, pattern in patterns.items():
        matches = list(pattern.finditer(text))
        if matches:
            labels.append(label)
            spans.extend(match.span() for match in matches)
    return labels[0] if len(labels) == 1 else "conflicted" if labels else "unspecified", spans


def _quantity(raw: str, field: str) -> dict | None:
    prefixes = {"below ": "<", "above ": ">", "less than ": "<", "more than ": ">", "at least ": ">=", "at most ": "<=",
                "低于": "<", "高于": ">", "小于": "<", "大于": ">", "不超过": "<=", "不少于": ">=", "约": "~"}
    value = raw.strip()
    for prefix, symbol in prefixes.items():
        if value.lower().startswith(prefix):
            value = symbol + value[len(prefix):]
            break
    proposal = parse_scientific_value(value, field)
    if proposal["status"] != "parsed" or proposal["errors"] or proposal["unit_basis"] != "explicit":
        return None
    return {key: proposal[key] for key in _Q_FIELDS}


def _parse(text: str) -> tuple[_Tuple | None, str]:
    text = _normal(_CITATION.sub("", text)).strip().strip(".*` ")
    if _UNTRUSTED_DIRECTIVE.search(text) or _NONASSERTIVE.search(text):
        return None, "nonassertive_or_instructional_text"
    # A negated condition is not a negated superconducting event. Scope outside
    # this grammar must not be flattened into one sentence-wide polarity flag.
    if re.search(r"\bnot\s+(?:(?:at|under)\s+)?(?:ambient|atmospheric|[\d<>=])|非?常压以外|不是在", text, re.I):
        return None, "negation_scope_undetermined"
    spans: list[tuple[int, int]] = []
    quantities = list(_QUANTITY.finditer(text))
    temperatures, pressures = [], []
    for match in quantities:
        target = temperatures if re.search(r"(?:mK|K|kelvin)$", match.group(), re.I) else pressures
        target.append(match)
        spans.append(match.span())
    if len(temperatures) != 1 or len(pressures) > 1:
        return None, "quantity_binding_undetermined"
    tc = _quantity(temperatures[0].group(), "tc_kelvin")
    if tc is None or any(tc[key] is not None and tc[key] <= 0 for key in ("value", "lower", "upper")):
        return None, "tc_quantity_invalid_or_unsupported"
    ambient = list(_AMBIENT.finditer(text))
    spans.extend(match.span() for match in ambient)
    pressure = _quantity(pressures[0].group(), "pressure_gpa") if pressures else None
    if pressure is None and not ambient:
        return None, "pressure_context_missing_or_unsupported"
    if ambient:
        if pressure is not None and (pressure["relation"] != "exact" or pressure["value"] != 0 or pressure["uncertainty"] is not None or pressure["approximate"]):
            return None, "pressure_assertions_conflict"
        pressure = {"relation": "exact", "value": 0.0, "lower": None, "upper": None,
                    "uncertainty": None, "uncertainty_interpretation": None, "approximate": False, "unit": "GPa", "state": "explicit_ambient"}
    else:
        if pressure["value"] == 0 or any(pressure[key] is not None and pressure[key] < 0 for key in ("value", "lower", "upper")):
            return None, "pressure_convention_undetermined"
        pressure = {**pressure, "state": "reported"}
    # Find chemical tokens only after masking quantities and property names.
    tc_matches = list(_TC.finditer(text))
    property_matches = tc_matches or list(_TRANSITION.finditer(text))
    if len(property_matches) != 1:
        return None, "property_binding_undetermined"
    spans.append(property_matches[0].span())
    formula_text = _mask(text, spans + [match.span() for match in _IDENTIFIERS.finditer(text)])
    formulas = []
    for match in _FORMULA.finditer(formula_text):
        token = match.group()
        elements = re.findall(r"[A-Z][a-z]?", token)
        if elements and all(element in _ELEMENTS for element in elements):
            formulas.append(match)
    if len(formulas) != 1:
        return None, "material_binding_ambiguous_or_missing"
    formula = formulas[0].group()
    spans.append(formulas[0].span())
    # The quantity must bind directly to the property, not to a measurement
    # temperature elsewhere in the same sentence.
    prop = property_matches[0]
    if temperatures[0].start() < prop.end():
        return None, "property_quantity_binding_unsupported"
    between = _mask(text, [formulas[0].span()])[prop.end():temperatures[0].start()]
    if not _CONNECTOR.fullmatch(between):
        return None, "property_quantity_binding_unsupported"
    state = {}
    for match in _IDENTIFIERS.finditer(text):
        kind = match[1].lower() if match[1] else "sample" if "样品" in match.group() else "state" if "状态" in match.group() else "phase"
        value = match[2] or match[3]
        if kind in state and state[kind] != value:
            return None, "multiple_material_states"
        state[kind] = value
        spans.append(match.span())
    labels = []
    for patterns in (_ORIGINS, _ROLES, _CRITERIA, _FORMS):
        label, found = _one_label(text, patterns)
        if label == "conflicted":
            return None, "qualifier_scope_conflict"
        labels.append(label)
        spans.extend(found)
    origin, role, criterion, form = labels
    if form != "unspecified":
        state["form"] = form
    negations = list(_NEGATION.finditer(text))
    if len(negations) > 1:
        return None, "negation_scope_undetermined"
    spans.extend(match.span() for match in negations)
    residual = _mask(text, spans)
    residual = _ZH_ALLOWED.sub(" ", residual)
    words = re.findall(r"[A-Za-z]+", residual)
    if any(word.lower() not in _EN_ALLOWED for word in words):
        return None, "unsupported_claim_grammar"
    residue = re.sub(r"[A-Za-z]+|[\s,，.。:：=()\[\]{}*'’\-]", "", residual)
    if residue:
        return None, "unsupported_claim_grammar"
    temperature_role = ("negated_tc_value" if tc_matches else "transition_test_temperature") if negations else "reported_tc"
    return _Tuple(formula, tc, temperature_role, pressure, "negative" if negations else "positive", origin, role, criterion, tuple(sorted(state.items()))), "tuple_parsed"


def _source_gate(source: Any) -> str | None:
    section = _get(source, "section", "")
    paper = _get(source, "paper_id", "")
    body = _get(source, "text", "")
    if (not isinstance(paper, str) or not 0 < len(paper) <= 200 or not isinstance(body, str)
            or section is not None and (not isinstance(section, str) or len(section) > 200)):
        return "source_metadata_invalid"
    if len(body) > LIMITS["source_chars"]:
        return "source_character_limit"
    if (isinstance(section, str) and re.search(r"\b(?:facts?|derived|generated|summary)\b", re.sub(r"[_-]", " ", section), re.I)
            or re.match(r"(?:facts?|derived|generated):", paper, re.I)
            or re.search(r"^\s*Section:\s*(?:Facts?|Derived)\b", body, re.I | re.M)):
        return "derived_evidence_root_unresolved"
    visibility = _get(source, "source_visibility", {})
    if _get(source, "visibility_resolved", False) is not True or not isinstance(visibility, Mapping):
        return "source_visibility_unresolved"
    if visibility.get("version") != MATERIAL_VISIBILITY_VERSION:
        return "source_visibility_policy_unknown"
    if visibility.get("source_status") != "active" or visibility.get("reported_claim_filter_eligible") is not True:
        return "source_not_eligible_for_report_support"
    warnings = visibility.get("warning_codes")
    if (not isinstance(warnings, list) or len(warnings) > 40
            or any(not isinstance(value, str) or len(value) > 100 for value in warnings)):
        return "source_visibility_metadata_invalid"
    if isinstance(warnings, list) and any(isinstance(value, str) and ("omitted" in value or "restricted" in value) for value in warnings):
        return "restricted_source_occurrences"
    if warnings:
        return "source_visibility_warning_unresolved"
    records = _get(source, "material_evidence", [])
    if not isinstance(records, list):
        return "material_evidence_metadata_invalid"
    if len(records) > LIMITS["material_evidence"]:
        return "material_evidence_count_limit"
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, Mapping):
            return "material_evidence_metadata_invalid"
        if any(isinstance(record.get(key), str) and len(record[key]) > 200 for key in (
            "formula", "knowledge_origin", "result_origin", "evidence_role", "evidence_type",
            "claim_kind", "source_role", "measurement", "measurement_method", "method",
        )):
            return "material_evidence_metadata_invalid"
        envelope = record.get("visibility")
        if isinstance(envelope, Mapping) and envelope.get("reported_claim_filter_eligible") is not True:
            return "material_occurrence_not_eligible"
        kind = record.get("evidence_kind")
        if kind is not None and (not isinstance(kind, str) or len(kind) > 80):
            return "material_evidence_metadata_invalid"
        if record.get("is_derived") is True or kind in {"derived", "fact", "generated"}:
            return "derived_evidence_root_unresolved"
        classification = classify_result(record)
        derived = record.get("result_classification")
        if derived is not None and not isinstance(derived, Mapping):
            return "material_evidence_metadata_invalid"
        if (classification.classification_status == "conflicted" or classification.source_role == "conflicted"
                or isinstance(derived, Mapping) and (derived.get("classification_status") == "conflicted" or derived.get("source_role") == "conflicted")):
            return "material_result_classification_conflict"
        if any(record.get(key) is True for key in ("needs_review", "retracted", "disputed", "corrected")):
            return "material_occurrence_not_eligible"
    if _UNTRUSTED_DIRECTIVE.search(body):
        return "source_contains_instructional_text"
    if _NONASSERTIVE.search(body) or _SOURCE_CAUTION.search(body):
        return "source_context_caution_or_uncertainty"
    return None


def _metadata_conflict(source: Any, parsed: _Tuple) -> bool:
    # Only negative conflict detection uses extraction labels. They never supply
    # a missing quantity, formula, state, origin or source-role assertion.
    for record in _get(source, "material_evidence", []):
        formula = record.get("formula")
        if not isinstance(formula, str) or _normal(formula) != parsed.material:
            continue
        current = classify_result(record)
        derived = record.get("result_classification")
        origins = {current.knowledge_origin}
        roles = {current.source_role}
        if isinstance(derived, Mapping):
            origin, role = derived.get("knowledge_origin"), derived.get("source_role")
            if isinstance(origin, str):
                origins.add(origin)
            if isinstance(role, str):
                roles.add(role)
        origins.discard("Unknown")
        roles.discard("unknown")
        if origins and (parsed.origin == "unspecified" or origins != {parsed.origin}):
            return True
        if roles and (parsed.role == "unspecified" or roles != {parsed.role}):
            return True
    return False


def _compare(claim: _Tuple, source: _Tuple) -> tuple[str, str]:
    for field, reason in (("material", "material_mismatch"), ("state", "material_state_context_mismatch"),
                          ("criterion", "tc_criterion_context_mismatch"), ("origin", "result_origin_context_mismatch"),
                          ("role", "source_role_context_mismatch"), ("pressure", "pressure_condition_mismatch")):
        if getattr(claim, field) != getattr(source, field):
            return "undetermined", reason
    if claim.polarity == source.polarity == "negative" and claim.temperature_role != source.temperature_role:
        return "undetermined", "negative_temperature_semantics_mismatch"
    if claim.quantity == source.quantity:
        return ("supported", "explicit_same_source_tuple_match") if claim.polarity == source.polarity else ("contradicted", "reported_polarity_conflict")
    if claim.polarity != source.polarity:
        return "undetermined", "polarity_and_quantity_differ"
    exact = all(item["relation"] == "exact" and item["uncertainty"] is None and not item["approximate"] for item in (claim.quantity, source.quantity))
    if exact and claim.polarity == "positive":
        return "contradicted", "reported_exact_value_conflict"
    return "undetermined", "quantity_relation_or_uncertainty_not_entailed"


def _is_refusal(sentence: str) -> bool:
    return _normal(sentence).strip(" .。!！").lower() in _REFUSALS


def assess_answer(answer: str, sources: list[object]) -> dict:
    """Assess bounded EN/CJK Tc claims against individually cited source clauses."""
    warnings: set[str] = set()
    truncated = False
    if not isinstance(answer, str):
        answer = ""
        warnings.add("answer_not_text")
    if len(answer) > LIMITS["answer_chars"]:
        truncated = True
        warnings.add("answer_character_limit")
    sentences = [part for part in _segments(answer[:LIMITS["answer_chars"]]) if not _is_refusal(part)]
    total = len(sentences)
    if total > LIMITS["claims"]:
        truncated = True
        warnings.add("claim_count_limit")
    checked_sources = sources if isinstance(sources, list) else []
    source_by_index, duplicate_indices = {}, set()
    for source in checked_sources[:LIMITS["sources"]]:
        index = _get(source, "index")
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= 99999:
            warnings.add("source_index_invalid")
            continue
        if index in source_by_index:
            duplicate_indices.add(index)
        source_by_index[index] = source
    for index in duplicate_indices:
        del source_by_index[index]
    if duplicate_indices:
        warnings.add("source_indices_ambiguous")
    if len(checked_sources) > LIMITS["sources"]:
        truncated = True
        warnings.add("source_count_limit")
    claims = []
    if sentences and checked_sources:
        for ordinal, sentence in enumerate(sentences[:LIMITS["claims"]]):
            refs = sorted({int(value) for match in _CITATION.finditer(sentence) for value in match[1].split(",")})
            reasons: set[str] = set()
            evidence = []
            claim_status = "undetermined"
            if len(sentence) > LIMITS["claim_chars"]:
                truncated = True
                reasons.add("claim_character_limit")
                parsed = None
            else:
                parsed, reason = _parse(sentence)
                if parsed is None:
                    reasons.add(reason)
            if not refs:
                reasons.add("claim_has_no_citation")
            outcomes = []
            if parsed is not None:
                for ref in refs:
                    source = source_by_index.get(ref)
                    if source is None:
                        outcomes.append("undetermined")
                        reasons.add("citation_source_missing_or_ambiguous")
                        continue
                    gate = _source_gate(source)
                    if gate:
                        outcomes.append("undetermined")
                        reasons.add(gate)
                        if gate.endswith("_limit"):
                            truncated = True
                        continue
                    body = _get(source, "text", "")
                    if len(body) > LIMITS["source_chars"]:
                        truncated = True
                        reasons.add("source_character_limit")
                        outcomes.append("undetermined")
                        continue
                    parts = _segments(body)
                    if len(parts) > LIMITS["source_sentences"]:
                        truncated = True
                        reasons.add("source_sentence_limit")
                        outcomes.append("undetermined")
                        continue
                    if any(len(part) > LIMITS["claim_chars"] for part in parts):
                        truncated = True
                        reasons.add("source_clause_character_limit")
                        outcomes.append("undetermined")
                        continue
                    local_outcomes, local_reasons, local_evidence = [], set(), []
                    for part in parts:
                        source_tuple, _ = _parse(part)
                        if source_tuple is None:
                            continue
                        if _metadata_conflict(source, source_tuple):
                            local_reasons.add("excerpt_material_classification_conflict")
                            continue
                        outcome, reason = _compare(parsed, source_tuple)
                        local_outcomes.append(outcome)
                        local_reasons.add(reason)
                        if outcome in {"supported", "contradicted"}:
                            if len(part) > LIMITS["excerpt_chars"]:
                                warnings.add("evidence_excerpt_display_truncated")
                            local_evidence.append({"source_index": ref, "paper_id": _get(source, "paper_id"),
                                                   "excerpt": part if len(part) <= LIMITS["excerpt_chars"] else part[:LIMITS["excerpt_chars"] - 1] + "…"})
                    if "supported" in local_outcomes and "contradicted" not in local_outcomes:
                        outcomes.append("supported")
                    elif "contradicted" in local_outcomes and "supported" not in local_outcomes:
                        outcomes.append("contradicted")
                    else:
                        outcomes.append("undetermined")
                        reasons.add("conflicting_source_assertions" if local_outcomes else "no_self_contained_source_tuple")
                    reasons.update(local_reasons)
                    evidence.extend(local_evidence)
                if outcomes and all(outcome == "supported" for outcome in outcomes):
                    claim_status = "supported"
                elif "contradicted" in outcomes and "supported" not in outcomes:
                    claim_status = "contradicted"
                elif "supported" in outcomes:
                    reasons.add("cited_sources_not_all_support_claim")
            claim = {
                "claim_id": "claim:" + hashlib.sha256(f"{ordinal}|{sentence}".encode()).hexdigest(),
                "text": sentence[:LIMITS["claim_chars"]], "cited_indices": refs,
                "status": claim_status, "reason_codes": sorted(reasons),
                "evidence": evidence[:LIMITS["evidence_per_claim"]],
            }
            if len(evidence) > LIMITS["evidence_per_claim"]:
                warnings.add("claim_evidence_display_truncated")
            if parsed is not None:
                quantity_key = {"reported_tc": "tc_kelvin", "transition_test_temperature": "tested_temperature_k",
                                "negated_tc_value": "negated_tc_value_k"}[parsed.temperature_role]
                claim["quantities"] = {"material": parsed.material, quantity_key: parsed.quantity,
                                       "temperature_role": parsed.temperature_role,
                                       "pressure_gpa": parsed.pressure, "polarity": parsed.polarity}
            claims.append(claim)
    statuses = [claim["status"] for claim in claims]
    if not checked_sources or not sentences:
        status = "not_checked"
        warnings.add("no_sources" if not checked_sources else "no_checkable_assertions")
    elif "contradicted" in statuses:
        status = "contradicted"
    elif statuses and all(value == "supported" for value in statuses) and not truncated:
        status = "supported"
    else:
        status = "undetermined"
    if truncated:
        warnings.add("assessment_coverage_incomplete")
    if any(value == "undetermined" for value in statuses):
        warnings.add("some_claims_undetermined")
    return {
        "policy_version": SUPPORT_POLICY_VERSION, "status": status, "claims": claims,
        "warning_codes": sorted(warnings),
        "coverage": {"total_claims": total, "assessed_claims": len(claims),
                     "supported_claims": statuses.count("supported"), "contradicted_claims": statuses.count("contradicted"),
                     "undetermined_claims": statuses.count("undetermined"), "truncated": truncated, "limits": dict(LIMITS)},
    }
