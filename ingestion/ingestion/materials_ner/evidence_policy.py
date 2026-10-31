"""Native /13 witness obligations shared by validation and model instructions.

These rules name claims that need evidence; they never assign source facts or
grant scientific acceptance. Legacy graph contracts keep their own behavior.
"""
from .contract import canonical

VERSION = 'materials-field-evidence-policy/1'
COMPONENT_KINDS = ('gap_amplitude_ratio','pairing_component_fraction','nmr_relaxation_power_law_exponent')


def rule(select, *conditions, suffix=''):
    return dict(select=select, suffix=suffix, when=list(conditions))


# Conditions use @ for the selected object and / for the entity root. A '*'
# expands actual array entries; it never creates missing properties or values.
RULES = {
    'sample': [
        rule('/formula_raw', ('@','non_null',None)),
        rule('/composition_basis', ('@','not_equal','unresolved')),
        rule('/isotopes/*'), rule('/variables/*'), rule('/additional_formula_assertions/*'),
        rule('/identity_resolution', ('@','equal','conflicted')),
        rule('/target_kind', ('@','not_equal','unresolved')),
        *[rule('/'+key, ('@','truthy',None)) for key in ('label','form_raw','substrate_raw')],
    ],
    'state': [rule('/sample_id'), rule('/conditions/*', ('@/quantity/status','equal','reported'))],
    'pressure': [rule('/pressure', ('@/availability','equal','reported')),
        rule('/pressure/basis_raw', ('@','non_null',None))],
    'protocol': [rule('/method', ('@','truthy',None)), rule('/method_class', ('@','not_equal','unspecified')),
        rule('/parameters/*'), rule('/context_uses/*')],
    'definition': [rule('/definition/criterion', ('@','not_in',['unspecified','not_applicable'])),
        rule('/definition/criterion_raw', ('@','non_null',None)), rule('/definition/parameters/*')],
    'result': [*[rule('/'+key) for key in ('quantity_kind','sample_id','state_id','protocol_id','origin','source_role')],
        rule('/quantity', ('@/status','equal','reported'))],
    'qualifiers': [rule('/qualifiers/*'), rule('/qualifiers/*', ('@/kind','equal','conditional_existence'),
        ('@/tc_bound/status','equal','reported'), suffix='/tc_bound')],
    'adopted': [rule('/quantity_kind'),rule('/quantity_name_raw')],
    'citation': [rule('/cited_source_raw')],
    'component': [rule('/component_raw')],
    'unmapped': [rule('/quantity_name_raw')],
    'sample_relation': [rule('/'+key) for key in ('from_sample_id','to_sample_id','relation','relation_raw')],
    'condition_support': [rule('/'+key) for key in ('result_id','state_id','condition_id','relation','relation_raw')],
    'non_detection_window': [rule('/qualifiers/*', ('@/kind','equal','non_detection'),
        ('@/window_condition_ids','truthy',None), suffix='/window_condition_ids')],
    'non_detection_sensitivity': [rule('/qualifiers/*/sensitivities/*')],
}


def _expand(value, parts, prefix=''):
    if not parts:
        yield prefix,value
    elif parts[0]=='*':
        if isinstance(value,list):
            for i,entry in enumerate(value):yield from _expand(entry,parts[1:],prefix+'/'+str(i))
    elif isinstance(value,dict) and parts[0] in value:
        yield from _expand(value[parts[0]],parts[1:],prefix+'/'+parts[0])


def _get(value, path):
    for key in path.lstrip('/').split('/') if path else []:
        if not isinstance(value,dict) or key not in value:return None
        value=value[key]
    return value


def required(stage, entity):
    body=entity.model_dump() if hasattr(entity,'model_dump') else entity
    result=[]
    for policy in RULES[stage]:
        for path,selected in _expand(body,policy['select'].lstrip('/').split('/')):
            passed=True
            for selector,operator,expected in policy['when']:
                value=_get(selected,selector[1:]) if selector.startswith('@') else _get(body,selector)
                checks={'non_null':value is not None,'truthy':bool(value),
                    'equal':value==expected,'not_equal':value!=expected,
                    'not_in':value not in expected if isinstance(expected,list) else False}
                if operator not in checks:raise ValueError('unknown_evidence_policy_operator')
                passed=passed and checks[operator]
            if passed:result.append(path+policy['suffix'])
    return result


def raw_fields(value,pointer=''):
    """Source-raw assertions, excluding numerical raw and evidence metadata."""
    if isinstance(value,dict):
        for name,item in value.items():
            if name=='evidence':continue
            path=pointer+'/'+name
            if name.endswith('_raw') and item is not None:yield path,item
            yield from raw_fields(item,path)
    elif isinstance(value,list):
        for i,item in enumerate(value):yield from raw_fields(item,pointer+'/'+str(i))


def render():
    from .field_quantity import POLICY
    from .quantities_v2 import ADDITIONS
    return '''
FIELD EVIDENCE CONTRACT (shared with the native validator)
Each applicable rule below requires an evidence item at that exact entity-relative pointer. A child binding does not automatically satisfy its parent, and a sibling binding never satisfies another claim. Reuse a source passage only by explicitly binding it to each claim that it actually supports. Keep optional source fields null when no literal source wording is available; do not add a label or explanation that creates an unsupported assertion.
The rule table uses '*' for each existing array element. '@' means the selected object; '/' means the entity root. Operators are equal, not_equal, not_in, non_null and truthy. Apply sample to samples, state/pressure to states, protocol to protocols, definition/result/qualifiers to results, and relation rules to their corresponding collections. The adopted rule applies to registry-adopted kinds; citation applies when cited_source_raw is present, component when a component-specific kind requires it, and unmapped to unmapped quantities. Non-detection rules apply only to the explicit non-detection target.
''' + canonical(RULES) + '\nAdopted quantity kinds: ' + canonical(sorted(ADDITIONS)) + \
        '\nComponent-specific kinds: ' + canonical(COMPONENT_KINDS) + '''
Every non-null *_raw string must be a verbatim source substring, supported by evidence for that field or its enclosing object. A criterion_raw string specifically needs its own /definition/criterion_raw witness. Interpretive summaries belong in limitations, not in *_raw fields. Labels, methods and categories must still have source support.
For a reported quantity, bind the complete /quantity assertion and, when value and unit are separated in the source, bind /quantity/raw and /quantity/unit separately as well. The unit-only witness must quote the unit expression itself, not the whole table header. The same rule applies to condition and parameter quantities using their nested pointers. Preserve numeric signs, uncertainties and bounds. Do not manufacture an inline value-plus-unit string from two source locations.
A short quote may be disambiguated with context_quote, a longer verbatim passage from the SAME supplied block that contains that quote once. This optional provider-only selector locates the exact short quote; it is not scientific evidence for other fields. Otherwise use an unambiguous quote or accurate original offsets. Never estimate offsets or alter source characters. This selector is removed only after deterministic resolution to native original coordinates.
Shared quantity policy: ''' + POLICY + '\n'
