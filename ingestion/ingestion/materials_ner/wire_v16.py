"""Inline native-13 transport with closed contexts and scientific schema parity.

Reuses source selection/accounting; it never repairs a model response. Older
transports keep their default projection and generation behavior unchanged.
"""
from copy import deepcopy
from typing import Literal

from pydantic import create_model

from .contract import StrictModel, canonical, digest
from .contract_v13 import ExtractionV13, StateV13
from .inventory import strict_schema
from . import item_stages, wire_v11 as accounting, wire_v13 as literal
from . import wire_v14 as selected_wire, wire_v15 as inline, typed_inventory_v3 as selected
from .wire import output_schema as canonical_schema
from .source_field_stages import _pointer_patterns

WIRE_VERSION = 'materials-ner-inline/2'
PROMPT_VERSION = 'materials-ner-prompt/16.0.0'
PROJECTION_VERSION = 'materials-inline-item-projection/2'
AccountingError = accounting.AccountingError
PressureState = inline.selected_entity('PressureState', StateV13)
SelectedPressureState = selected_wire.narrowed('SelectedPressureState', StateV13)
LiteralPressureState = literal.narrowed('LiteralPressureState', StateV13)


class LiteralPressureExtraction(literal.AdoptedExtraction):
    states: list[LiteralPressureState]


class AdoptedExtraction(selected_wire.AdoptedExtraction):
    schema_version: Literal['materials-ner-adopted/3']
    states: list[SelectedPressureState]

    def expand(self, bundle):
        return super().expand(bundle, canonical_model=ExtractionV13, canonical_version='materials-ner/13')


def validate_coverage(compact, inventory, bundle):
    return selected_wire.validate_coverage(compact, inventory, bundle, literal_model=LiteralPressureExtraction)


class AccountedTransport(selected_wire.AccountedExtraction):
    schema_version: Literal['materials-ner-pressure-accounted/1']
    states: list[SelectedPressureState]

    def project(self, inventory, bundle):
        return accounting.AccountedExtraction.project(self, inventory, bundle,
            projected_model=AdoptedExtraction, projected_version='materials-ner-adopted/3',
            projection_version='materials-result-accounting/5', coverage_validator=validate_coverage)


Base = create_model('PressureInlineBase', __base__=StrictModel,
    **accounting.copied_fields(inline.AccountedExtraction, {'schema_version', 'states', 'context_dispositions'}))


class AccountedExtraction(Base):
    schema_version: Literal[WIRE_VERSION]
    states: list[PressureState]
    context_decisions: dict[str, item_stages.CarriedContext | item_stages.HeldContext]

    parse_response = classmethod(accounting.AccountedExtraction.parse_response.__func__)

    def project(self, inventory, bundle):
        if set(self.context_decisions) != {c.id for c in inventory.context_assertions}:
            raise AccountingError('inline_context_keys_not_closed')
        def transport(data):
            data['schema_version'] = 'materials-ner-pressure-accounted/1'
            data['context_dispositions'] = [dict(context_id=k, **v)
                for k, v in data.pop('context_decisions').items()]
            return AccountedTransport.model_validate(data)
        return inline.AccountedExtraction.project(self, inventory, bundle,
            transport_factory=transport, projection_version=PROJECTION_VERSION)


def _pressure_schema(base):
    branches = []
    for kind in ('ambient', 'numeric', 'unavailable'):
        branch = deepcopy(base)
        p = branch['properties']
        if kind == 'ambient':
            p['availability'] = {'type': 'string', 'enum': ['reported']}
            p['regime'] = {'type': 'string', 'enum': ['explicit_ambient']}
            p['basis_raw'] = {'type': 'string', 'minLength': 1, 'maxLength': 2000}
        elif kind == 'numeric':
            # Unknown regime can still have a source-reported numeric pressure.
            p['availability'] = {'type': 'string', 'enum': ['reported']}
            p['regime'] = {'type': 'string', 'enum': ['nonambient', 'unknown']}
            p['condition_id'] = {'type': 'string', 'minLength': 1, 'maxLength': 100}
            # A basis is useful for both cases and required for a known regime.
            p['basis_raw'] = {'type': 'string', 'minLength': 1, 'maxLength': 2000}
        else:
            p['availability']['enum'].remove('reported')
            p['regime'] = {'type': 'string', 'enum': ['unknown']}
        branches.append(branch)
    return {'anyOf': branches}


def output_schema(bundle=None, inventory=None):
    schema = strict_schema(AccountedExtraction)
    inherited = inline.output_schema(bundle, inventory)
    for name in ('work_id', 'processed_block_ids', 'unread_block_ids', 'decisions'):
        schema['properties'][name] = deepcopy(inherited['properties'][name])
    defs = schema['$defs']
    defs['Quantity'] = deepcopy(canonical_schema()['$defs']['Quantity'])
    defs['PressureDeclaration'] = _pressure_schema(defs['PressureDeclaration'])
    defs['EvidenceReference'] = deepcopy(inherited['$defs']['EvidenceReference'])
    defs['SelectedResult']['properties']['quantity_selection_id'] = deepcopy(
        inherited['$defs']['SelectedResult']['properties']['quantity_selection_id'])
    # Preserve formula missingness restrictions from the existing shared wire.
    defs['IdentitySample'] = deepcopy(selected_wire.output_schema(bundle, inventory)['$defs']['IdentitySample'])
    # Evidence addresses expanded native entities, never transport-only fields.
    native = ExtractionV13.model_json_schema()
    entities = {'IdentitySample': 'samples', 'PressureState': 'states',
        'AdoptedProcedure': 'protocols', 'SampleRelation': 'sample_relations',
        'ConditionSupport': 'condition_supports', 'SelectedResult': 'results'}
    for name, collection in entities.items():
        model = ExtractionV13.model_fields[collection].annotation.__args__[0]
        body = model.model_json_schema()
        properties = deepcopy(body['properties'])
        if collection == 'results':
            properties.pop('definition', None)
        paths = _pointer_patterns(dict(type='object', properties=properties), native['$defs'])
        witness = deepcopy(defs['EvidenceReference'])
        witness['properties']['fields']['items'] = {'type': 'string', 'pattern': '^(?:' + '|'.join(sorted(set(paths))) + ')$'}
        key = name + 'Evidence'
        defs[key] = witness
        branches = defs[name].get('anyOf', [defs[name]])
        for branch in branches:
            branch['properties']['evidence']['items'] = {'$ref': '#/$defs/' + key}
    definition = deepcopy(defs['Definition'])
    paths = _pointer_patterns(definition, defs)
    witness = deepcopy(defs['EvidenceReference'])
    witness['properties']['fields']['items'] = {'type': 'string', 'pattern': '^(?:' + '|'.join(sorted(set(paths))) + ')$'}
    defs['DefinitionEvidence'] = witness
    defs['Definition']['properties']['evidence']['items'] = {'$ref': '#/$defs/DefinitionEvidence'}
    # Quantity source XOR and categorical result constraints also apply before
    # generation, not only in Pydantic validators after the provider call.
    base = defs['SelectedResult']
    branches = []
    for category in ('numeric', 'tc', 'negative'):
        for has_number in (True, False):
            if category == 'negative' and has_number:
                continue
            branch = deepcopy(base)
            p = branch['properties']
            if category == 'numeric':
                p['quantity_kind']['enum'] = [k for k in p['quantity_kind']['enum'] if k not in {'tc', 'non_detection'}]
            elif category == 'tc':
                p['quantity_kind']['enum'] = ['tc']
                p['qualifiers']['items'] = {'anyOf': [{'$ref': '#/$defs/TransitionStage'}, {'$ref': '#/$defs/TemperatureRole'}]}
            else:
                p['quantity_kind']['enum'] = ['non_detection']
                p['qualifiers']['minItems'] = 1
                p['qualifiers']['items'] = {'anyOf': [{'$ref': '#/$defs/NonDetectionV8'}, {'$ref': '#/$defs/ConditionalExistenceV4'}]}
            if has_number:
                p['quantity_selection_id'] = p['quantity_selection_id']['anyOf'][0]
                p['quantity_status'] = {'type': 'null'}
            else:
                p['quantity_selection_id'] = {'type': 'null'}
                p['quantity_status'] = (dict(type='string', enum=['not_applicable']) if category == 'negative'
                    else p['quantity_status']['anyOf'][0])
            branches.append(branch)
    defs['SelectedResult'] = {'anyOf': branches}
    from .wire_v4 import output_schema as conditional_schema
    defs['ConditionalExistenceV4'] = deepcopy(conditional_schema()['$defs']['ConditionalExistenceV4'])
    contexts = [c.id for c in inventory.context_assertions] if inventory is not None else []
    schema['properties']['context_decisions'] = item_stages._keyed(contexts,
        {'anyOf': [{'$ref': '#/$defs/CarriedContext'}, {'$ref': '#/$defs/HeldContext'}]})
    return schema


RULES = '''PRESSURE AND SOURCE CONTEXT CONTRACT:
Use materials-ner-inline/2. Each state has pressure={availability, regime,
condition_id, basis_raw}, matching the existing canonical condition semantics.
An explicitly ambient measurement with no printed pressure number has
availability=reported, regime=explicit_ambient, condition_id=null and literal
basis_raw, with state evidence for /pressure and /pressure/basis_raw. Do not
invent a zero-GPa Quantity. A reported numeric pressure uses an actual pressure
condition with role measurement or simulation and the matching condition_id.
Choose regime only from source evidence, never from a numeric threshold. Missing
or uninspected pressure remains unknown, not ambient. Preserve conflicts.

context_decisions has exactly every fresh first-read context ID. Use carried
with real entity/field bindings, or unresolved/not_applicable with no bindings
and an explanation. Every carried fact must be in the named entity field and
have that field's own source evidence. Result and definition IDs are item:I1,
item:I2, etc. There is no context_dispositions array in this transport.

Evidence fields address expanded native objects: /quantity/value is a result
path, /value is not. Pressure conditions belong to states; method belongs to
protocols; criterion belongs to the result-owned definition. Quantity source
selection automatically supplies numeric evidence, but not scientific ownership.
All *_raw fields are literal source phrases, not summaries of the first read.

Resolve continuous experiment paragraphs across columns and pages using the
original images and source geometry. Track the named run through continuations.
Separate source-scoped assertions for distinct experiments and aggregate/cited
contexts unless the source supports a shared specimen; a common formula or
instrument does not prove shared physical identity. Separate assertions do not
prove physically distinct specimens either. Preserve uncertainty explicitly.

A loading, unloading, calibration or pressure-change temperature is procedure
context. Use condition role unknown and its literal basis_raw when no precise
role is supported by this contract; do not label it synthesis or Tc measurement.
Retain its protocol connection and operation context. Do not invent a numeric
room temperature. Distinguish resistivity, magnetization/susceptibility and
specific heat through method_class while retaining the exact method/observable.

Experimental slopes are not automatically theoretical computations. Distinguish
observed experimental quantities, explicit fitted/model-derived quantities and
computed theoretical quantities using source evidence. If the derivation is
unclear use unknown; derivative notation alone establishes neither a fit nor a
computation. Current/cited aggregates remain mixed/unknown in source_role unless
the source supports separable results. Never manufacture individual specimens
or values from a group summary. Scientific qualification remains pending.
'''
PROMPT_HASH = digest(dict(version=PROMPT_VERSION, inherited=inline.PROMPT_HASH, rules=RULES))


def render(bundle, inventory):
    return inline.render(bundle, inventory).replace(inline.WIRE_VERSION, WIRE_VERSION) + '\n' + RULES


def verify_extraction(receipt, bundle, raw_output):
    return accounting.verify_extraction(receipt, bundle, raw_output, model=AccountedExtraction)
