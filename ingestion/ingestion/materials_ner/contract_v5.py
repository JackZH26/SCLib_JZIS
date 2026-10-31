"""Native shared procedures, result-owned definitions and condition-method uses.

No extra material-wide columns or fictitious measurements are needed to retain
a method supporting a sample condition. Unassigned declarations remain proposals.
"""
from typing import Literal

from pydantic import Field, model_validator

from .contract import Evidence, StrictModel
from .contract_v2 import ProtocolParameter
from .contract_v3 import CriterionKind, ProtocolParameterV3
from .contract_v4 import ExtractionV4, ResultV4


class ConditionMethodUse(StrictModel):
    state_id: str = Field(min_length=1)
    condition_index: int = Field(ge=0)


class ProcedureV5(StrictModel):
    id: str = Field(min_length=1)
    method: str | None
    method_class: Literal["resistivity", "magnetization", "specific_heat", "tunneling",
                          "muon_spin", "calculation", "other", "unspecified"]
    observable: str | None
    details_raw: str | None
    parameters: list[ProtocolParameter]
    context_uses: list[ConditionMethodUse] = Field(default_factory=list)
    evidence: list[Evidence]


class DefinitionParameter(ProtocolParameterV3):
    kind: Literal["resistance_fraction"]


class ResultDefinitionV5(StrictModel):
    criterion: CriterionKind
    criterion_raw: str | None
    parameters: list[DefinitionParameter]
    # Evidence belongs to the result, using /definition/criterion and indexed
    # /definition/parameters/N paths. There is only one canonical binding owner.


class ResultV5(ResultV4):
    definition: ResultDefinitionV5


class ExtractionV5(ExtractionV4):
    schema_version: Literal["materials-ner/5"]
    protocols: list[ProcedureV5]
    results: list[ResultV5]

    @model_validator(mode="after")
    def condition_method_references(self):
        states = {s.id: s for s in self.states}
        for procedure in self.protocols:
            uses = [(u.state_id, u.condition_index) for u in procedure.context_uses]
            if len(uses) != len(set(uses)):
                raise ValueError("duplicate_condition_method_use")
            for state_id, index in uses:
                if state_id not in states or index >= len(states[state_id].conditions):
                    raise ValueError("condition_method_target_invalid")
        return self
