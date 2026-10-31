"""Opt-in sparse Quantity field evidence; source syntax is not scientific approval.

Existing packets without a /raw witness retain their historical validation path.
No source strings are joined, no units inferred and no arbitrary equations solved.
Association of a qualifier with its specimen remains an independent review gate.
"""
import re
from math import isclose

from .quantities import (NUMBER, NUMERIC_PREFIX, ENDPOINT_UNITS_RANGE, lexical,
                         numeric_presentation, parse_source_numeric)

POLICY = 'quantity-field-evidence/1'
ASSIGNMENT = re.compile(r"^(?:[A-Za-z]'?|\\[A-Za-z]+)\s*(=|≈)\s*(?=[+\-\d.])")
PROSE = ((r'cannot\s+exceed|does\s+not\s+exceed', '≤'),
         (r'more\s+than', '>'))


def balanced(text):
    """A selected unit cannot omit a TeX brace; dollar delimiters may be outside it."""
    depth = 0
    for token in re.finditer(r'(?<!\\)[{}]', text):
        depth += 1 if token[0] == '{' else -1
        if depth < 0:
            return False
    return depth == 0


def presentation(text):
    if not balanced(text):
        return None
    token = lexical(text)
    token = re.sub(r'([+-])\s+(?=\d|\.\d)',r'\1',token)
    # Numeric parentheses only; never strip an arbitrary equation or function.
    enclosing = re.fullmatch(rf'\(\s*({NUMBER}(?:\s*±\s*{NUMBER})?)\s*\)\s*(.*)',token)
    if enclosing:
        token = enclosing[1]+' '+enclosing[2]
    for words, symbol in PROSE:
        token = re.sub(r'^(?:' + words + r')\s+', symbol, token, flags=re.I)
    match = ASSIGNMENT.match(token)
    if match:
        token = ('≈ ' if match[1] == '≈' else '') + token[match.end():]
    return numeric_presentation(token)


def expression(text):
    """Finite number/unit expression, including a single literal assignment."""
    token = presentation(text)
    if token is None:
        return None
    endpoint = ENDPOINT_UNITS_RANGE.fullmatch(token)
    if endpoint and strict_unit(endpoint[2]) == strict_unit(endpoint[4]):
        token = f'{endpoint[1]} to {endpoint[3]} {endpoint[2]}'
    match = NUMERIC_PREFIX.fullmatch(token)
    if not match:
        return None
    parsed = parse_source_numeric(match[1])
    if parsed['status'] != 'parsed' or parsed['errors']:
        return None
    return dict(parsed, inline_unit=match[2])


def strict_unit(text):
    """Formatting aliases only, retaining division/parenthesis scope."""
    if not balanced(text):
        return None
    token = lexical(text)
    token = re.sub(r'\b(?:angstroms?|kelvin|Kelvin|tesla|Tesla)\b',
                   lambda m: {'angstrom':'Å', 'angstroms':'Å', 'kelvin':'K',
                              'Kelvin':'K', 'tesla':'T', 'Tesla':'T'}[m[0]], token)
    return re.sub(r'\s+', '', token).replace('Å', 'Å').replace('²', '^2').replace('⁴', '^4')


def enabled(evidence, field):
    return any(e.field == field + '/raw' for e in evidence)


def equal(a, b):
    return a is b if a is None or b is None else isclose(a, b, rel_tol=1e-12, abs_tol=1e-15)


def field_quantity_issues(quantity, evidence, field):
    if quantity.status != 'reported':
        return []
    fields = {}
    for item in evidence:
        if item.field.startswith(field + '/'):
            fields.setdefault(item.field[len(field)+1:], []).append(item.quote)
    raw = quantity.raw
    if not any(' '.join(raw.split()) in ' '.join(q.split()) for q in fields.get('raw', [])):
        return ['quantity_raw_not_in_field_evidence']
    parsed = expression(raw)
    if parsed is None:
        return ['field_numeric_raw_requires_review']
    issues = []
    declared = strict_unit(quantity.unit)
    inline = strict_unit(parsed['inline_unit'])
    if parsed['inline_unit'] and inline != declared:
        issues.append('numeric_source_unit_mismatch')
    unit_quotes = fields.get('unit', [])
    if unit_quotes and not all(strict_unit(q) == declared for q in unit_quotes):
        issues.append('field_unit_witness_mismatch')
    if not parsed['inline_unit'] and not unit_quotes:
        issues.append('field_source_unit_missing')

    # A separate bound must name the SAME number, not just say "at most".
    # Multiple values / respectively clauses stay under review; no nearest-number rule.
    effective = parsed
    from .numeric_occurrences import shared_prefix_shape
    shared = [shared_prefix_shape(q,raw) for q in fields.get('relation', [])]
    shared = [p for p in shared if p is not None]
    if any(p['relation']!=quantity.relation for p in shared):
        issues.append('field_relation_disagrees_with_evidence')
    if quantity.relation != parsed['relation']:
        alternatives = [expression(q) for q in fields.get('relation', [])]
        alternatives = [p for p in alternatives if p and p['relation'] == quantity.relation
                        and (not p['inline_unit'] or strict_unit(p['inline_unit']) == declared)]
        alternatives += [p for p in shared if p['relation']==quantity.relation and strict_unit(p['unit'])==declared]
        selected = [p for p in alternatives if all(equal(p[k], getattr(quantity, k))
                    for k in ('value', 'lower', 'upper'))]
        nominal = next((getattr(quantity, k) for k in ('value', 'lower', 'upper')
                        if getattr(quantity, k) is not None), None)
        if parsed['relation'] == 'exact' and equal(parsed['value'], nominal) and len(selected) == 1:
            effective = selected[0]
        else:
            issues.append('field_relation_requires_review')
    if any(not equal(effective[k], getattr(quantity, k)) for k in ('value', 'lower', 'upper')):
        issues.append('numeric_value_disagrees_with_raw')

    approximate = parsed['approximate']
    if quantity.approximate and not approximate:
        target = next((getattr(quantity, k) for k in ('value', 'lower', 'upper')
                       if getattr(quantity, k) is not None), None)
        for quote in fields.get('approximate', []):
            token = lexical(quote)
            numbers = re.findall(NUMBER, token)
            match = re.search(rf'(?:≈|~|\babout\s+|\bapproximately\s+)\s*({NUMBER})', token, re.I)
            tail = token[match.end():].strip().rstrip('.') if match else ''
            if (len(numbers) == 1 and match and equal(float(match[1]), target)
                    and (not tail or strict_unit(tail) == declared)):
                approximate = True
        if not approximate:
            issues.append('field_approximation_requires_review')
    elif approximate and not quantity.approximate:
        issues.append('approximation_marker_lost')

    uncertainty = quantity.uncertainty
    source_error = parsed['uncertainty']
    if uncertainty is not None:
        quotes = fields.get('uncertainty', [])
        if not any(uncertainty.raw in q for q in quotes) and uncertainty.raw not in raw:
            issues.append('field_uncertainty_raw_not_in_evidence')
        if source_error is None:
            errors = []
            for quote in quotes:
                token = lexical(quote)
                match = re.search(rf'±\s*({NUMBER})\s*(.*)$', token)
                if (match and len(re.findall(NUMBER, token)) == 1
                        and strict_unit(match[2].rstrip('.')) == declared):
                    errors.append(float(match[1]))
            if len(errors) == 1:
                source_error = errors[0]
            else:
                issues.append('field_uncertainty_requires_review')
        if source_error is not None and not (equal(uncertainty.minus, source_error) and equal(uncertainty.plus, source_error)):
            issues.append('uncertainty_disagrees_with_raw')
        # Magnitude evidence alone cannot establish statistical interpretation.
        if uncertainty.kind != 'reported_unspecified' or uncertainty.level is not None:
            issues.append('field_uncertainty_definition_requires_review')
    elif source_error is not None:
        issues.append('uncertainty_lost')
    return list(dict.fromkeys(issues))
