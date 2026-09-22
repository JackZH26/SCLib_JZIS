"""Closed saved-answer evidence, not regeneration or present-day admission."""
from __future__ import annotations

import json
import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.search import AskRequest, AskResponse

VERSION = "ask-answer-evidence/1.0.0"
MAX_BYTES = 1024 * 1024
EXCLUDED_RESPONSE_FIELDS = frozenset({"history", "guest_remaining", "remaining"})


def canonical(value):
    """Bound JSON before encoding. SQL supplies the final numeric spelling."""
    pending, nodes, characters = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 100000 or depth > 24:
            raise ValueError("answer_evidence_resource_limit")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("answer_evidence_json_shape")
            characters += sum(len(key) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            characters += len(item)
        elif item is not None and type(item) not in {int, float, bool}:
            raise ValueError("answer_evidence_json_shape")
        elif type(item) is float and not math.isfinite(item):
            raise ValueError("answer_evidence_nonfinite_number")
        if characters > MAX_BYTES:
            raise ValueError("answer_evidence_resource_limit")
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("answer_evidence_resource_limit")
    return payload


def _uuid(value):
    if value is not None and (type(value) is not str or str(UUID(value)) != value):
        raise ValueError("answer_evidence_uuid")
    return value


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AnswerEvidenceItem(Closed):
    kind: Literal["source", "scientific_result"]
    position: int = Field(ge=1, le=20)
    paper_id: str = Field(min_length=1, max_length=100)
    chunk_id: str = Field(min_length=1, max_length=200)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_record_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_revision_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    vector_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_revision_id: str | None
    evidence_record_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    parent_result_revision_id: str | None
    parent_result_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    selection_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_generation_pin_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    selection_grouping_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    has_evidence_pin: bool

    @field_validator("evidence_revision_id", "parent_result_revision_id")
    @classmethod
    def identifiers(cls, value):
        return _uuid(value)

    @model_validator(mode="after")
    def paired_hashes(self):
        for identifier, digest in ((self.evidence_revision_id, self.evidence_record_sha256),
                                   (self.parent_result_revision_id, self.parent_result_sha256)):
            if (identifier is None) != (digest is None):
                raise ValueError("answer_evidence_incomplete_identity")
        if self.parent_result_revision_id is not None and self.evidence_revision_id is None:
            raise ValueError("answer_evidence_parent_without_evidence")
        if not self.has_evidence_pin and self.evidence_revision_id is not None:
            raise ValueError("answer_evidence_descriptor_pin_missing")
        return self


class AnswerEvidenceBindings(Closed):
    version: Literal["ask-answer-evidence/1.0.0"] = VERSION
    mode: Literal["no_selected_evidence", "generation_bound", "snapshot_only"]
    generation_id: str | None
    activation_event_id: str | None
    manifest_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    items: list[AnswerEvidenceItem] = Field(max_length=20)

    @field_validator("generation_id", "activation_event_id")
    @classmethod
    def identifiers(cls, value):
        return _uuid(value)

    @model_validator(mode="after")
    def complete_bindings(self):
        generation = self.generation_id is not None
        if generation != (self.activation_event_id is not None) or generation != (self.manifest_sha256 is not None):
            raise ValueError("answer_evidence_generation_incomplete")
        expected_mode = "no_selected_evidence" if not self.items else "generation_bound" if generation else "snapshot_only"
        if self.mode != expected_mode or len({item.chunk_id for item in self.items}) != len(self.items):
            raise ValueError("answer_evidence_inventory_mismatch")
        expected_order = sorted(self.items, key=lambda item: (item.kind != "source", item.position))
        if self.items != expected_order:
            raise ValueError("answer_evidence_inventory_order")
        for kind in ("source", "scientific_result"):
            positions = [item.position for item in self.items if item.kind == kind]
            if positions != list(range(1, len(positions) + 1)):
                raise ValueError("answer_evidence_position_mismatch")
        for item in self.items:
            fields = (item.member_record_sha256, item.chunk_revision_sha256, item.vector_sha256,
                      item.source_snapshot_sha256, item.selection_generation_pin_sha256)
            if generation:
                if any(value is None for value in fields) or item.evidence_revision_id is None or not item.has_evidence_pin:
                    raise ValueError("answer_evidence_member_incomplete")
                if item.chunk_id != "ig62_" + UUID(self.generation_id).hex + "_" + item.chunk_revision_sha256:
                    raise ValueError("answer_evidence_member_generation_mismatch")
            elif any(value is not None for value in fields) or item.kind == "scientific_result":
                raise ValueError("answer_evidence_legacy_generation_claim")
            if item.kind == "scientific_result" and item.parent_result_revision_id is None:
                raise ValueError("answer_evidence_scientific_parent_missing")
        return self


def validate_request(value):
    canonical(value)
    if type(value) is not dict or set(value) != set(AskRequest.model_fields):
        raise ValueError("answer_evidence_request_fields")
    result = AskRequest.model_validate(value, strict=True).model_dump(mode="json")
    if canonical(result) != canonical(value):
        raise ValueError("answer_evidence_request_coercion")
    return result


def validate_response(value):
    canonical(value)
    expected = set(AskResponse.model_fields) - EXCLUDED_RESPONSE_FIELDS
    if type(value) is not dict or set(value) != expected:
        raise ValueError("answer_evidence_response_fields")
    result = AskResponse.model_validate(value, strict=True).model_dump(mode="json", exclude=EXCLUDED_RESPONSE_FIELDS)
    # Equality of the canonical round trip catches ignored nested extra fields
    # and coercions in legacy DTOs, while retaining their declared metadata.
    if canonical(result) != canonical(value):
        raise ValueError("answer_evidence_response_coercion")
    if len(result["sources"]) + len(result["scientific_results"]) > 20:
        raise ValueError("answer_evidence_selection_limit")
    return result


def validate_body(request, response, bindings):
    request, response = validate_request(request), validate_response(response)
    model = AnswerEvidenceBindings.model_validate(bindings, strict=True)
    bindings = model.model_dump(mode="json")
    if len(model.items) > request["max_sources"]:
        raise ValueError("answer_evidence_requested_limit")
    if response["scientific_query"] is not None and response["scientific_query"]["raw_query"] != request["question"]:
        raise ValueError("answer_evidence_question_mismatch")
    generation = response["retrieval_generation"]
    if any(getattr(model, key) != generation[key] for key in ("generation_id", "activation_event_id", "manifest_sha256")):
        raise ValueError("answer_evidence_response_generation_mismatch")
    sources = [item for item in model.items if item.kind == "source"]
    results = [item for item in model.items if item.kind == "scientific_result"]
    if len(sources) != len(response["sources"]) or len(results) != len(response["scientific_results"]):
        raise ValueError("answer_evidence_response_inventory_mismatch")
    for item, source in zip(sources, response["sources"], strict=True):
        packing, evidence = source["packing_info"], source["evidence_provenance"]
        if (source["index"] != item.position or source["paper_id"] != item.paper_id or packing is None
                or packing["chunk_id"] != item.chunk_id or packing["position"] != item.position
                or packing["source_snapshot_sha256"] != item.source_snapshot_sha256):
            raise ValueError("answer_evidence_source_position_mismatch")
        if item.has_evidence_pin:
            if not evidence or any(evidence[key] != getattr(item, key) for key in (
                "content_sha256", "evidence_revision_id", "evidence_record_sha256",
                "parent_result_revision_id", "parent_result_sha256")):
                raise ValueError("answer_evidence_source_descriptor_mismatch")
        elif evidence:
            raise ValueError("answer_evidence_unpinned_descriptor")
    for item, result in zip(results, response["scientific_results"], strict=True):
        binding = result["binding"]
        if binding["vector_id"] != item.chunk_id or any(binding[key] != getattr(item, key) for key in (
            "paper_id", "content_sha256", "evidence_revision_id", "evidence_record_sha256",
            "parent_result_revision_id", "parent_result_sha256")):
            raise ValueError("answer_evidence_result_mismatch")
    canonical({"request": request, "response": response, "bindings": bindings})
    return request, response, bindings


class SavedAnswerEvidenceReceipt(Closed):
    version: Literal["ask-answer-evidence/1.0.0"] = VERSION
    history_id: str
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bindings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: dict
    response: dict
    bindings: AnswerEvidenceBindings

    @field_validator("history_id")
    @classmethod
    def identifier(cls, value):
        return _uuid(value)

    @model_validator(mode="after")
    def coherent_body(self):
        validate_body(self.request, self.response, self.bindings.model_dump(mode="json"))
        canonical(self.model_dump(mode="json"))
        return self
