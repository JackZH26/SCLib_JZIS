"""Exact numeric source fragments; neither semantic ownership nor scientific Gold.

The recognizer requires an explicit local unit and a complete compatible numeric
shape. Unsupported prose/table layouts keep their source assertions unresolved.
It never constructs a literal by concatenating a model number and unit.
"""
import re
from types import SimpleNamespace

from .contract import Quantity, digest
from .evidence import source_catalog, selected_quotes
from .quantities import (NUMBER, NUMERIC_PREFIX, ENDPOINT_UNITS_RANGE, lexical,
                         numeric_presentation, unmapped_quantity_source_issues)
from .sources import sha

POLICY = 'source_literal_choice_v2'
LEGACY_POLICY = 'source_literal_numeric_shape_v1'
START = re.compile(r'(?:(?<!\\)\\(?:lesssim|gtrsim|approx|simeq|sim|leq?|geq?)(?![A-Za-z])\s*|'
                   r'(?:<=|>=|[≈≲≳<>≤≥~])\s*|'
                   r'(?<![\w.\\+−<>≈≲≳≤≥~-])(?:between\s+|(?:about|approximately)\s+)?)'
                   r'[+−-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', re.I)
MAX_FRAGMENT = 240
MAX_CHOICES = 32


def unit_text(text):
    # Keep parentheses/division and do not repair doubled TeX command escapes.
    return re.sub(r'[\s~]', '', lexical(text))


def compatible(raw, quantity):
    """Full numeric fidelity plus explicit units, with no scale conversion."""
    candidate = Quantity.model_validate(dict(quantity.model_dump(), raw=raw))
    if unmapped_quantity_source_issues(candidate,
            [SimpleNamespace(field='/quantity', quote=raw)], '/quantity'):
        return False
    token = numeric_presentation(lexical(raw))
    endpoint = ENDPOINT_UNITS_RANGE.fullmatch(token)
    if endpoint and unit_text(endpoint[2]) == unit_text(endpoint[4]) == unit_text(quantity.unit):
        token = f'{endpoint[1]} to {endpoint[3]} {quantity.unit}'
    match = NUMERIC_PREFIX.fullmatch(token)
    if not match or not match[2] or unit_text(match[2]) != unit_text(quantity.unit):
        return False
    approximate = bool(re.match(r'^(?:≈|~|about\b|approximately\b)', match[1], re.I))
    return approximate == quantity.approximate


def continued_before(text):
    """Do not select the tail of a range, uncertainty, list or product."""
    prefix = lexical(text[-160:])
    return bool(re.search(rf'{NUMBER}[^.;\n]*?(?:±|\+/-|--?|–|—|~|\bto|\band|×|·|\\times|\\cdot)\s*$', prefix, re.I))


def continued_after(text):
    suffix = re.sub(r'^[\s$~]+', '', text)
    if re.match(r'^(?:[±/^*×·_²⁴]|\\(?:pm|times|cdot)\b)', suffix):
        return True
    if re.match(rf'^(?:--?|–|—|~|\+/-|to\b|and\b)\s*\$?\s*{NUMBER}', suffix, re.I):
        return True
    # Conservative compound-unit boundary; unsupported layouts stay unresolved.
    return bool(re.match(r'^(?:per\b|(?:nm|mm|cm|m|s|K|T|A|V|Hz|mol|eV|J|Pa|Ω)\b(?:\^|\s|/|$))', suffix))


def source_literals(text, quantity):
    """Yield exact complete fragments with offsets in the supplied source text."""
    if quantity.status != 'reported' or not quantity.unit:
        return
    seen = set()
    for start_match in START.finditer(text):
        start = start_match.start()
        if continued_before(text[:start]):
            continue
        if start_match[0].startswith(('~','-','−','+')) and re.search(rf'{NUMBER}\s*$', lexical(text[:start])):
            continue
        matches = []
        for end in range(start_match.end() + 1, min(len(text), start + MAX_FRAGMENT) + 1):
            raw = text[start:end]
            if '\n' in raw or ';' in raw or ',' in raw.replace(r'\,', ''):
                break
            if raw[-1].isspace():
                continue
            following = text[end:end+1]
            if following and not (following.isspace() or following in '$.,;:)]}'):
                continue
            if continued_after(text[end:]) or not compatible(raw, quantity):
                continue
            matches.append(end)
        if not matches:
            continue
        end = max(matches)
        if (start,end) in seen:
            continue
        seen.add((start,end))
        yield dict(start_char=start, end_char=end, raw=text[start:end],
                   quote_sha256=sha(text[start:end].encode()), numeric_shape_matched=True,
                   explicit_unit_matched=True)


def context(graph, path, bundle):
    """Use only the target's pre-existing numeric evidence, never all equal values."""
    if not path.endswith('/quantity/raw'):
        return None
    parts = path.strip('/').split('/');data = graph.model_dump();owner = None;owner_path = ''
    value = data
    for index,part in enumerate(parts[:-1]):
        if isinstance(value,dict) and 'evidence' in value:
            owner = value;owner_path = '/'+'/'.join(parts[:index])
        value = value[int(part)] if isinstance(value,list) else value[part]
    quantity = Quantity.model_validate(value)
    quantity_path = '/'+ '/'.join(parts[:-1])
    local = quantity_path[len(owner_path):] if owner is not None else None
    aliases = list(dict.fromkeys(alias for ref in (owner or {}).get('evidence', [])
        if any(field == local or local.startswith(field+'/') for field in ref['fields'])
        for alias in ref['span_ids']))
    catalog = source_catalog(bundle);choices = {};count = 0
    for quote in selected_quotes(catalog, aliases) if aliases else []:
        for candidate in source_literals(quote['quote'], quantity):
            count += 1
            if len(choices) == MAX_CHOICES:
                continue
            start = quote['start_char']+candidate['start_char'];end = quote['start_char']+candidate['end_char']
            spans = [alias for alias in quote['span_ids']
                     if catalog['spans'][alias]['start_char'] < end and catalog['spans'][alias]['end_char'] > start]
            block = next(b for b in bundle.blocks if b.id == quote['block_id'])
            assert block.text[start:end] == candidate['raw']
            choices[f'Q{len(choices)+1}'] = dict(candidate, start_char=start, end_char=end,
                block_id=block.id, block_sha256=block.sha256, document_id=block.document_id,
                source_span_ids=spans)
    identity = {}
    if parts[0] == 'observations':
        observation = graph.observations[int(parts[1])]
        identity = {key:getattr(observation,key) for key in ('id','sample_id','state_id','protocol_id','inventory_item_ids')}
    elif parts[0] == 'states':
        state = graph.states[int(parts[1])];identity = dict(state_id=state.id,sample_id=state.sample_id)
    return dict(policy=POLICY, target_path=path, owner_path=owner_path, identity=identity,
        bundle_sha256=catalog['bundle_sha256'], numeric_evidence_span_ids=aliases,
        frozen_quantity=quantity.model_dump(), frozen_quantity_sha256=digest(quantity.model_dump()),
        choices=choices, compatible_fragments=count, choices_truncated=count>MAX_CHOICES,
        scientific_acceptance=False, independent_gold=False,
        limitation='Finite explicit-unit fragments only; source applicability, prose/table definitions and independent scientific review remain required.')
