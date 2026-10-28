"""Accounted initial extraction with explicit source-scoped formula missingness."""
from copy import deepcopy
from typing import Literal

from .contract import canonical,digest
from .contract_v9 import SampleV9,ExtractionV9
from .evidence import source_catalog
from .inventory import source_text
from .wire import nested_model
from .wire_v10 import DetectionExtraction
from . import wire_v11 as previous
from .wire_v11 import AccountingError, validate_coverage, inventory_render, inventory_render_repair

WIRE_VERSION='materials-ner-shared/8'
PROMPT_VERSION='materials-ner-prompt/12.0.0'
IdentitySample=nested_model('IdentitySample',SampleV9,set())


class IdentityExtraction(DetectionExtraction):
    schema_version: Literal['materials-ner-identity/1']
    samples: list[IdentitySample]

    def expand(self,bundle):
        # Translate only source aliases. No scientific status, formula or owner
        # is chosen by this adapter; the original transport remains immutable.
        blocks=source_catalog(bundle)['blocks'];copy=self.model_copy(deep=True)
        for sample in copy.samples:
            if sample.formula_unavailability is not None:
                sample.formula_unavailability.checked_block_ids=[blocks[x]['block_id']
                    for x in sample.formula_unavailability.checked_block_ids]
        return DetectionExtraction.expand(copy,bundle,canonical_model=ExtractionV9,canonical_version='materials-ner/9')


class AccountedExtraction(previous.AccountedExtraction):
    schema_version: Literal['materials-ner-shared/8']
    samples: list[IdentitySample]

    def project(self,inventory,bundle):
        return super().project(inventory,bundle,projected_model=IdentityExtraction,
            projected_version='materials-ner-identity/1',projection_version='materials-result-accounting/2')


def output_schema(bundle=None,inventory=None, *, model=AccountedExtraction):
    schema=previous.output_schema(bundle,inventory,model=model)
    base=schema['$defs']['IdentitySample'];reported=deepcopy(base);missing=deepcopy(base)
    reported['properties']['formula_raw']={'type':'string','minLength':1}
    reported['properties']['formula_unavailability']={'type':'null'}
    missing['properties']['formula_raw']={'type':'null'}
    missing['properties']['formula_unavailability']={'$ref':'#/$defs/FormulaUnavailability'}
    missing['properties']['composition_basis']={'type':'string','enum':['unresolved']}
    schema['$defs']['IdentitySample']={'anyOf':[reported,missing]}
    if bundle:
        schema['$defs']['FormulaUnavailability']['properties']['checked_block_ids']['items']['enum']=list(source_catalog(bundle)['blocks'])
    return schema


IDENTITY_RULES='''SOURCE-SCOPED FORMULA MISSINGNESS V12:
Use schema_version materials-ner-shared/8. A source-reported result may have an
unresolved specimen or composition. Do not discard its quantities or invent a
formula/label to satisfy the graph. A sample ID is local bookkeeping, never proof
that two measurements used the same physical specimen or canonical material.

formula_raw is a literal source formula when its association to this subject is
supported. Then formula_unavailability=null. Otherwise formula_raw=null,
composition_basis=unresolved, and formula_unavailability has status,
explanation and checked_block_ids. Status is not_extracted, not_accessible,
ambiguous, conflicted or not_reported_in_supplied_source. Select checked source
BLOCK aliases, not span IDs. These are reading metadata, not chemical facts.
Use ambiguous when a nearby formula exists but applicability to the asserted
specimen is unresolved. Do not use a bibliographic note's primary authorship to
assign a contextual crystal's formula. Keep identity_resolution=unresolved when
the specimen association is unresolved. A named source sample can instead have
source_scoped identity while its formula remains unavailable; identity and
chemical knowledge are separate decisions.

not_reported_in_supplied_source requires every supplied block to have been read
and included in checked_block_ids. It never asserts absence in unprovided parts
of the paper. Missing or unread source is not absence. Unknown, unspecified,
sample unspecified and similar placeholders are not formulas. Symbolic y is not
zero. Retain independently supported variables/isotopes/alternative formulas,
but do not infer their connection or composition basis from proximity.

An anonymous source-scoped subject may have label=null, formula_raw=null,
target_kind=unresolved and identity_resolution=unresolved with appropriate
formula_unavailability. Keep separate result conditions and source attribution.
Bind the result's sample/state references to the actual assertion, not another
sample's formula. If even a source-scoped subject connection is unsupported,
retain the original source item as held with the specific unresolved relation.
Do not bind positive evidence to absent formula_raw or invented descriptions.
Unresolved identity/formula is excluded from composition-based ML qualification.
'''
PROMPT_HASH=digest({'version':PROMPT_VERSION,'previous_prompt':previous.PROMPT_HASH,'identity':IDENTITY_RULES})


def render(bundle,inventory):
    return previous.render(bundle,inventory).replace(previous.WIRE_VERSION,WIRE_VERSION)+'\n'+IDENTITY_RULES


def verify_extraction(receipt,bundle,raw_output):
    return previous.verify_extraction(receipt,bundle,raw_output,model=AccountedExtraction)
