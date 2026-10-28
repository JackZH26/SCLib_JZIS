"""Provider-facing constraints for explicitly selected native science contracts.

Only structural invariants belong here. Source meaning, foreign keys, quantity
semantics and actual pointer/quote resolution remain native validation gates.
"""
from copy import deepcopy
import re

from .contract_v13 import ExtractionV13
from .contract_v14 import ExtractionV14
from .contract_v15 import ExtractionV15, DESCRIPTORS, INTERSECTION
from .contract_v8 import TARGET_OBSERVABLES
from .inventory import strict_schema
from .quantities_v2 import ADDITIONS as V12_NAMES
from .quantities_v3 import ADDITIONS as V14_NAMES

VERSION = 'materials-source-projector-interface/5'
NATIVE14_VERSION = 'materials-source-projector-interface/6'
CONSOLIDATED_NATIVE14_VERSION = 'materials-source-projector-interface/7'
NATIVE15_VERSION = 'materials-source-projector-interface/8'
GROUPS = ('samples', 'states', 'protocols', 'results', 'sample_relations', 'condition_supports')


def interface_version(graph_schema, selected=None):
    if graph_schema == 'materials-ner/13':
        versions = [VERSION]
    elif graph_schema == 'materials-ner/14':
        versions = [NATIVE14_VERSION, CONSOLIDATED_NATIVE14_VERSION]
    elif graph_schema == 'materials-ner/15':
        versions = [NATIVE15_VERSION]
    else:
        raise ValueError('projector_unsupported_graph_contract')
    if selected is not None and selected not in versions:
        raise ValueError('projector_unsupported_interface')
    return selected if selected is not None else versions[0]


def _dereference(node, definitions):
    return definitions[node['$ref'].removeprefix('#/$defs/')] if '$ref' in node else node


def _children(node, definitions):
    """Regex suffix for real schema properties and canonical array indices.

    This constrains the address language, not whether the selected value exists
    or is non-null in a particular model output. The native validator does that.
    """
    node = _dereference(node, definitions)
    if 'anyOf' in node:
        choices = sorted(set(_children(child, definitions) for child in node['anyOf']) - {''})
        return '(?:' + '|'.join(choices) + ')' if choices else ''
    if node.get('type') == 'object':
        choices = []
        for key, child in node['properties'].items():
            if key == 'evidence':
                continue
            escaped = re.escape(key.replace('~', '~0').replace('/', '~1'))
            suffix = _children(child, definitions)
            choices.append(escaped + ('(?:' + suffix + ')?' if suffix else ''))
        return '/(?:' + '|'.join(choices) + ')' if choices else ''
    if node.get('type') == 'array':
        suffix = _children(node['items'], definitions)
        return '/(?:0|[1-9][0-9]*)' + ('(?:' + suffix + ')?' if suffix else '')
    return ''


def _pressure_branches(original):
    """Mirror PressureDeclaration's three cross-field invariants, without if.

    Do not require a number for explicit ambient or an unknown declaration.
    Condition identity and status matching cannot be expressed by this schema.
    """
    available = original['properties']['availability']['enum']
    branches = []
    for status, regime, condition_required, basis_required in [
        (['reported'], 'explicit_ambient', False, True),
        (['reported'], 'nonambient', True, True),
        (['reported'], 'unknown', True, False),
        ([s for s in available if s != 'reported'], 'unknown', False, False),
    ]:
        branch = deepcopy(original)
        props = branch['properties']
        props['availability'] = dict(type='string', enum=status)
        props['regime'] = dict(type='string', const=regime)
        for key, required in [('condition_id', condition_required), ('basis_raw', basis_required)]:
            if required:
                props[key] = next(deepcopy(x) for x in props[key]['anyOf'] if x.get('type') == 'string')
        if basis_required:
            props['basis_raw']['pattern'] = r'\S'
        branches.append(branch)
    return dict(anyOf=branches, description=(
        'Source-supported pressure declaration. Nonambient needs an identified measurement or simulation '
        'condition and a nonblank verbatim source basis. Explicit ambient needs a source basis but '
        'need not invent a numeric condition. Unreported pressure remains unknown.'))


def _quantity_branches(original):
    """Mirror native Quantity.shape without adding scientific requirements.

    Relative interval ordering cannot be expressed in this provider schema and
    remains a native check. Unavailable quantities may retain a raw/unit string;
    they must not select a value, a bound, a relation or an uncertainty.
    """
    shapes = {'exact': {'value'}, 'interval': {'lower', 'upper'},
        'lt': {'upper'}, 'le': {'upper'}, 'gt': {'lower'}, 'ge': {'lower'}}
    branches = []
    for relation, selected in shapes.items():
        branch = deepcopy(original); props = branch['properties']
        props['status'] = dict(type='string', const='reported')
        props['relation'] = dict(type='string', const=relation)
        for key in ('value','lower','upper'):
            props[key] = dict(type='number' if key in selected else 'null')
        for key in ('raw','unit'):
            props[key] = dict(type='string', minLength=1)
        branches.append(branch)
    unavailable = deepcopy(original); props = unavailable['properties']
    props['status'] = dict(type='string', enum=[s for s in props['status']['enum'] if s!='reported'])
    for key in ('value','lower','upper','relation','uncertainty'):
        props[key] = dict(type='null')
    branches.append(unavailable)
    return dict(anyOf=branches, description=(
        'Reported numeric shapes are mutually exclusive: exact uses value only; '
        'interval uses lower and upper; lt/le use upper only; gt/ge use lower only. '
        'Missing statuses select no numeric shape. Native validation also checks interval ordering.'))


def _literal_basis_branches(original, selector, value, literal):
    """Mirror a selected native kind/role's nonblank source-literal requirement."""
    ordinary, selected = deepcopy(original), deepcopy(original)
    ordinary['properties'][selector]['enum'].remove(value)
    selected['properties'][selector] = dict(type='string', const=value)
    selected['properties'][literal] = dict(type='string', minLength=1, pattern=r'\S')
    return dict(anyOf=[ordinary, selected])


def _formula_branches(original):
    # Reuse wire_v12's present/unavailable invariant without its old workflow.
    reported, missing = deepcopy(original), deepcopy(original)
    reported['properties']['formula_raw'] = dict(type='string', minLength=1, pattern=r'\S')
    reported['properties']['formula_unavailability'] = dict(type='null')
    missing['properties']['formula_raw'] = dict(type='null')
    missing['properties']['formula_unavailability'] = {'$ref': '#/$defs/FormulaUnavailability'}
    missing['properties']['composition_basis'] = dict(type='string', const='unresolved')
    return dict(anyOf=[reported, missing])


def _condition_branches(original, extra_basis_kinds=()):
    # Two independent native requirements. Neither adds a scientific claim.
    ordinary, field, extrapolation = [deepcopy(original) for _ in range(3)]
    basis_kinds = ['reported_magnetic_field', *extra_basis_kinds]
    for kind in basis_kinds:
        ordinary['properties']['kind']['enum'].remove(kind)
    ordinary['properties']['role']['enum'].remove('extrapolation_target')
    field['properties']['kind'] = (dict(type='string', enum=basis_kinds) if extra_basis_kinds
        else dict(type='string', const='reported_magnetic_field'))
    for kind in basis_kinds:
        extrapolation['properties']['kind']['enum'].remove(kind)
    extrapolation['properties']['role'] = dict(type='string', const='extrapolation_target')
    for branch in [field, extrapolation]:
        branch['properties']['basis_raw'] = dict(type='string', minLength=1, pattern=r'\S')
    return dict(anyOf=[ordinary, field, extrapolation])


def _non_detection_branches(original):
    branches = []
    statuses = original['properties']['window_status']['enum']
    for target, observables in TARGET_OBSERVABLES.items():
        for reported in [False, True]:
            branch = deepcopy(original); props = branch['properties']
            props['target'] = dict(type='string', const=target)
            props['observable'] = dict(type='string', enum=sorted(observables))
            props['window_status'] = dict(type='string', enum=['reported'] if reported else
                [status for status in statuses if status != 'reported'])
            props['window_condition_ids']['minItems' if reported else 'maxItems'] = 1 if reported else 0
            branches.append(branch)
    # Duplicate references and actual state ownership remain native checks.
    return dict(anyOf=branches)


def _result_branches(original, unavailable_quantity):
    named = set(V12_NAMES) | set(V14_NAMES)
    kinds = original['properties']['quantity_kind']['enum']
    groups = [(set(kinds) - named - {'unmapped', 'non_detection'}, None),
        (named, dict(type='string', minLength=1, pattern=r'\S')),
        ({'unmapped'}, dict(type='string', minLength=1)), ({'non_detection'}, None)]
    branches = []
    for selected, name_schema in groups:
        branch = deepcopy(original); props = branch['properties']
        props['quantity_kind'] = dict(type='string', enum=[kind for kind in kinds if kind in selected])
        if name_schema is not None:
            props['quantity_name_raw'] = name_schema
        if selected == {'non_detection'}:
            props['quantity'] = deepcopy(unavailable_quantity)
            props['quantity']['properties']['status'] = dict(type='string', const='not_applicable')
        else:
            props['qualifiers']['items']['anyOf'] = [item for item in props['qualifiers']['items']['anyOf']
                if item.get('$ref') != '#/$defs/NonDetectionV8']
        # Exactly one negative qualifier and its target/conditional-Tc relation
        # need array-content/relational checks; this schema does not claim them.
        branches.append(branch)
    return dict(anyOf=branches)


def _consolidate_native14(schema, *, condition_name='ConditionV14', result_name='ResultV14', extra_basis_kinds=()):
    definitions = schema['$defs']
    for group in ('samples', 'states', 'protocols', 'results'):
        entity = _dereference(schema['properties'][group]['items'], definitions)
        entity['properties']['id'] = dict(type='string', minLength=1, pattern=r'\S')
    sample_name = schema['properties']['samples']['items']['$ref'].removeprefix('#/$defs/')
    definitions[sample_name] = _formula_branches(definitions[sample_name])
    definitions['FormulaUnavailability']['properties']['checked_block_ids']['items'] = dict(type='string', minLength=1, pattern=r'\S')
    definitions[condition_name] = _condition_branches(definitions[condition_name], extra_basis_kinds)
    definitions['NonDetectionV8'] = _non_detection_branches(definitions['NonDetectionV8'])
    definitions[result_name] = _result_branches(definitions[result_name], definitions['Quantity']['anyOf'][-1])
    definitions[sample_name]['description'] = (
        'A source formula and an unavailability assertion are mutually exclusive. '
        'Unknown and similar placeholders are not chemical formulas. Checked block IDs '
        'describe the actual supplied reading scope; missing source is not source absence.')
    state = _dereference(schema['properties']['states']['items'], definitions)
    state['description'] = (
        'sample_id must name a supplied sample. A non-null pressure.condition_id names exactly '
        'one condition in this state, with kind pressure, role measurement or simulation, and '
        'quantity.status equal to pressure.availability. An explicitly ambient statement may '
        'use condition_id null without any numeric condition. Do not invent zero pressure.')
    procedure = _dereference(schema['properties']['protocols']['items'], definitions)
    procedure['properties']['method_class']['description'] = (
        'The controlled class must agree with the source method. If no listed class applies, '
        'use other and retain the source-supported method; do not choose a superficially similar class.')
    procedure['properties']['context_uses']['description'] = (
        'Every state/condition pair must exist in the supplied states and refer to the actual '
        'procedure context; no duplicate pairs. Identifier validity does not establish applicability.')
    definitions[result_name]['description'] = (
        'sample_id, state_id and protocol_id must name supplied entities; the state belongs to '
        'that sample. Dependencies name other supplied results and contain no derivation cycle. '
        'Do not invent a missing procedure or scientific parent to satisfy references. '
        'Preserve comparison denominators and comparator identity using source-supported existing '
        'definitions/parameters/dependencies, or keep the comparison unmapped. '
        'A non_detection result requires exactly one non_detection qualifier and no selected '
        'numeric quantity; a device non-detection does not establish a conditional superconducting Tc.')


def output_schema(*, require_context_quote=False, source_catalog=None, graph_schema='materials-ner/13', selected_interface=None):
    selected = interface_version(graph_schema, selected_interface)
    if source_catalog is not None and require_context_quote:
        raise ValueError('projector_conflicting_evidence_transports')
    schema = strict_schema({'materials-ner/13': ExtractionV13, 'materials-ner/14': ExtractionV14,
        'materials-ner/15': ExtractionV15}[graph_schema])
    definitions = schema['$defs']
    # Derive address patterns before replacing pressure with its alternatives.
    for group in GROUPS:
        entity = _dereference(schema['properties'][group]['items'], definitions)
        pattern = '^' + _children(entity, definitions) + '$'
        if source_catalog is not None:
            name = group + 'SourceSelection'
            definitions[name] = dict(type='object', additionalProperties=False,
                required=['field', 'witness_ids'], properties=dict(
                    field=dict(type='string', pattern=pattern,
                        description='Exact entity-relative pointer to the supported claim.'),
                    witness_ids=dict(type='array', minItems=1, items=dict(type='string',
                        enum=list(source_catalog['spans'])))))
            entity['properties']['evidence']['items'] = {'$ref': '#/$defs/' + name}
            continue
        evidence_types = []
        for choice in entity['properties']['evidence']['items']['anyOf']:
            evidence = deepcopy(_dereference(choice, definitions))
            name = group + evidence['title']
            evidence['properties']['field'] = dict(type='string', pattern=pattern,
                description='JSON pointer relative to this entity. Array elements use numeric indices. '
                    'Do not prefix a collection or entity ID. Select the exact supported non-null property.')
            definitions[name] = evidence
            evidence_types.append({'$ref': '#/$defs/' + name})
        contextual = deepcopy(definitions[group+'Evidence'])
        contextual['title'] = 'ContextEvidence'
        contextual['properties']['context_quote'] = dict(type='string',minLength=1,
            description='A longer verbatim passage in the same supplied block containing quote exactly once. '
                'Optional transport selector for locating a short quote; never a replacement scientific claim.')
        contextual['required'].append('context_quote')
        definitions[group+'ContextEvidence'] = contextual
        contextual_reference={'$ref':'#/$defs/'+group+'ContextEvidence'}
        evidence_types=[contextual_reference] if require_context_quote else evidence_types+[contextual_reference]
        entity['properties']['evidence']['items'] = dict(anyOf=evidence_types)
    definitions['PressureDeclaration'] = _pressure_branches(definitions['PressureDeclaration'])
    definitions['Quantity'] = _quantity_branches(definitions['Quantity'])
    if selected == NATIVE15_VERSION:
        _consolidate_native14(schema, condition_name='ConditionV15', result_name='ResultV15', extra_basis_kinds=DESCRIPTORS)
        definition = _literal_basis_branches(definitions['DefinitionV15'], 'criterion', INTERSECTION, 'criterion_raw')
        definition['anyOf'][1]['properties']['parameters']['maxItems'] = 0
        definitions['DefinitionV15'] = definition
    elif selected == CONSOLIDATED_NATIVE14_VERSION:
        _consolidate_native14(schema)
    elif graph_schema == 'materials-ner/14':
        definitions['ConditionV14'] = _literal_basis_branches(definitions['ConditionV14'],
            'role', 'extrapolation_target', 'basis_raw')
        definitions['ResultV14'] = _literal_basis_branches(definitions['ResultV14'],
            'quantity_kind', 'inverse_square_penetration_depth', 'quantity_name_raw')
    return schema
