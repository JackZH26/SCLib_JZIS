"""Source-authored development comparison, never an independent Gold claim.

References enter only after extraction. Matching depends on original occurrence
identity, not candidate values, row order or arbitrary result identifiers.
"""
from . import paper_coverage
from .contract import Quantity, canonical
from .quantities_v2 import normalize


def pressure(state):
    values = [c for c in state['conditions'] if c['kind'] == 'pressure' and c['role'] == 'measurement']
    if len(values) != 1:
        return None, None
    c = values[0]
    q = c['quantity']
    if q['status'] != 'reported' or q['relation'] != 'exact' or q.get('approximate'):
        return None, c['role']
    try:
        return normalize('pressure', Quantity.model_validate(q))['normalized']['value'], c['role']
    except (ValueError, KeyError):
        return None, c['role']


def witnesses(result, bundle):
    blocks = {b.id:b for b in bundle.blocks}
    # A row-level /quantity witness supplies context; an explicit raw-cell
    # witness is the more precise occurrence. Do not union it with the row.
    field = '/quantity/raw' if any(e['field'] == '/quantity/raw' for e in result['evidence']) else '/quantity'
    for e in result['evidence']:
        if e['field'] != field:
            continue
        block = blocks.get(e['block_id'])
        quote = e['quote']
        if block is None or not quote:
            continue
        if 'start_char' in e and 'end_char' in e:
            a, z = e['start_char'], e['end_char']
        else:
            if block.text.count(quote) != 1:
                continue
            a = block.text.index(quote)
            z = a + len(quote)
        if type(a) is int and type(z) is int and 0 <= a < z <= len(block.text) and block.text[a:z] == quote:
            yield dict(block_id=block.id, start_char=a, end_char=z, quote=quote)


def assess(reference, graph, bundle):
    if (reference.get('schema') != 'materials-development-source-tuples/1'
            or reference['work_id'] != bundle.work_id or graph['work_id'] != bundle.work_id
            or reference['original']['sha256'] not in {d.source_sha256 for d in bundle.documents}
            or reference.get('independent_gold') is not False):
        raise ValueError('development_reference_source_identity')
    samples = {x['id']:x for x in graph['samples']}
    states = {x['id']:x for x in graph['states']}
    results = {x['id']:x for x in graph['results']}
    if len(results) != len(graph['results']):
        raise ValueError('development_duplicate_result_id')
    def parent_tuple(identifier):
        rr = results[identifier]
        pp, _ = pressure(states[rr['state_id']])
        return dict(kind=rr['quantity_kind'], value=rr['quantity']['value'], unit=rr['quantity']['unit'], pressure_gpa=pp)
    checked = []
    matched_ids = set()
    for ref in reference['tuples']:
        anchor = ref['original_quantity_anchor']
        paper_coverage.anchor(anchor, bundle)
        candidates = [x for x in graph['results'] if paper_coverage.inside(anchor, list(witnesses(x, bundle)))]
        if len(candidates) != 1:
            checked.append(dict(assertion_id=ref['assertion_id'], matched=False,
                reason='missing_or_ambiguous_source_occurrence', candidate_count=len(candidates)))
            continue
        result = candidates[0]
        matched_ids.add(result['id'])
        q = result['quantity']
        p_gpa, role = pressure(states[result['state_id']])
        definition = result['definition']
        fraction = next((x['quantity'] for x in definition['parameters'] if x['kind'] == 'resistance_fraction'), None)
        actual = dict(formula=samples[result['sample_id']]['formula_raw'], kind=result['quantity_kind'],
            value=q['value'], unit=q['unit'], pressure_gpa=p_gpa, pressure_role=role,
            source_role=result['source_role'], origin=result['origin'], criterion=definition['criterion'],
            resistance_fraction_percent=fraction['value'] if fraction and fraction['unit'] == '%' else None,
            derived_from=sorted([parent_tuple(x['result_id']) for x in result['dependencies'] if x['relation'] == 'derived_from'], key=canonical))
        expected = dict(ref['expected'])
        if set(expected) != set(actual):
            raise ValueError('development_reference_tuple_fields')
        expected['derived_from'] = sorted(expected['derived_from'], key=canonical)
        mismatches = [key for key in expected if actual[key] != expected[key]]
        checked.append(dict(assertion_id=ref['assertion_id'], result_id=result['id'], matched=not mismatches,
            mismatched_fields=mismatches, actual=actual))
    return dict(rows=checked, matched=sum(x['matched'] for x in checked), reference_tuples=len(checked),
        candidates_outside_reference=sorted(set(results)-matched_ids),
        independent_gold=False, scientific_acceptance=False, production_semantic_verifier=False,
        accuracy_or_recall_estimate=False, scope='Only the source-authored development tuples supplied to this comparison.')
