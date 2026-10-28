"""Source-tested property adoption with the positioned native evidence shape.

No per-property columns or optional payload fields are added. Existing source
names, definitions, conditions and dependencies carry the scientific context.
"""
from typing import Literal, get_args
from pydantic import model_validator

from .contract_v11 import ExtractionV11, ResultV11
from .quantities_v2 import ADDITIONS

VERSION = 'materials-ner/12'


class ResultV12(ResultV11):
    quantity_kind: Literal[tuple(get_args(ResultV11.model_fields['quantity_kind'].annotation)) + tuple(ADDITIONS)]

    @model_validator(mode='after')
    def explicit_new_property_name(self):
        if self.quantity_kind in ADDITIONS and not (self.quantity_name_raw and self.quantity_name_raw.strip()):
            raise ValueError('adopted_quantity_requires_source_property_name')
        return self


class ExtractionV12(ExtractionV11):
    schema_version: Literal[VERSION]
    results: list[ResultV12]
