"""Source assignment candidates for name repair, never physical registration.

This finite recognizer handles inline TeX assignments with explicit source units.
Other source layouts remain unresolved. Equal values do not prove sample identity;
the model must select the applicable assertion and scientific review still applies.
"""
import re

from .contract import digest
from .evidence import source_catalog
from .quantities import lexical, NUMERIC_PREFIX, numeric_shape_issues
from .quantity_raw_witness import source_literals, MAX_FRAGMENT
from .sources import sha

LEGACY_POLICY = 'quantity_assignment_name_v1'
POLICY = 'quantity_assignment_name_v2'
MATH = re.compile(r'(?<![\\$])\$(?!\$)([^$\n]+)(?<!\\)\$(?!\$)')
RELATION = re.compile(r'(?<![<>=])=(?!=)|\\(?:approx|simeq)(?![A-Za-z])')


def unit_key(value):
    # Some fallible drafts doubled a TeX command escape. Permit this comparison
    # spelling only, record it, and never alter the retained quantity or its holds.
    value = re.sub(r'\\\\(?=(?:mu|Omega|mathrm|textrm|text|mbox)\b)', r'\\', value)
    value = re.sub(r'\\\\(?=[,;!])', r'\\', value)
    return re.sub(r'[\s~]', '', lexical(value).replace('²', '^2').replace('⁴', '^4'))


def inline_assignments(text, quantity):
    """Yield exact source expressions compatible with a frozen numeric quantity."""
    if quantity.status != 'reported' or not quantity.unit:
        return
    for match in MATH.finditer(text):
        content = match[1]
        relations = list(RELATION.finditer(content))
        if len(relations) != 1:
            continue
        relation = relations[0]
        lhs = content[:relation.start()].strip()
        rhs = content[relation.end():].strip()
        if not lhs or not re.search(r'[A-Za-z\\]', lhs):
            continue
        # Reject bare numerical comparisons, multi-assignment lists and prose
        # inside the mathematical name. A model cannot use this as a free label.
        if re.search(r'[,;=<>]', lhs):
            continue
        approximate = relation[0] != '='
        numeric = NUMERIC_PREFIX.fullmatch(('≈ ' if approximate else '') + lexical(rhs))
        if numeric is None or numeric_shape_issues(numeric[1], quantity):
            continue
        if bool(approximate or numeric[1].lstrip().startswith(('≈', '~'))) != quantity.approximate:
            continue
        inside_unit = numeric[2]
        end = match.end()
        source_unit = inside_unit
        if inside_unit:
            if unit_key(inside_unit) != unit_key(quantity.unit):
                continue
        else:
            # A TeX unit can continue outside math: $x=1$~f$\Omega$m$^2$.
            # Compare explicit prefixes only; never infer units from context.
            endings = []
            for length in range(1, min(120, len(text) - end) + 1):
                tail = text[end:end + length]
                if any(c in tail for c in ',;\n'):
                    break
                if unit_key(tail) == unit_key(quantity.unit):
                    following = text[end + length:end + length + 1]
                    if not following or following.isspace() or following in '.,;:)]}':
                        endings.append((end + length, tail))
            if not endings:
                continue
            end, source_unit = endings[-1]
        yield dict(name=lhs, start_char=match.start(), end_char=end,
            numeric_start_char=match.start(1) + relation.end(),
            quote=text[match.start():end], quote_sha256=sha(text[match.start():end].encode()),
            source_unit=source_unit, declared_unit=quantity.unit,
            declared_unit_escape_review=bool(re.search(r'\\\\', quantity.unit)),
            numeric_shape_matched=True, explicit_unit_matched=True)


def mixed_assignments(text, quantity):
    """Recognize a math name followed immediately by an explicit prose assignment.

    Keep the source intact: only the numeric recognizer's complete fragment may
    follow the assignment. Ratios, chained names and unsupported layouts remain
    unresolved. Matching this syntax never proves physical owner applicability.
    """
    if quantity.status != 'reported' or not quantity.unit:
        return
    for match in MATH.finditer(text):
        name = match[1].strip()
        if (not re.search(r'[A-Za-z\\]', name) or re.search(r'[,;=<>/+*]', name)
                or re.search(r'\\(?:approx|simeq|leq?|geq?|pm|times|cdot)\b', name)):
            continue
        prefix = text[max(0, match.start() - 160):match.start()]
        if re.search(r'(?:=|[/+*]|\\(?:approx|simeq))\s*$', prefix):
            continue
        relation = re.match(r'[ \t~]*(?P<relation>=(?!=)|\\(?:approx|simeq)(?![A-Za-z]))[ \t~]*', text[match.end():])
        if relation is None:
            continue
        # An approximate relation is part of the numeric fragment, so the same
        # shape/approximation checks apply without manufacturing a source token.
        offset = relation.end() if relation['relation'] == '=' else relation.start('relation')
        numeric_start = match.end() + offset
        tail = text[numeric_start:numeric_start + MAX_FRAGMENT]
        for candidate in source_literals(tail, quantity):
            if re.fullmatch(r'[ \t~$]*', tail[:candidate['start_char']]) is None:
                continue
            end = numeric_start + candidate['end_char']
            if re.match(r'\s*,\s*\$?\s*[+−-]?\d', text[end:]):
                continue
            unit = NUMERIC_PREFIX.fullmatch(lexical(candidate['raw']))
            if unit is None or not unit[2]:
                continue
            quote = text[match.start():end]
            yield dict(name=name, start_char=match.start(), end_char=end,
                numeric_start_char=numeric_start + candidate['start_char'],
                quote=quote, quote_sha256=sha(quote.encode()), source_unit=unit[2],
                declared_unit=quantity.unit, declared_unit_escape_review=False,
                numeric_shape_matched=True, explicit_unit_matched=True,
                assignment_syntax='math_name_external_assignment',
                numeric_source_fragment=candidate['raw'])


def assignments(text, quantity, policy=POLICY):
    if policy not in {LEGACY_POLICY, POLICY}:
        raise ValueError('quantity_name_policy_unknown')
    yield from inline_assignments(text, quantity)
    if policy == POLICY:
        yield from mixed_assignments(text, quantity)


def context(graph, path, bundle, policy=POLICY):
    """Bind candidates to one result's original numeric evidence and identity."""
    match = re.fullmatch(r'/observations/(\d+)/result/quantity_name_raw', path)
    if match is None:
        return None
    observation = graph.observations[int(match[1])]
    result = observation.result
    catalog = source_catalog(bundle)
    quantity_spans = {alias for evidence in result.evidence if '/quantity' in evidence.fields
                      for alias in evidence.span_ids}
    choices = {}
    for block in bundle.blocks:
        for candidate in assignments(block.text, result.quantity, policy):
            owner_spans = [alias for alias, span in catalog['spans'].items()
                          if span['block_id'] == block.id and span['start_char'] <= candidate['numeric_start_char'] < span['end_char']]
            if not set(owner_spans) & quantity_spans:
                continue
            spans = [alias for alias, span in catalog['spans'].items() if span['block_id'] == block.id
                     and span['start_char'] < candidate['end_char'] and span['end_char'] > candidate['start_char']]
            choices[f'N{len(choices) + 1}'] = dict(candidate, block_id=block.id,
                document_id=block.document_id, source_span_ids=spans)
    return dict(policy=policy, observation_id=observation.id, inventory_item_ids=observation.inventory_item_ids,
        frozen_quantity=result.quantity.model_dump(), frozen_quantity_sha256=digest(result.quantity.model_dump()),
        sample_id=observation.sample_id, state_id=observation.state_id, protocol_id=observation.protocol_id,
        source_role=result.source_role, origin=result.origin, definition=observation.definition.model_dump(),
        choices=choices, independent_gold=False, scientific_acceptance=False,
        limitation=('Finite inline assignment support; table headers, prose and ambiguous source owners require another source-backed review path.'
                    if policy == LEGACY_POLICY else
                    'Finite inline or math-name external assignments only; table headers, unsupported prose and ambiguous source owners require another source-backed review path.'))
