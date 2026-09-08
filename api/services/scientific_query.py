"""Conservative English/Chinese development grammar, entirely I/O-free.

Unrecognized clauses remain visible and require clarification. This is query
interpretation, not a scientific result, evidence root or source-use grant.
Unlike legacy catalogue grouping, no isotope/phase/variable/charge is erased.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from models.scientific_query import (
    EvidenceConstraint,
    FormulaMention,
    FormulaNormalization,
    QuantityConstraint,
    ScientificQueryInterpretation,
    UnresolvedClause,
)
from services.pressure_semantics import classify_pressure
from services.scientific_values import parse_scientific_value

VERSION = "scientific-query/1.0.0"
_ELEMENTS = frozenset("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split())
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_ELEMENT = re.compile(r"[A-Z][a-z]?")
_AMOUNT = re.compile(r"\d+(?:\.\d+)?")
_TOKEN = re.compile(r"[A-Za-z0-9α-ωΑ-Ω₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹₊₋⁺⁻_^{}()[\].+\-−/·@$]+")
_NOT_FORMULAS = {"Tc", "TC", "T_c", "T_{c}", "K", "mK", "GPa", "MPa", "kPa", "Pa", "P", "BCS", "DFT", "AI", "SC", "NER", "LLM"}
_ELEMENT_WORDS = {"In", "As", "At", "No", "He", "I", "Be", "Am"}
_SHORTHANDS = {"YBCO", "BSCCO", "LSCO", "LBCO", "NCCO", "PCCCO", "LCO", "Y123", "Y124"}
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_TC = r"(?:T_\{c\}|T_c|Tc|critical\s+temperature|superconducting\s+transition\s+temperature|transition\s+temperature|超导转变温度|临界温度|超导临界温度)"
_PRESSURE = r"(?:pressure|压力|压强|P)"
_UNIT = r"(?:GPa|gpa|MPa|kPa|Pa|kbar|bar|atm|mK|K|k|kelvin|Kelvin|吉帕|兆帕|千帕|帕|开尔文|开|°C|℃|°F|eV|meV)"
_UNIT_MAP = {"吉帕": "GPa", "兆帕": "MPa", "千帕": "kPa", "帕": "Pa", "开尔文": "K", "开": "K"}
_COMPARATORS = {
    "at least": ">=", "no less than": ">=", "greater than": ">", "more than": ">", "above": ">", "over": ">",
    "at most": "<=", "no more than": "<=", "less than": "<", "below": "<", "under": "<",
    "不低于": ">=", "至少": ">=", "大于": ">", "高于": ">", "超过": ">",
    "不高于": "<=", "不超过": "<=", "至多": "<=", "小于": "<", "低于": "<",
    "等于": "", "为": "", "是": "", "在": "", "equals": "", "is": "", "at": "", "=": "",
    ">": ">", "<": "<", ">=": ">=", "<=": "<=", "≥": ">=", "≤": "<=",
}
_REL = "(?:" + "|".join(re.escape(key) for key in sorted(_COMPARATORS, key=len, reverse=True)) + ")"
_ENDPOINT = rf"{_NUMBER}\s*{_UNIT}?"
_BODY = rf"(?:(?:between\s+|从\s*){_ENDPOINT}\s*(?:and|to|到|至)\s*{_ENDPOINT}|{_ENDPOINT}\s*(?:to|–|—|-|到|至)\s*{_ENDPOINT}|{_ENDPOINT}(?:\s*(?:±|\+/-)\s*{_ENDPOINT})?)"
_QUANTITY = re.compile(rf"(?<![A-Za-z0-9_])(?P<label>{_TC}|{_PRESSURE})\s*(?P<rel>{_REL})?\s*(?P<body>{_BODY})(?![A-Za-z0-9])", re.IGNORECASE)
_BARE_PRESSURE = re.compile(rf"(?<![A-Za-z0-9])(?P<rel>{_REL})?\s*(?P<body>{_NUMBER}\s*(?:GPa|gpa|MPa|kPa|Pa|kbar|bar|atm|吉帕|兆帕|千帕|帕))(?![A-Za-z])")
_TC_FIELD = re.compile(rf"(?<![A-Za-z]){_TC}(?![A-Za-z])", re.IGNORECASE)
_PRESSURE_FIELD = re.compile(rf"(?<![A-Za-z]){_PRESSURE}(?![A-Za-z])", re.IGNORECASE)
_AMBIENT = re.compile(r"(?:at\s+)?(?:ambient\s+pressure|atmospheric\s+pressure)|常压|大气压|环境压力", re.IGNORECASE)
_MECHANISM = re.compile(r"\b(?:why|how|explain|mechanism|pairing|symmetry|phonon|phonons|electron-phonon|BCS|Eliashberg|spin\s+fluctuations?|role|effect|impact|dependence|relationship)\b|为什么|为何|解释|机理|机制|配对|对称性|声子|自旋涨落|作用|影响|依赖|关系", re.IGNORECASE)
_VALUE_REQUEST = re.compile(rf"\b(?:what|which)\s+(?:is\s+|are\s+)?(?:the\s+)?(?:{_TC}|{_PRESSURE})(?![A-Za-z])|\b(?:values?|numerical|numbers?|how\s+(?:high|much))\b|多少|数值|具体温度|具体压力", re.IGNORECASE)
_QUERY_ACTION = re.compile(r"\b(?:show|find|list|give|report|tell|what|which)\b|请|列出|查找|给出|查询", re.IGNORECASE)
_COMPARISON = re.compile(r"\b(?:compare|comparison|versus|vs)\b|比较|对比", re.IGNORECASE)
_EVIDENCE_PATTERNS = [
    ("experimental_outcome", "not_detected", r"\b(?:(?:did|does)\s+not\s+detect\s+superconductivity|not\s+detected|not\s+observed|no\s+superconductivity(?:\s+(?:was\s+)?observed)?|non[- ]superconducting|no\s+transition)\b|未检测到超导|未观察到超导|没有观察到超导|未发现超导|未检测到|未观察到"),
    ("experimental_outcome", "positive_reported", r"\b(?:superconductivity\s+(?:was\s+)?(?:observed|detected)|positive\s+superconductivity\s+reports?)\b|(?<!未)(?<!没有)检测到超导|(?<!未)(?<!没有)观察到超导"),
    ("knowledge_origin", "AI-Proposed", r"\b(?:AI[- ]proposed|AI[- ]generated)\b|人工智能提出|AI提出"),
    ("knowledge_origin", "Inferred", r"\binferred\b|推断"),
    ("knowledge_origin", "Computed", r"\b(?:computed|calculated|computational|theoretical|DFT)\b|理论计算|计算|理论"),
    ("knowledge_origin", "Observed", r"\b(?:experimental(?:ly)?|measured|observed)\b|实验测量|实验|测量"),
    ("knowledge_origin", "Unknown", r"\bunknown\s+(?:knowledge\s+)?origin\b|知识来源未知"),
    ("source_role", "primary", r"\bprimary\b|一手|原始研究"),
    ("source_role", "cited", r"\b(?:cited|secondary)\b|被引用|二手|引用"),
]
_UNSUPPORTED = [
    ("unsupported_disjunction", r"\b(?:or|either|rather\s+than)\b|或者|或是|或"),
    ("unsupported_negation", r"\b(?:not|no|without|exclude|excluding|except|never|isn't|aren't|don't|doesn't)\b|不是|非|不|未|没有|排除|除外"),
    ("temporal_constraint_unresolved", r"\b(?:before|after|since|until|latest|recent|currently|today|as\s+of|during|published\s+in|in\s+20\d{2})\b|最新|最近|目前|现在|截至|之前|之后|以来|年"),
    ("state_constraint_unresolved", r"\b(?:bulk|film|thin[- ]film|monolayer|bilayer|interface|strained|strain|phase|polymorph|annealed|quenched|disordered|crystal|structure|space\s+group|magnetic\s+field|ambient|room[- ]temperature|(?:low|high|ultrahigh)\s+pressure)\b|薄膜|单层|双层|界面|应变|体相|块材|相态|结构|空间群|退火|磁场|室温|低压|高压"),
    ("isotope_constraint_unresolved", r"\b(?:isotope|isotopic|deuterium|deuterated|tritium)\b|同位素|氘|氚"),
    ("doping_constraint_unresolved", r"\b(?:doped|doping|carrier|substitution|oxygen[- ]deficient|stoichiometry)\b|掺杂|载流子|取代|缺氧|化学计量"),
    ("criterion_constraint_unresolved", r"\b(?:onset|midpoint|zero[- ]resistance|resistive|susceptibility|Meissner|shielding|criterion|criteria|measurement\s+method|specific\s+heat)\b|起始|中点|零电阻|磁化率|迈斯纳|判据|测量方法|比热"),
    ("approximation_unresolved", rf"\b(?:approximately|roughly|around|rough|uncertainty)\b|\babout(?=\s*{_NUMBER})|约|大约|左右|不确定度|≈|~|±"),
    ("ambiguous_origin", r"\bpredicted\b|预测"),
]
_FILLER_EN = re.compile(r"\b(?:what|which|is|are|was|were|a|an|the|of|in|for|at|with|and|to|from|by|on|as|does|do|can|could|please|tell|me|find|show|list|give|report|reports|reported|value|values|data|material|materials|compound|compounds|superconductor|superconductors|superconductivity|superconducting|temperature|pressure|critical|transition|properties|property|between|than|that|have|has|it|its|their|result|results|evidence|only|versus|vs|compare|comparison|explain|why|how|mechanism|mechanisms|pairing|symmetry|phonon|phonons|electron|BCS|Eliashberg|spin|fluctuation|fluctuations|affect|affects|effect|effects|dependence|behavior|behaviour|relationship)\b", re.IGNORECASE)
_FILLER_ZH = re.compile(r"请|问|告诉我|给出|列出|查找|寻找|查询|哪些|哪个|什么|多少|如何|怎样|为什么|为何|解释|介绍|比较|对比|超导体|超导材料|超导性|超导电性|超导|材料|化合物|临界温度|超导转变温度|压力|压强|数值|数据|性质|结果|研究|证据|报告|报道|机制|机理|配对|对称性|声子|自旋涨落|电子|影响|关系|的|是|为|在|有|和|与|及|下|于|其|分别|仅|只")


def normalize_query_formula(raw_formula: str) -> FormulaNormalization:
    if type(raw_formula) is not str or not raw_formula or len(raw_formula) > 200:
        raise ValueError("Formula input must contain 1..200 characters")

    def unresolved(reason):
        return FormulaNormalization(raw_formula=raw_formula, status="unresolved", reason_codes=[reason])

    text = raw_formula.strip()
    if text in _SHORTHANDS:
        return unresolved("formula_shorthand_requires_resolution")
    if re.search(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻₊₋^]", text) or re.search(r"(?:^|\[)\d+(?=[A-Z])", text) and not re.match(r"\d+[A-Z]-", text):
        return unresolved("isotope_or_charge_requires_resolution")
    if "/" in text or "@" in text:
        return unresolved("interface_requires_resolution")
    if re.match(r"(?:[α-ωΑ-Ω]|\d+[A-Z])-", text):
        return unresolved("phase_requires_resolution")
    if re.search(r"[δΔ]|[+−-](?:[xyz]|delta)|(?:^|[0-9_(])[xyz](?![a-z])", text):
        return unresolved("variable_composition_requires_resolution")
    if any(character in text for character in "+-−·,"):
        return unresolved("charge_mixture_or_modifier_requires_resolution")
    if re.search(r"\s", text):
        return unresolved("formula_spacing_requires_resolution")
    if text.count("$") % 2:
        return unresolved("unbalanced_formula_markup")
    text = text.replace("$", "").translate(_SUBSCRIPTS)
    text = re.sub(r"_\{(\d+(?:\.\d+)?)\}", r"\1", text)
    text = re.sub(r"_(\d+(?:\.\d+)?)", r"\1", text)
    if any(character in text for character in "_{}"):
        return unresolved("unsupported_formula_markup")
    tokens = list(re.finditer(r"[A-Z][a-z]?|\d+(?:\.\d+)?|[()[\]]", text))
    if "".join(item.group() for item in tokens) != text or not tokens:
        return unresolved("variable_or_unrecognized_formula_syntax")
    stack, preceding = [], None
    for token in (item.group() for item in tokens):
        if token in {"D", "T"}:
            return unresolved("isotope_requires_resolution")
        if token[0].isalpha():
            if token not in _ELEMENTS:
                return unresolved("unknown_element_or_shorthand")
            preceding = "element"
        elif token in "([":
            stack.append(token)
            preceding = "open"
        elif token in ")]":
            if not stack or stack.pop() != {")": "(", "]": "["}[token] or preceding not in {"element", "number", "close"}:
                return unresolved("unbalanced_formula_group")
            preceding = "close"
        else:
            try:
                number = Decimal(token)
            except InvalidOperation:
                return unresolved("invalid_stoichiometric_amount")
            if preceding not in {"element", "close"} or not number.is_finite() or number <= 0:
                return unresolved("invalid_stoichiometric_amount")
            preceding = "number"
    if stack or preceding not in {"element", "number", "close"}:
        return unresolved("unbalanced_formula_group")
    return FormulaNormalization(raw_formula=raw_formula, normalized_formula=text, status="normalized")


def _formula_candidates(text):
    """One lexical pass; preserve whole tokens and bound context copies."""
    stripped = text.strip()
    standalone = stripped if len(stripped) <= 200 else None
    for match in _TOKEN.finditer(text):
        # Do not split a long qualified token into a shorter, false identity.
        if match.end() - match.start() > 201:
            continue
        raw = match.group().rstrip(".")
        if not raw or len(raw) > 200 or raw in _NOT_FORMULAS:
            continue
        # Capitalized English words are not elemental evidence merely because
        # they also name an element. Explicit material/property context or a
        # standalone formula is required for these ambiguous tokens.
        if raw in _ELEMENT_WORDS and standalone != raw:
            before = text[max(0, match.start() - 200):match.start()]
            after = text[match.end():match.end() + 200]
            named = re.search(r"\b(?:element|material|compound|of|for)\s+$", before, re.IGNORECASE)
            property_after = raw != "No" and re.match(rf"\s*(?:{_TC}|的临界温度)(?![A-Za-z])", after)
            if not (named or property_after):
                continue
        letters = _ELEMENT.findall(raw)
        likely = (raw in _ELEMENTS or raw in {"D", "T"} or len(letters) >= 2 and not re.search(r"[a-z]{3}", raw)
                  or bool(re.search(r"[A-Z]", raw) and re.search(r"[0-9₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹_^]", raw)))
        if not likely:
            continue
        yield match.start(), raw, normalize_query_formula(raw)


def find_formula_mentions(text: str) -> list[FormulaMention]:
    """Bounded source/query lexical mentions, never legacy catalogue grouping."""
    if type(text) is not str or len(text) > 20000:
        raise ValueError("Formula mention scan requires <=20000 characters")
    result = []
    for start, raw, normalization in _formula_candidates(text):
        result.append(FormulaMention(raw_text=raw, start=start, end=start + len(raw), normalization=normalization))
        if len(result) > 256:
            raise ValueError("Formula mention count exceeds development limit")
    return result


def match_source_formulas(text: str, wanted) -> set[str]:
    """Bounded source membership scan without query-span DTO/count limits.

    The retained generation already bounds aggregate bytes. Independently bound
    this public pure helper too, using incremental UTF-8 accounting; no source
    truncation, unsafe token splitting, source text list or unbounded matches.
    """
    maximum = 16 * 1024 * 1024
    if type(text) is not str or len(text) > maximum:
        raise ValueError("Source formula scan exceeds its retained text bound")
    if type(wanted) not in {set, frozenset, list, tuple} or len(wanted) > 32:
        raise ValueError("At most 32 normalized formula targets are required")
    targets = set()
    for item in wanted:
        normalized = normalize_query_formula(item)
        if normalized.status != "normalized" or normalized.normalized_formula != item:
            raise ValueError("Source formula targets must already be safely normalized")
        targets.add(item)
    size = 0
    for start in range(0, len(text), 65536):
        size += len(text[start:start + 65536].encode("utf-8"))
        if size > maximum:
            raise ValueError("Source formula scan exceeds its retained UTF-8 bound")
    found = set()
    if not targets:
        return found
    for _, _, normalized in _formula_candidates(text):
        if normalized.status == "normalized" and normalized.normalized_formula in targets:
            found.add(normalized.normalized_formula)
            if found == targets:
                break
    return found


def interpret_scientific_query(raw_query: str) -> ScientificQueryInterpretation:
    if type(raw_query) is not str or not raw_query.strip() or len(raw_query) > 2000:
        raise ValueError("Scientific query requires 1..2000 nonblank characters")
    covered = [False] * len(raw_query)
    constraints, evidence, unresolved, formulas = [], [], [], []
    requested = set()

    def free(start, end):
        return not any(covered[start:end])

    def mark(start, end):
        covered[start:end] = [True] * (end - start)

    def clause(start, end, reason):
        unresolved.append(UnresolvedClause(raw_text=raw_query[start:end], start=start, end=end, reason_code=reason))
        mark(start, end)

    def span(match):
        return {"raw_text": match.group(), "start": match.start(), "end": match.end()}

    def quantity(match, field):
        if not free(match.start(), match.end()):
            return
        requested.add(field)
        raw_body = match["body"].strip()
        relation = _COMPARATORS.get((match["rel"] or "").lower(), "")
        for original, canonical in _UNIT_MAP.items():
            raw_body = raw_body.replace(original, canonical)
        endpoints = re.fullmatch(rf"(?:between\s+|从\s*)?({_NUMBER})\s*({_UNIT})?\s*(?:and|to|–|—|-|到|至)\s*({_NUMBER})\s*({_UNIT})?", raw_body, re.IGNORECASE)
        if endpoints:
            unit1, unit2 = endpoints[2], endpoints[4]
            if relation or not (unit1 or unit2):
                clause(match.start(), match.end(), "ambiguous_interval_or_missing_unit")
                return
            value = [endpoints[1] + " " + (unit1 or unit2), endpoints[3] + " " + (unit2 or unit1)]
        else:
            value = relation + raw_body
        proposal = parse_scientific_value(value, field)
        if proposal["status"] != "parsed" or proposal["unit_basis"] not in {"explicit", "endpoint_units"}:
            clause(match.start(), match.end(), "quantity_unit_or_syntax_unresolved")
            return
        if proposal["approximate"] or proposal["uncertainty"] is not None:
            clause(match.start(), match.end(), "quantity_uncertainty_unresolved")
            return
        if any(proposal[key] is not None and proposal[key] < 0 for key in ("value", "lower", "upper")):
            clause(match.start(), match.end(), "quantity_domain_unresolved")
            return
        constraints.append(QuantityConstraint(**span(match), field=field, relation=proposal["relation"], value=proposal["value"],
            lower=proposal["lower"], upper=proposal["upper"], unit=proposal["unit"], unit_basis="explicit"))
        requested.add(field)
        mark(match.start(), match.end())

    for match in _QUANTITY.finditer(raw_query):
        field = "pressure_gpa" if re.fullmatch(_PRESSURE, match["label"], re.IGNORECASE) else "tc_kelvin"
        # "Tc at 150 GPa" asks for Tc at a pressure, not Tc measured in GPa.
        # Only this explicit context connector is safe; e.g. "Tc <150 GPa"
        # still fails unit validation rather than changing its meaning.
        if (field == "tc_kelvin" and (match["rel"] or "").lower() in {"at", "在"}
                and re.search(r"(?:GPa|gpa|MPa|kPa|Pa|kbar|bar|atm|吉帕|兆帕|千帕|帕)\s*$", match["body"])):
            continue
        quantity(match, field)
    for match in _BARE_PRESSURE.finditer(raw_query):
        quantity(match, "pressure_gpa")
    for match in _AMBIENT.finditer(raw_query):
        if free(match.start(), match.end()):
            ambient = classify_pressure({"pressure": "ambient pressure"})
            constraints.append(QuantityConstraint(**span(match), field="pressure_gpa", relation="exact", value=ambient.pressure_gpa,
                                                   unit="GPa", unit_basis="explicit_ambient_reference"))
            requested.add("pressure_gpa")
            mark(match.start(), match.end())
    for field, value, pattern in _EVIDENCE_PATTERNS:
        for match in re.finditer(pattern, raw_query, re.IGNORECASE):
            if free(match.start(), match.end()):
                evidence.append(EvidenceConstraint(**span(match), field=field, value=value))
                mark(match.start(), match.end())
    try:
        mentions = find_formula_mentions(raw_query)
    except ValueError:
        # The HTTP query bound permits many short formulas. A complexity
        # limit is a clarification, not an uncaught500 or a partial parse.
        mentions = []
        clause(0, len(raw_query), "query_complexity_unresolved")
    for item in mentions:
        if free(item.start, item.end):
            formulas.append(item)
            mark(item.start, item.end)
            if item.normalization.status != "normalized":
                clause(item.start, item.end, item.normalization.reason_codes[0])
    for expression, field in ((_TC_FIELD, "tc_kelvin"), (_PRESSURE_FIELD, "pressure_gpa")):
        for match in expression.finditer(raw_query):
            if free(match.start(), match.end()):
                requested.add(field)
                mark(match.start(), match.end())
    for reason, pattern in _UNSUPPORTED:
        for match in re.finditer(pattern, raw_query, re.IGNORECASE):
            # A recognized noun inside an otherwise unsupported condition
            # does not erase the condition (e.g. "low pressure"). Fully
            # parsed phrases such as "no less than 20 K" remain protected.
            if not all(covered[match.start():match.end()]):
                clause(match.start(), match.end(), reason)
    for pattern in (_FILLER_EN, _FILLER_ZH):
        for match in pattern.finditer(raw_query):
            if free(match.start(), match.end()):
                mark(match.start(), match.end())
    # "Tell me about Tc" is discourse, while "Tc about 39 K" was explicitly
    # flagged as an approximate numerical condition above.
    for match in re.finditer(r"\babout\b", raw_query, re.IGNORECASE):
        if free(match.start(), match.end()):
            mark(match.start(), match.end())
    # Anything not understood survives. Never silently discard a qualifier,
    # unbound temperature, unsupported unit, equation, temporal span or command.
    residual = "".join(" " if covered[index] or character.isspace() or character in ",;:?!。；，：？！'\"" else character
                       for index, character in enumerate(raw_query))
    for match in re.finditer(r"\S+", residual):
        start, end = match.span()
        clause(start, end, "unsupported_clause")
    for field in ("knowledge_origin", "source_role", "experimental_outcome"):
        values = {item.value for item in evidence if item.field == field}
        if len(values) > 1:
            clause(0, len(raw_query), "conflicting_evidence_constraints")
    for field in ("tc_kelvin", "pressure_gpa"):
        members = [item for item in constraints if item.field == field]
        lower, upper, strict_low, strict_high = 0.0, float("inf"), False, False
        for item in members:
            low = item.value if item.relation == "exact" else item.lower
            high = item.value if item.relation == "exact" else item.upper
            if low is not None and low >= lower:
                strict_low = item.relation == "gt" or low == lower and strict_low
                lower = low
            if high is not None and high <= upper:
                strict_high = item.relation == "lt" or high == upper and strict_high
                upper = high
        if lower > upper or lower == upper and (strict_low or strict_high):
            clause(0, len(raw_query), "contradictory_quantity_constraints")
    mechanism, comparison = bool(_MECHANISM.search(raw_query)), bool(_COMPARISON.search(raw_query))
    if (not mechanism and not comparison and not formulas and not constraints and not evidence
            and not _VALUE_REQUEST.search(raw_query) and not _QUERY_ACTION.search(raw_query)
            and not re.fullmatch(rf"\s*(?:{_TC}|{_PRESSURE})[?？]?\s*", raw_query, re.IGNORECASE)):
        # A noun-only fulltext bag such as "hydride pressure result" is not
        # an instruction to select a pressure value. Explicit value requests,
        # material/property shorthand and constraints keep their numeric scope.
        requested.clear()
    explanatory = mechanism and not constraints and not evidence and not _VALUE_REQUEST.search(raw_query)
    general_keywords = not mechanism and not comparison and not requested and not constraints and not evidence
    if general_keywords and not formulas:
        unresolved = [item for item in unresolved if not (item.reason_code == "state_constraint_unresolved"
                      and item.raw_text.lower() in {"structure", "phase"})]
    if explanatory or general_keywords:
        # Explanatory content and ordinary lexical search are intentionally
        # opaque, retained verbatim in raw_query, not misrepresented as closed
        # numerical predicates. Only generic words may pass this route;
        # explicit semantic vetoes and leftover numbers/operators/markup still
        # require clarification. An unknown search keyword is not a bad filter.
        requested.clear()
        unresolved = [item for item in unresolved if item.reason_code != "unsupported_clause"
                      or not re.fullmatch(r"(?:[A-Za-z\u3400-\u9fff][A-Za-z\u3400-\u9fff_.-]*|\.+)", item.raw_text)]
    numeric = bool(requested or constraints or any(item.field == "experimental_outcome" for item in evidence))
    intent = "comparison" if comparison else "mixed" if mechanism and numeric else "mechanism" if mechanism else "numerical" if numeric else "general"
    if comparison and len(formulas) < 2:
        clause(0, len(raw_query), "comparison_targets_unresolved")
    if len(formulas) > 1 and (constraints or evidence) and not comparison:
        clause(0, len(raw_query), "material_constraint_scope_unresolved")
    if (comparison and len(formulas) > 1
            and any(_COMPARISON.search(raw_query).start() <= item.start < formulas[-1].end for item in [*constraints, *evidence])):
        clause(0, len(raw_query), "material_constraint_scope_unresolved")
    if len(formulas) > 32 or len(constraints) > 32 or len(evidence) > 32 or len(unresolved) > 128:
        formulas, constraints, evidence = [], [], []
        unresolved = [UnresolvedClause(raw_text=raw_query, start=0, end=len(raw_query), reason_code="query_scope_limit")]
    # Only typographical formula normalizations affect lexical display. Raw
    # text and every original span remain unchanged in their own fields.
    normalized = raw_query
    for item in sorted(formulas, key=lambda item: item.start, reverse=True):
        if item.normalization.status == "normalized":
            normalized = normalized[:item.start] + item.normalization.normalized_formula + normalized[item.end:]
    chinese = bool(re.search(r"[\u3400-\u9fff]", raw_query))
    english = bool(re.search(r"[A-Za-z]{2,}", raw_query))
    language = "mixed" if chinese and english else "zh" if chinese else "en"
    questions = ["Please clarify the unresolved clauses, including exact material/state, quantity units, evidence category or time scope; no unsupported condition will be discarded."] if unresolved else []
    return ScientificQueryInterpretation(raw_query=raw_query, normalized_query=normalized, language=language, intent=intent,
        status="clarification_required" if unresolved else "resolved", requested_fields=sorted(requested), formulas=formulas,
        constraints=constraints, evidence_constraints=evidence, unresolved_clauses=unresolved, clarification_questions=questions)
