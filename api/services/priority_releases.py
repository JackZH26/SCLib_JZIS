"""Immutable, curator-approved RPS bundles; no database or public write path.

A manifest hash proves integrity, not scientific validity. Public serving also
requires an administrator-pinned digest (separate from the untrusted bundle).
"""

from __future__ import annotations

import json
from copy import deepcopy
from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from services.priority_release_cache import (
    clear_release_cache as clear_release_cache,
)
from services.priority_release_cache import (
    read_verified_file,
)
from services.priority_release_cache import (
    release_cache_stats as release_cache_stats,
)
from services.research_priority import (
    DIMENSIONS,
    POLICY_HASH,
    POLICY_VERSION,
    PROFILES,
    ActionTemplate,
    Assessment,
    Campaign,
    Contract,
    Hash,
    Identifier,
    Nonnegative,
    Reference,
    action_specification,
    digest,
    evaluate,
)


class EvidenceContent(Contract):
    source_kind: Literal["literature", "calculation", "curation"]
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    url: HttpUrl
    doi: str | None = None
    source_version: Annotated[str, Field(min_length=1, max_length=200)]
    locator: Annotated[str, Field(min_length=1, max_length=2000)]
    license: Annotated[str, Field(min_length=1, max_length=300)]
    validity: Literal["accepted", "disputed", "retracted"]


class StateContent(Contract):
    material_id: Identifier
    pressure_status: Literal["explicit_ambient", "reported", "not_reported", "ambiguous"]
    pressure_gpa: Nonnegative | None
    temperature_role: Literal["measurement", "synthesis", "simulation", "unknown"]
    temperature_k: Nonnegative | None
    phase: Annotated[str, Field(min_length=1, max_length=1000)]
    sample_context: Annotated[str, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def conditions(self):
        if self.pressure_status in {"not_reported", "ambiguous"}:
            if self.pressure_gpa is not None:
                raise ValueError("unknown pressure must be null")
        elif self.pressure_gpa is None or (
            self.pressure_status == "explicit_ambient" and self.pressure_gpa != 0
        ):
            raise ValueError("reported pressure must be explicit; ambient is zero")
        if self.temperature_role == "unknown" and self.temperature_k is not None:
            raise ValueError("unknown temperature role must have null value")
        return self


class ActionContent(Contract):
    state_id: Identifier
    assessment_action_hash: Hash
    action_requirements_hash: Hash
    kind: Literal["verification", "calculation", "conversion", "measurement"]
    conversion_target_pressure_gpa: Nonnegative | None = None
    conversion_rationale: str | None = None
    conversion_evidence: list[Reference] = Field(default_factory=list)


class TemplateReviewContent(Contract):
    template_id: Identifier
    template_version: Identifier
    template_hash: Hash
    decision: Literal["approved"]
    reviewer_id: Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
    review_scope: Literal["prerequisite_and_resource_completeness"]
    rationale: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]
    evidence: list[Reference] = Field(min_length=1, max_length=100)


class RubricContent(Contract):
    dimension: Identifier
    profiles: list[Identifier] = Field(min_length=1)
    anchors: dict[str, str]
    required_evidence: Annotated[str, Field(min_length=1, max_length=4000)]

    @model_validator(mode="after")
    def complete(self):
        if self.dimension not in DIMENSIONS or not set(self.profiles) <= set(PROFILES):
            raise ValueError("unknown rubric dimension/profile")
        if set(self.anchors) != {"0", "25", "50", "75", "100"} or any(
            not v.strip() for v in self.anchors.values()
        ):
            raise ValueError("rubric needs definitions for all five anchors")
        return self


class Artifact(Contract):
    id: Identifier
    kind: Literal[
        "material",
        "state",
        "action",
        "profile_assignment",
        "evidence",
        "review",
        "rubric",
        "action_template",
        "template_review",
    ]
    sha256: Hash
    available_at: AwareDatetime
    public: bool = Field(strict=True)
    content: dict

    @model_validator(mode="after")
    def hashed(self) -> Artifact:
        if self.sha256 != digest(self.model_dump(mode="json", exclude={"sha256"})):
            raise ValueError(f"artifact digest mismatch: {self.id}")
        contracts = {
            "state": StateContent,
            "action": ActionContent,
            "evidence": EvidenceContent,
            "rubric": RubricContent,
            "action_template": ActionTemplate,
            "template_review": TemplateReviewContent,
        }
        if self.kind in contracts:
            contracts[self.kind].model_validate(self.content)
        return self


class ReviewedAssessment(Contract):
    assessment: Assessment
    review: Reference


class PriorityRelease(Contract):
    schema_version: Literal["rps-release/1.2"] = "rps-release/1.2"
    id: Identifier
    policy_version: Literal["RPS-v1.2"]
    policy_hash: Hash
    campaign: Campaign
    campaign_hash: Hash
    evidence_cutoff: AwareDatetime
    published_at: AwareDatetime
    artifacts: list[Artifact] = Field(max_length=100000)
    assessments: list[ReviewedAssessment] = Field(max_length=10000)
    manifest_sha256: Hash

    @model_validator(mode="after")
    def verified(self) -> PriorityRelease:
        if self.policy_hash != POLICY_HASH or self.policy_version != POLICY_VERSION:
            raise ValueError("release policy does not match implemented policy")
        if self.campaign_hash != digest(self.campaign.model_dump(mode="json")):
            raise ValueError("campaign digest mismatch")
        if self.manifest_sha256 != digest(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("release manifest mismatch")
        if self.evidence_cutoff > self.published_at:
            raise ValueError("evidence cutoff follows publication")
        artifacts = {a.id: a for a in self.artifacts}
        if len(artifacts) != len(self.artifacts):
            raise ValueError("duplicate artifact id")
        identities = [entry.assessment.id for entry in self.assessments]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate assessment id")
        action_keys = [
            (e.assessment.material.id, e.assessment.state.id, e.assessment.action.id)
            for e in self.assessments
        ]
        if len(action_keys) != len(set(action_keys)):
            raise ValueError("duplicate material/state/action in fixed release")
        for artifact in self.artifacts:
            cutoff = self.published_at if artifact.kind == "review" else self.evidence_cutoff
            if not artifact.public or artifact.available_at > cutoff:
                raise ValueError("non-public or post-cutoff artifact")

        def resolve(ref: Reference, kind: str) -> Artifact:
            found = artifacts.get(ref.id)
            if found is None or found.sha256 != ref.sha256 or found.kind != kind:
                raise ValueError(f"unresolved {kind} reference: {ref.id}")
            if kind == "evidence" and found.content["validity"] == "retracted":
                raise ValueError("retracted evidence cannot support a published assessment")
            return found

        for entry in self.assessments:
            a = entry.assessment
            material = resolve(a.material, "material")
            state = resolve(a.state, "state")
            action = resolve(a.action, "action")
            assignment = resolve(a.profile_assignment, "profile_assignment")
            review = resolve(entry.review, "review")
            requirements = a.action_requirements
            template = resolve(requirements.template_ref, "action_template")
            template_review = resolve(requirements.template_review, "template_review")
            if ActionTemplate.model_validate(template.content) != requirements.template:
                raise ValueError("inline action template does not match its immutable artifact")
            if self.campaign.action_templates.get(template.id) != template.sha256:
                raise ValueError("action template is not pinned in this campaign")
            reviewed_template = TemplateReviewContent.model_validate(template_review.content)
            if (
                reviewed_template.template_id != template.id
                or reviewed_template.template_version != requirements.template.version
                or reviewed_template.template_hash != template.sha256
                or template_review.available_at < template.available_at
                or template_review.available_at > action.available_at
                or template_review.available_at > review.available_at
            ):
                raise ValueError("missing/broken/late action-template review")
            for ref in reviewed_template.evidence:
                resolve(ref, "evidence")
            if action.content["kind"] != requirements.template.action_kind:
                raise ValueError("action kind is outside the reviewed template")
            if action.content["action_requirements_hash"] != digest(
                requirements.model_dump(mode="json")
            ):
                raise ValueError("action prerequisites/dependencies/resources changed after review")
            for declaration in (
                *requirements.prerequisites,
                *requirements.dependencies,
                *requirements.resources,
            ):
                for ref in declaration.evidence:
                    resolve(ref, "evidence")
            if material.content.get("formula") != a.formula:
                raise ValueError("material formula mismatch")
            if state.content.get("material_id") != a.material.id:
                raise ValueError("state/material mismatch")
            if action.content.get("state_id") != a.state.id:
                raise ValueError("action/state mismatch")
            pressure = state.content["pressure_gpa"]
            if a.target_fit == "matches" and (
                pressure is None or pressure > self.campaign.target_pressure_max_gpa
            ):
                raise ValueError("target_fit contradicts known pressure or lacks conditions")
            if a.target_fit == "approved_conversion":
                target = action.content.get("conversion_target_pressure_gpa")
                if (
                    action.content["kind"] != "conversion"
                    or target is None
                    or target > self.campaign.target_pressure_max_gpa
                    or not action.content.get("conversion_rationale")
                    or not action.content.get("conversion_evidence")
                ):
                    raise ValueError("conversion requires a supported, specific target path")
                for ref in action.content["conversion_evidence"]:
                    resolve(Reference.model_validate(ref), "evidence")
            if action.content.get("assessment_action_hash") != digest(action_specification(a)):
                raise ValueError("action specification mismatch")
            expected_assignment = {
                "campaign_hash": self.campaign_hash,
                "mix": self.campaign.profile_mixes.get(a.profile_assignment.id),
            }
            if expected_assignment["mix"] is None or assignment.content != expected_assignment:
                raise ValueError("profile assignment is not fixed in campaign")
            if (
                review.content.get("assessment_hash") != digest(a.model_dump(mode="json"))
                or review.content.get("campaign_hash") != self.campaign_hash
                or review.content.get("policy_hash") != self.policy_hash
                or review.content.get("decision") != "approved"
                or not review.content.get("reviewer_id")
            ):
                raise ValueError("missing/broken assessment review")
            for key, dimension in a.dimensions.items():
                rule_id = self.campaign.dimension_rules[key]
                rubric = artifacts.get(rule_id)
                if (
                    dimension.rule_id != rule_id
                    or rubric is None
                    or rubric.kind != "rubric"
                    or rubric.content["dimension"] != key
                    or not set(self.campaign.profile_mixes[a.profile_assignment.id])
                    <= set(rubric.content["profiles"])
                ):
                    raise ValueError("dimension rubric is not registered for this campaign/profile")
                for ref in dimension.evidence:
                    resolve(ref, "evidence")
            for judged in (a.decision_impact, a.discrimination, a.readiness, *a.costs):
                for ref in judged.evidence:
                    resolve(ref, "evidence")
            evaluate(a, self.campaign)  # revalidate every candidate before exposing ANY row
        return self

    @cached_property
    def _rows(self) -> list[dict]:
        rows = []
        for entry in self.assessments:
            a = entry.assessment
            result = evaluate(a, self.campaign)
            rows.append(
                {
                    "id": a.id,
                    "revision": a.revision,
                    "material_id": a.material.id,
                    "state_id": a.state.id,
                    "action_id": a.action.id,
                    "formula": a.formula,
                    "family": a.family,
                    "state_summary": a.state_summary,
                    "action_summary": a.action_summary,
                    "role": a.role,
                    "action_template": {
                        "id": a.action_requirements.template_ref.id,
                        "version": a.action_requirements.template.version,
                        "sha256": a.action_requirements.template_ref.sha256,
                        "review_id": a.action_requirements.template_review.id,
                    },
                    "dimensions": {
                        k: {
                            "status": v.status,
                            "lower": v.lower,
                            "upper": v.upper,
                            "anchor": v.anchor,
                            "missing_reason": v.missing_reason,
                            "evidence_polarity": v.evidence_polarity,
                        }
                        for k, v in a.dimensions.items()
                    },
                    "result": result,
                }
            )
        # Displayed ties share rank; immutable ID orders ties, not hidden decimals.
        rows.sort(
            key=lambda r: (
                r["result"]["score_display"] is None,
                -(r["result"]["score_display"] or 0),
                r["id"],
            )
        )
        counts: dict[str, int] = {}
        previous: dict[str, tuple[int, int]] = {}
        for row in rows:
            result = row["result"]
            group, score = result["rank_group"], result["score_display"]
            row["rank"] = None
            if score is not None:
                counts[group] = counts.get(group, 0) + 1
                rank = (
                    previous[group][1]
                    if group in previous and previous[group][0] == score
                    else counts[group]
                )
                row["rank"] = rank
                previous[group] = (score, rank)
        return rows

    def rows(self) -> list[dict]:
        """Read projection computed once per verified immutable bundle."""
        return self._rows


def read_release(directory: Path, release_id: str, expected_hash: str) -> PriorityRelease:
    """Never accept arbitrary file paths or bundle-provided publication approval."""
    # Pydantic frozen models do not recursively freeze dict/list fields. Never
    # let a route or CLI mutate the cache's verified inputs or cached row values.
    return deepcopy(_cached_release(directory, release_id, expected_hash))


def read_release_projection(directory: Path, release_id: str, expected_hash: str) -> dict:
    """Lightweight detached catalogue metadata, not a full model copy per item."""
    release = _cached_release(directory, release_id, expected_hash)
    return {
        "id": release.id,
        "manifest_sha256": release.manifest_sha256,
        "campaign_id": release.campaign.id,
        "campaign_version": release.campaign.version,
        "objective": release.campaign.objective,
        "published_at": release.published_at.isoformat(),
        "evidence_cutoff": release.evidence_cutoff.isoformat(),
        "total": len(release.assessments),
    }


def _cached_release(directory: Path, release_id: str, expected_hash: str) -> PriorityRelease:
    from pydantic import TypeAdapter

    TypeAdapter(Identifier).validate_python(release_id)
    TypeAdapter(Hash).validate_python(expected_hash)
    path = directory / f"{release_id}.json"
    release = read_verified_file(
        path,
        identity=("rps-release-reader/2", release_id, expected_hash),
        validator=lambda raw: _read_verified(raw, release_id, expected_hash),
    )
    return release


def _read_verified(raw: bytes, release_id: str, expected_hash: str) -> PriorityRelease:
    def unique_keys(pairs: list[tuple[str, object]]) -> dict:
        obj: dict = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON object key")
            obj[key] = value
        return obj

    def invalid_constant(value: str):
        raise ValueError("nonfinite JSON value")

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_keys,
                             parse_constant=invalid_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid RPS JSON input") from exc
    release = PriorityRelease.model_validate(payload)
    if release.id != release_id or release.manifest_sha256 != expected_hash:
        raise ValueError("release identity does not match administrator-pinned digest")
    release.rows()  # materialize once in the reader worker, not the async request loop
    return release
