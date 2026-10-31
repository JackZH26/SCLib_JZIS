"""Source-owned components and measured properties supporting state geometry.

These are sparse proposal relationships, not reviewed canonical identities.
Historical contracts remain unchanged. A condition value is still a literal
source assertion; a support edge does not create a second independent result.
"""
from typing import Literal, get_args

from pydantic import Field, model_validator

from .contract import Evidence, StrictModel
from .contract_v3 import ConditionV3, StateV3
from .contract_v5 import ExtractionV5, ProcedureV5, ResultV5


class ConditionV6(ConditionV3):
    id: str = Field(min_length=1)
    role: Literal["measurement", "synthesis", "simulation", "detection_window", "pump", "sample_geometry", "unknown"]


class StateV6(StateV3):
    conditions: list[ConditionV6]


class ConditionMethodUseV6(StrictModel):
    state_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)


class ProcedureV6(ProcedureV5):
    context_uses: list[ConditionMethodUseV6] = Field(default_factory=list)


class SampleRelationV6(StrictModel):
    id: str = Field(min_length=1)
    from_sample_id: str = Field(min_length=1)
    to_sample_id: str = Field(min_length=1)
    relation: Literal["component_of"]
    relation_raw: str = Field(min_length=1)
    evidence: list[Evidence]


class ConditionSupportV6(StrictModel):
    id: str = Field(min_length=1)
    result_id: str = Field(min_length=1)
    state_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    relation: Literal["measures"]
    relation_raw: str = Field(min_length=1)
    evidence: list[Evidence]


class ResultV6(ResultV5):
    # Total specimen thickness is distinct from superconducting-layer thickness.
    quantity_kind: Literal[tuple(get_args(ResultV5.model_fields["quantity_kind"].annotation)) + ("thickness",)]


def relation_references(samples, states, protocols, results, relations, supports):
    sample_map = {s.id: s for s in samples}
    state_map = {s.id: s for s in states}
    result_map = {r.id: r for r in results}
    for items in (relations, supports):
        if len({x.id for x in items}) != len(items):
            raise ValueError("duplicate_relation_identifier")
    conditions = {}
    for state in states:
        if len({c.id for c in state.conditions}) != len(state.conditions):
            raise ValueError("duplicate_state_condition_identifier")
        conditions.update({(state.id, c.id): c for c in state.conditions})
    for procedure in protocols:
        uses = [(u.state_id, u.condition_id) for u in procedure.context_uses]
        if len(uses) != len(set(uses)) or any(u not in conditions for u in uses):
            raise ValueError("invalid_stable_condition_method_use")
    adjacency = {s.id: [] for s in samples}
    seen = set()
    for relation in relations:
        edge = (relation.from_sample_id, relation.to_sample_id, relation.relation)
        if (edge[0] not in sample_map or edge[1] not in sample_map or edge[0] == edge[1] or edge in seen):
            raise ValueError("invalid_component_relation")
        seen.add(edge); adjacency[edge[0]].append(edge[1])
    visiting, done = set(), set()
    def visit(identifier):
        if identifier in visiting: raise ValueError("cyclic_component_containment")
        if identifier in done: return
        visiting.add(identifier)
        for parent in adjacency[identifier]: visit(parent)
        visiting.remove(identifier); done.add(identifier)
    for identifier in adjacency: visit(identifier)
    seen = set()
    for support in supports:
        edge = (support.result_id, support.state_id, support.condition_id)
        if edge in seen or support.result_id not in result_map or edge[1:] not in conditions:
            raise ValueError("invalid_condition_support_reference")
        seen.add(edge)
        result = result_map[support.result_id]
        if result.state_id != support.state_id or result.sample_id != state_map[support.state_id].sample_id:
            raise ValueError("cross_state_condition_support")


class ExtractionV6(ExtractionV5):
    schema_version: Literal["materials-ner/6"]
    states: list[StateV6]
    protocols: list[ProcedureV6]
    results: list[ResultV6]
    sample_relations: list[SampleRelationV6] = Field(default_factory=list)
    condition_supports: list[ConditionSupportV6] = Field(default_factory=list)

    @model_validator(mode="after")
    def condition_method_references(self):
        # Overrides the old positional condition reference validator.
        relation_references(self.samples, self.states, self.protocols, self.results,
                            self.sample_relations, self.condition_supports)
        return self
