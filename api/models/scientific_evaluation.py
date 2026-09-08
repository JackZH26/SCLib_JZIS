"""Closed portable scientific-evaluation objects, not authenticated review.

These models check representation only. IDs, declared human judgments, source
roots and hashes confer no scientific, permission, or release authority. The
separate evaluator must verify cross-references, content digests, evidence and
split graphs; it must distinguish those checks from real human adjudication.
"""
from __future__ import annotations

import re
from datetime import datetime
from math import isfinite
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from models.index_read import IndexReadMetadata
from models.scientific_lookup import ScientificResultBinding

VERSION = "scientific-evaluation/1.0.0"
PROTOCOL_VERSION = "scientific-evaluation-protocol/1.0.0"
METRICS_VERSION = "scientific-eval-metrics/1.0.0"


def _nonblank(value: str) -> str:
    if not value.strip() or any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise ValueError("A nonblank bounded text value is required")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("Valid UTF-8 text is required") from None
    return value


def _uuid(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("A canonical UUID string is required")
    return value


def _timestamp(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value):
        raise ValueError("A canonical UTC microsecond timestamp is required")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    return value


def _unique(values):
    if len(set(values)) != len(values):
        raise ValueError("Repeated values are not allowed")
    return values


def _finite_json(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is float and not isfinite(item):
            raise ValueError("Portable JSON numbers must be finite")
        if type(item) is str:
            try:
                item.encode("utf-8")
            except UnicodeError:
                raise ValueError("Portable JSON strings must be valid UTF-8") from None
        elif type(item) is list:
            pending.extend(item)
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
    return value


EvaluationJSON = Annotated[JsonValue, AfterValidator(_finite_json)]
Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]*$")]
Label = Annotated[str, Field(min_length=1, max_length=160), AfterValidator(_nonblank)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
CanonicalUUID = Annotated[str, Field(min_length=36, max_length=36), AfterValidator(_uuid)]
Timestamp = Annotated[str, Field(min_length=27, max_length=27), AfterValidator(_timestamp)]
Rationale = Annotated[str, Field(min_length=1, max_length=8000), AfterValidator(_nonblank)]
SourceIDs = Annotated[list[Identifier], Field(max_length=1000), AfterValidator(_unique)]
ReviewerKind = Literal["declared_human", "synthetic"]
ReviewDecision = Literal["accept", "reject", "needs_revision"]
Task = Literal["numerical", "mechanism", "comparison", "mixed", "clarification", "general"]
AnswerMode = Literal["synthesis", "limited_synthesis", "extractive_fallback", "abstention", "structured_results", "clarification", "unavailable"]
Correctness = Literal["correct", "incorrect", "undetermined", "not_applicable"]
ReviewIDs = Annotated[list[Identifier], Field(min_length=2, max_length=2), AfterValidator(_unique)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False, revalidate_instances="always")


class StratumRequirement(_Closed):
    dimension: Literal["task", "language", "family", "tag"]
    key: Label
    min_n: int = Field(ge=1, le=200)


class MetricGate(_Closed):
    metric: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")]
    direction: Literal["min", "max"]
    threshold: float
    min_n: int = Field(ge=1, le=200)


class EvaluationProtocol(_Closed):
    version: Literal["scientific-evaluation-protocol/1.0.0"] = PROTOCOL_VERSION
    id: Identifier
    created_at: Timestamp
    scope_note: Rationale
    target_question_count: int = Field(default=120, ge=100, le=200)
    k_values: Annotated[list[Annotated[int, Field(ge=1, le=20)]], Field(min_length=1, max_length=20), AfterValidator(_unique)]
    strata: list[StratumRequirement] = Field(default_factory=list, max_length=100)
    gates: list[MetricGate] = Field(default_factory=list, max_length=100)
    metrics_version: Literal["scientific-eval-metrics/1.0.0"] = METRICS_VERSION


class CapturedSource(_Closed):
    id: Identifier
    paper_id: Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_nonblank)]
    vector_id: Annotated[str, Field(pattern=r"^ig62_[0-9a-f]{32}_[0-9a-f]{64}$", min_length=102, max_length=102)]
    vector_sha256: Hash
    source_snapshot_sha256: Hash
    text: str = Field(min_length=1, max_length=512 * 1024)
    evidence_provenance: dict[str, EvaluationJSON]
    work_id: CanonicalUUID | None = None
    root_id: Identifier | None = None
    capture_sha256: Hash | None = None

    @field_validator("text")
    @classmethod
    def bounded_source_bytes(cls, value):
        _nonblank(value)
        if len(value.encode("utf-8")) > 512 * 1024:
            raise ValueError("Captured source exceeds 512 KiB of UTF-8")
        return value

    @field_validator("evidence_provenance", mode="before")
    @classmethod
    def current_closed_descriptor(cls, value):
        from services.rag_evidence_contract import validate_evidence_descriptor

        return validate_evidence_descriptor(value)


class CapturedResult(_Closed):
    id: Identifier
    binding: ScientificResultBinding
    raw_record: dict[str, EvaluationJSON] = Field(max_length=1000)
    input_record_sha256: Hash

    @field_validator("binding")
    @classmethod
    def checked_binding_instance(cls, value):
        return ScientificResultBinding.model_validate(value.model_dump(), strict=True)


class EvaluationCorpus(_Closed):
    id: Identifier
    generation: IndexReadMetadata
    index_profile: dict[str, EvaluationJSON] = Field(max_length=32)
    index_resource: dict[str, EvaluationJSON] = Field(max_length=32)
    sources: list[CapturedSource] = Field(min_length=1, max_length=1000)
    results: list[CapturedResult] = Field(default_factory=list, max_length=1000)

    @field_validator("generation")
    @classmethod
    def frozen_generation_only(cls, value):
        # Revalidate even an instance made with model_construct/model_copy.
        value = IndexReadMetadata.model_validate(value.model_dump(), strict=True)
        if value.mode != "generation_snapshot":
            raise ValueError("A scientific evaluation requires a complete frozen generation identity")
        return value


class ExpectedCondition(_Closed):
    field: Literal["formula", "pressure", "tc", "sample", "isotope", "doping", "phase", "tc_criterion", "origin", "source_role", "outcome", "other"]
    raw_expectation: Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(_nonblank)]
    source_ids: SourceIDs = Field(default_factory=list)


class ExpectedClaim(_Closed):
    id: Identifier
    text: Annotated[str, Field(min_length=1, max_length=8000), AfterValidator(_nonblank)]
    evidence_alternatives: list[Annotated[SourceIDs, Field(min_length=1, max_length=20)]] = Field(min_length=1, max_length=20)

    @field_validator("evidence_alternatives")
    @classmethod
    def distinct_bundles(cls, value):
        if len({frozenset(bundle) for bundle in value}) != len(value):
            raise ValueError("Repeated OR evidence alternatives are ambiguous")
        return value


class CaseExpectation(_Closed):
    route: Task
    acceptable_modes: Annotated[list[AnswerMode], Field(min_length=1, max_length=7), AfterValidator(_unique)]
    conditions: list[ExpectedCondition] = Field(default_factory=list, max_length=32)
    claims: list[ExpectedClaim] = Field(default_factory=list, max_length=40)
    result_ids: SourceIDs = Field(default_factory=list)
    refusal_reason: Rationale | None = None


class EvaluationCase(_Closed):
    id: Identifier
    query_group_id: Identifier
    split: Literal["development", "held_out"]
    query: Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(_nonblank)]
    language: Literal["en", "zh"]
    task: Task
    families: Annotated[list[Label], Field(max_length=32), AfterValidator(_unique)] = Field(default_factory=list)
    tags: Annotated[list[Label], Field(max_length=32), AfterValidator(_unique)] = Field(default_factory=list)
    expected: CaseExpectation


class CaseReview(_Closed):
    id: Identifier
    case_id: Identifier
    case_sha256: Hash
    protocol_sha256: Hash
    corpus_sha256: Hash
    reviewer_id: Identifier
    reviewer_kind: ReviewerKind
    submitted_at: Timestamp
    decision: ReviewDecision
    rationale: Rationale


class CaseResolution(_Closed):
    id: Identifier
    case_id: Identifier
    case_sha256: Hash
    protocol_sha256: Hash
    corpus_sha256: Hash
    review_ids: ReviewIDs
    resolver_id: Identifier
    resolver_kind: ReviewerKind
    submitted_at: Timestamp
    decision: ReviewDecision
    rationale: Rationale


class OutputClaimJudgment(_Closed):
    id: Identifier
    start: int = Field(ge=0, le=128 * 1024)
    end: int = Field(ge=1, le=128 * 1024)
    source_ids: Annotated[list[Identifier], Field(max_length=20), AfterValidator(_unique)] = Field(default_factory=list)
    citation_indices: Annotated[list[Annotated[int, Field(ge=1, le=20)]], Field(max_length=20), AfterValidator(_unique)] = Field(default_factory=list)
    status: Literal["supported", "contradicted", "undetermined"]
    expected_claim_ids: Annotated[list[Identifier], Field(max_length=40), AfterValidator(_unique)] = Field(default_factory=list)

    @model_validator(mode="after")
    def nonempty_span(self):
        if self.end <= self.start:
            raise ValueError("A claim must identify a nonempty codepoint span")
        return self


class OutputLabels(_Closed):
    condition_match: Correctness
    numerical_correct: Correctness
    unit_correct: Correctness
    refusal_correct: Correctness
    answer_claims_complete: bool
    claims: list[OutputClaimJudgment] = Field(default_factory=list, max_length=40)


class OutputJudgment(_Closed):
    id: Identifier
    reviewer_id: Identifier
    reviewer_kind: ReviewerKind
    observation_sha256: Hash
    submitted_at: Timestamp
    rationale: Rationale
    labels: OutputLabels


class OutputResolution(OutputJudgment):
    """The inherited reviewer_id/reviewer_kind identify the declared resolver."""
    review_ids: ReviewIDs


class RunObservation(_Closed):
    case_id: Identifier
    case_sha256: Hash
    status: Literal["completed", "unavailable", "not_run"]
    retrieved_source_ids: Annotated[list[Identifier], Field(max_length=300), AfterValidator(_unique)] = Field(default_factory=list)
    selected_source_ids: Annotated[list[Identifier], Field(max_length=20), AfterValidator(_unique)] = Field(default_factory=list)
    result_ids: Annotated[list[Identifier], Field(max_length=20), AfterValidator(_unique)] = Field(default_factory=list)
    answer: str = Field(max_length=128 * 1024)
    answer_mode: AnswerMode
    answer_sha256: Hash
    request_sha256: Hash | None = None
    request_payload: dict[str, EvaluationJSON] | None = Field(default=None, max_length=32)
    latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0, le=2147483647)
    total_tokens: int | None = Field(default=None, ge=0, le=2147483647)
    cost_usd: float | None = Field(default=None, ge=0)
    provider_fallback: bool | None = None
    judgments: list[OutputJudgment] = Field(default_factory=list, max_length=2)
    resolution: OutputResolution | None = None

    @field_validator("answer")
    @classmethod
    def bounded_answer_bytes(cls, value):
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError:
            raise ValueError("Valid UTF-8 answer text is required") from None
        if size > 128 * 1024:
            raise ValueError("Captured answer exceeds 128 KiB of UTF-8")
        return value


class EvaluationRun(_Closed):
    id: Identifier
    arm: Literal["baseline", "candidate"]
    execution: Literal["captured", "synthetic"]
    protocol_sha256: Hash
    corpus_sha256: Hash
    dataset_sha256: Hash
    code_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$", min_length=40, max_length=40)]
    config: dict[str, EvaluationJSON] = Field(max_length=100)
    config_sha256: Hash
    lock_sha256: Hash
    prompt_version: Label
    model_requested: Label | None = None
    model_observed: Label | None = None
    policy_versions: dict[Identifier, Label] = Field(max_length=32)
    started_at: Timestamp
    observations: list[RunObservation] = Field(default_factory=list, max_length=200)


class ScientificEvaluationPackage(_Closed):
    version: Literal["scientific-evaluation/1.0.0"] = VERSION
    purpose: Literal["development_synthetic", "real_candidate"]
    protocol: EvaluationProtocol
    corpus: EvaluationCorpus
    cases: list[EvaluationCase] = Field(default_factory=list, max_length=200)
    case_reviews: list[CaseReview] = Field(default_factory=list, max_length=400)
    case_resolutions: list[CaseResolution] = Field(default_factory=list, max_length=200)
    runs: list[EvaluationRun] = Field(default_factory=list, max_length=2)
