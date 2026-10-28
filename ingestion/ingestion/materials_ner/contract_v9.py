"""Source-scoped formula missingness without inventing chemical identity."""
from typing import Literal

from pydantic import Field, model_validator

from .contract import StrictModel
from .contract_v2 import SampleV2
from .contract_v8 import ExtractionV8


class FormulaUnavailability(StrictModel):
    status: Literal['not_extracted', 'not_accessible', 'not_reported_in_supplied_source',
                    'ambiguous', 'conflicted']
    explanation: str = Field(min_length=1)
    # This is a reading scope, not positive evidence that a paper lacks a formula.
    # Canonical extraction uses source block IDs; transport uses source aliases.
    checked_block_ids: list[str]


class SampleV9(SampleV2):
    formula_raw: str | None = Field(min_length=1)
    formula_unavailability: FormulaUnavailability | None = None

    @model_validator(mode='after')
    def formula_shape(self):
        if (self.formula_raw is None) != (self.formula_unavailability is not None):
            raise ValueError('formula_value_missingness_mismatch')
        if self.formula_raw is None and self.composition_basis != 'unresolved':
            raise ValueError('missing_formula_cannot_have_selected_basis')
        if self.formula_raw is not None and self.formula_raw.strip().casefold() in {
            '', 'unknown', 'unspecified', 'unresolved', 'not reported', 'not stated',
            'sample unspecified', 'n/a', 'none', 'null'}:
            raise ValueError('formula_placeholder_is_not_chemistry')
        if self.formula_unavailability is not None:
            ids=self.formula_unavailability.checked_block_ids
            if len(ids)!=len(set(ids)) or any(not x.strip() for x in ids):
                raise ValueError('formula_checked_scope_invalid')
        return self


class ExtractionV9(ExtractionV8):
    schema_version: Literal['materials-ner/9']
    samples: list[SampleV9]

    @model_validator(mode='after')
    def formula_scope(self):
        processed=set(self.processed_block_ids)
        for sample in self.samples:
            gap=sample.formula_unavailability
            if gap is None:continue
            checked=set(gap.checked_block_ids)
            if not checked<=processed:
                raise ValueError('formula_checked_scope_not_read')
            if gap.status=='not_reported_in_supplied_source' and (
                not checked or checked!=processed or self.unread_block_ids):
                raise ValueError('formula_source_absence_requires_complete_supplied_scope')
        return self
