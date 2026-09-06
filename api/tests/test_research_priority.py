"""Synthetic policy tests. Fixtures are NOT scientific material assessments."""

from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from services.priority_releases import PriorityRelease
from services.research_priority import (
    DIMENSIONS,
    POLICY_HASH,
    POLICY_VERSION,
    RESOURCES,
    ActionTemplate,
    Assessment,
    Campaign,
    action_specification,
    digest,
    effective_weights,
    evaluate,
    round_score,
)


def template_artifact():
    content = ActionTemplate.model_validate(
        {
            "version": "synthetic-1",
            "title": "SYNTHETIC TEST TEMPLATE ONLY",
            "action_kind": "calculation",
            "scope": "No scientific approval: test fixture only",
            "prerequisites": [
                {
                    "key": "structure",
                    "description": "Synthetic structure needed",
                    "dependency_kind": "structure",
                    "critical": True,
                }
            ],
            "prerequisite_completeness_rationale": "Synthetic completeness assertion for unit testing only",
            "resource_rules": {
                resource: "required" if resource == "cpu_core_hours" else "not_applicable"
                for resource in RESOURCES
            },
        }
    ).model_dump(mode="json")
    item = {
        "id": "template:test",
        "kind": "action_template",
        "available_at": "2026-09-01T00:00:00Z",
        "public": True,
        "content": content,
    }
    item["sha256"] = digest(item)
    return item


def campaign():
    return Campaign.model_validate(
        {
            "id": "test-campaign",
            "version": "1",
            "objective": "SYNTHETIC TEST ONLY",
            "target_pressure_max_gpa": 0.0,
            "budget": {"cpu_core_hours": 100.0},
            "profile_mixes": {"assignment": {"common": 1.0}},
            "dimension_rules": {key: f"rule:{key}" for key in DIMENSIONS},
            "action_templates": {"template:test": template_artifact()["sha256"]},
        }
    )


def assessment():
    def ref(key):
        return {"id": key, "sha256": "a" * 64}

    def action_anchor(value):
        return {
            "anchor": value,
            "lower": value,
            "upper": value,
            "rationale": "Synthetic test anchor",
            "evidence": [ref("source")],
        }

    return Assessment.model_validate(
        {
            "id": "test-1",
            "revision": 1,
            "material": ref("material"),
            "state": ref("state"),
            "action": ref("action"),
            "profile_assignment": ref("assignment"),
            "formula": "TEST",
            "family": "synthetic",
            "state_summary": "test state",
            "action_summary": "test action",
            "role": "new_candidate",
            "target_fit": "matches",
            "dimensions": {
                key: {
                    "status": "assessed",
                    "anchor": value,
                    "lower": value,
                    "upper": value,
                    "rule_id": f"rule:{key}",
                    "rationale": "Synthetic test only",
                    "evidence": [ref("source")],
                    "missing_reason": None,
                    "evidence_polarity": "supporting",
                }
                for key, value in zip(DIMENSIONS, (50, 75, 50, 50, 75, 75), strict=True)
            },
            "decision_impact": action_anchor(1),
            "discrimination": action_anchor(0.75),
            "readiness": action_anchor(0.75),
            "action_requirements": {
                "template_ref": {"id": "template:test", "sha256": template_artifact()["sha256"]},
                "template_review": ref("template-review"),
                "template": template_artifact()["content"],
                "prerequisites": [
                    {
                        "key": "structure",
                        "status": "satisfied",
                        "rationale": "Synthetic proof",
                        "evidence": [ref("source")],
                        "dependency_ids": ["structure-input"],
                    }
                ],
                "dependencies": [
                    {
                        "id": "structure-input",
                        "kind": "structure",
                        "status": "available",
                        "rationale": "Synthetic proof",
                        "evidence": [ref("source")],
                    }
                ],
                "resources": [
                    {
                        "resource": resource,
                        "applicability": "required"
                        if resource == "cpu_core_hours"
                        else "not_applicable",
                        "rationale": "Synthetic declaration only",
                        "evidence": [ref("source")],
                    }
                    for resource in RESOURCES
                ],
            },
            "outcomes": [
                {"observation": "test positive", "decision": "proceed"},
                {"observation": "test negative", "decision": "stop"},
            ],
            "costs": [
                {
                    "resource": "cpu_core_hours",
                    "lower": 20.0,
                    "upper": 20.0,
                    "basis": "synthetic cost",
                    "evidence": [ref("source")],
                }
            ],
        }
    )


def release_payload():
    c = campaign()
    campaign_hash = digest(c.model_dump(mode="json"))
    artifacts = []

    def artifact(key, kind, content, date="2026-09-01T00:00:00Z"):
        item = {"id": key, "kind": kind, "available_at": date, "public": True, "content": content}
        item["sha256"] = digest(item)
        artifacts.append(item)
        return {"id": key, "sha256": item["sha256"]}

    a = assessment().model_dump(mode="json")
    evidence = artifact(
        "source",
        "evidence",
        {
            "source_kind": "curation",
            "title": "Synthetic fixture, not research evidence",
            "url": "https://example.org/test",
            "source_version": "1",
            "locator": "test case 1",
            "license": "synthetic",
            "validity": "accepted",
        },
    )
    execution_evidence = artifact(
        "execution-source",
        "evidence",
        {
            "source_kind": "curation",
            "title": "Synthetic execution-only proof, not a real approval",
            "url": "https://example.org/execution-test",
            "source_version": "1",
            "locator": "Synthetic action prerequisites and template review",
            "license": "synthetic",
            "validity": "accepted",
        },
    )
    template = template_artifact()
    artifacts.append(template)
    a["action_requirements"]["template_review"] = artifact(
        "template-review",
        "template_review",
        {
            "template_id": template["id"],
            "template_version": template["content"]["version"],
            "template_hash": template["sha256"],
            "decision": "approved",
            "reviewer_id": "synthetic-reviewer-not-a-real-approval",
            "review_scope": "prerequisite_and_resource_completeness",
            "rationale": "SYNTHETIC TEST ONLY: not an approved scientific template",
            "evidence": [execution_evidence],
        },
        "2026-09-01T00:00:00Z",
    )
    for key in ("prerequisites", "dependencies", "resources"):
        for item in a["action_requirements"][key]:
            item["evidence"] = [execution_evidence]
    a["material"] = artifact("material", "material", {"formula": "TEST"})
    a["state"] = artifact(
        "state",
        "state",
        {
            "material_id": "material",
            "pressure_status": "explicit_ambient",
            "pressure_gpa": 0.0,
            "temperature_role": "unknown",
            "temperature_k": None,
            "phase": "test phase",
            "sample_context": "synthetic fixture",
        },
    )
    a["profile_assignment"] = artifact(
        "assignment",
        "profile_assignment",
        {
            "campaign_hash": campaign_hash,
            "mix": c.profile_mixes["assignment"],
        },
    )
    for key, dimension in a["dimensions"].items():
        dimension["evidence"] = [evidence]
        artifact(
            f"rule:{key}",
            "rubric",
            {
                "dimension": key,
                "profiles": ["common"],
                "anchors": {str(n): f"synthetic anchor {n}" for n in (0, 25, 50, 75, 100)},
                "required_evidence": "synthetic test fixture only",
            },
        )
    for judged in (a["decision_impact"], a["discrimination"], a["readiness"], *a["costs"]):
        judged["evidence"] = [evidence]
    a["action"] = artifact(
        "action",
        "action",
        {
            "state_id": "state",
            "kind": "calculation",
            "action_requirements_hash": digest(a["action_requirements"]),
            "assessment_action_hash": digest(action_specification(Assessment.model_validate(a))),
        },
    )
    review = artifact(
        "review",
        "review",
        {
            "assessment_hash": digest(a),
            "campaign_hash": campaign_hash,
            "policy_hash": POLICY_HASH,
            "decision": "approved",
            "reviewer_id": "synthetic-reviewer",
        },
        "2026-09-04T00:00:00Z",
    )
    payload = {
        "schema_version": "rps-release/1.2",
        "id": "synthetic-release",
        "policy_version": POLICY_VERSION,
        "policy_hash": POLICY_HASH,
        "campaign": c.model_dump(mode="json"),
        "campaign_hash": campaign_hash,
        "evidence_cutoff": "2026-09-02T00:00:00Z",
        "published_at": "2026-09-05T00:00:00Z",
        "artifacts": artifacts,
        "assessments": [{"assessment": a, "review": review}],
    }
    payload["manifest_sha256"] = digest(payload)
    return payload


def rehash(payload):
    payload["manifest_sha256"] = digest(
        {k: v for k, v in payload.items() if k != "manifest_sha256"}
    )
    return payload


def test_golden_7075_half_up_and_conservation():
    result = evaluate(assessment(), campaign())
    assert (result["p_lower"], result["g_lower"], result["a_lower"]) == (60, 75, 75)
    assert result["score_raw"] == 7075
    assert result["score_display"] == 7100
    parts = result["contributions"]
    assert (parts["physical"], parts["gain"], parts["action"], parts["rounding"]) == (
        450,
        675,
        450,
        25,
    )
    assert sum(parts["dimensions"].values()) == parts["physical"]
    assert sum(parts[k] for k in ("baseline", "physical", "gain", "action", "rounding")) == 7100


@pytest.mark.parametrize(
    ("raw", "expected"), [(7047, 7050), (7075, 7100), (7025, 7050), (1000, 1000), (10000, 10000)]
)
def test_rounding(raw, expected):
    assert round_score(Decimal(raw)) == expected


def test_unknown_fixed_denominator_and_true_zero_distinguished():
    a = assessment().model_dump()
    for dimension in a["dimensions"].values():
        dimension.update(
            status="unknown",
            evidence_polarity="unknown",
            anchor=None,
            lower=0,
            upper=100,
            evidence=[],
            missing_reason="not calculated",
        )
    result = evaluate(Assessment.model_validate(a), campaign())
    assert (result["p_lower"], result["p_upper"], result["assessed_weight"]) == (0, 100, 0)
    a["dimensions"]["stability"].update(
        status="assessed",
        anchor=100,
        lower=100,
        upper=100,
        evidence=assessment().dimensions["stability"].model_dump()["evidence"],
        missing_reason=None,
    )
    result = evaluate(Assessment.model_validate(a), campaign())
    assert (result["p_lower"], result["p_upper"], result["assessed_weight"]) == (20, 100, 0.2)
    assert result["contributions"]["dimension_reasons"]["pairing"] == "missing_support"


@pytest.mark.parametrize(
    ("mix", "expected"),
    [
        ({"epc_hydride": 1}, [0.2, 0.175, 0.3, 0.125, 0.1, 0.1]),
        ({"epc_hydride": 0.5, "multiband": 0.5}, [0.2, 0.1875, 0.2875, 0.1375, 0.0875, 0.1]),
    ],
)
def test_prespecified_profile_mix(mix, expected):
    c = campaign().model_dump()
    c["profile_mixes"]["assignment"] = mix
    assert (
        list(map(float, effective_weights(Campaign.model_validate(c), "assignment").values()))
        == expected
    )


@pytest.mark.parametrize("key", ["decision_impact", "discrimination", "readiness"])
def test_zero_lower_gate_cannot_be_offset_by_other_scores(key):
    a = assessment().model_dump()
    a[key]["lower"] = 0
    r = evaluate(Assessment.model_validate(a), campaign())
    assert r["eligibility"] == "ineligible" and r["score_display"] is None


@pytest.mark.parametrize(
    ("upper", "expected"),
    [
        (10, 1),
        (10.01, 0.75),
        (25, 0.75),
        (25.01, 0.5),
        (50, 0.5),
        (100, 0.25),
        (100.01, 0),
        (None, None),
    ],
)
def test_cost_thresholds_use_upper_bound(upper, expected):
    a = assessment().model_dump()
    a["costs"][0].update(lower=0, upper=upper)
    r = evaluate(Assessment.model_validate(a), campaign())
    assert r["affordability_lower"] == expected
    if upper is None or upper > 100:
        assert r["score_display"] is None


@pytest.mark.parametrize("bad", [True, "75", float("nan"), float("inf"), -1, 60])
def test_strict_numeric_anchors(bad):
    a = assessment().model_dump()
    a["dimensions"]["stability"]["lower"] = bad
    with pytest.raises(ValidationError):
        Assessment.model_validate(a)


def test_reference_is_not_new_discovery_rank():
    a = assessment().model_dump()
    a["role"] = "negative_control"
    r = evaluate(Assessment.model_validate(a), campaign())
    assert r["eligibility"] == "reference_only" and r["score_display"] is None


def test_maximum_score_and_unavailable_required_resource():
    a = assessment().model_dump()
    for dimension in a["dimensions"].values():
        dimension.update(anchor=100, lower=100, upper=100)
    for key in ("decision_impact", "discrimination", "readiness"):
        a[key].update(anchor=1, lower=1, upper=1)
    a["costs"][0].update(lower=10, upper=10)
    assert evaluate(Assessment.model_validate(a), campaign())["score_display"] == 10000
    c = campaign().model_dump()
    c["budget"] = {}
    result = evaluate(Assessment.model_validate(a), Campaign.model_validate(c))
    assert result["score_display"] is None
    assert "resource_unavailable:cpu_core_hours" in result["reason_codes"]


def test_rule_registry_not_just_review_hash_is_enforced():
    payload = release_payload()
    a = payload["assessments"][0]["assessment"]
    a["dimensions"]["pairing"]["rule_id"] = "unregistered-rule"
    review = next(item for item in payload["artifacts"] if item["kind"] == "review")
    review["content"]["assessment_hash"] = digest(a)
    review["sha256"] = digest({k: v for k, v in review.items() if k != "sha256"})
    payload["assessments"][0]["review"]["sha256"] = review["sha256"]
    with pytest.raises(ValueError, match="rubric is not registered"):
        PriorityRelease.model_validate(rehash(payload))


def test_display_ties_and_mechanism_ranks_are_separate():
    payload = release_payload()
    for number, role in ((2, "mechanism_anchor"), (3, "new_candidate")):
        entry = deepcopy(payload["assessments"][0])
        entry["assessment"].update(id=f"test-{number}", role=role)
        action = deepcopy(next(item for item in payload["artifacts"] if item["id"] == "action"))
        action["id"] = f"action-{number}"
        action["sha256"] = digest({k: v for k, v in action.items() if k != "sha256"})
        entry["assessment"]["action"] = {"id": action["id"], "sha256": action["sha256"]}
        review = deepcopy(next(item for item in payload["artifacts"] if item["id"] == "review"))
        review["id"] = f"review-{number}"
        review["content"]["assessment_hash"] = digest(entry["assessment"])
        review["sha256"] = digest({k: v for k, v in review.items() if k != "sha256"})
        entry["review"] = {"id": review["id"], "sha256": review["sha256"]}
        payload["artifacts"].extend([action, review])
        payload["assessments"].append(entry)
    rows = PriorityRelease.model_validate(rehash(payload)).rows()
    assert [(r["id"], r["rank"]) for r in rows] == [("test-1", 1), ("test-2", 1), ("test-3", 1)]


def test_release_verified_review_may_follow_scientific_cutoff():
    payload = release_payload()
    release = PriorityRelease.model_validate(payload)
    assert release.rows()[0]["result"]["score_display"] == 7100
    assert release.rows()[0]["rank"] == 1
    assert release.manifest_sha256 == digest(
        release.model_dump(mode="json", exclude={"manifest_sha256"})
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "tampered",
        "unresolved",
        "empty_evidence",
        "future",
        "unregistered_rule",
        "false_target",
    ],
)
def test_release_rejects_broken_lineage(mutation):
    payload = release_payload()
    if mutation == "duplicate":
        payload["assessments"].append(deepcopy(payload["assessments"][0]))
    elif mutation == "tampered":
        payload["campaign"]["budget"]["cpu_core_hours"] = 1e9
    elif mutation == "unresolved":
        payload["assessments"][0]["assessment"]["material"]["id"] = "missing"
    elif mutation == "empty_evidence":
        item = payload["artifacts"][0]
        item["content"] = {}
        item["sha256"] = digest({k: v for k, v in item.items() if k != "sha256"})
    elif mutation == "future":
        item = payload["artifacts"][0]
        item["available_at"] = "2026-09-03T00:00:00Z"
        item["sha256"] = digest({k: v for k, v in item.items() if k != "sha256"})
    elif mutation == "unregistered_rule":
        payload["assessments"][0]["assessment"]["dimensions"]["pairing"]["rule_id"] = (
            "not-registered"
        )
    else:
        item = next(i for i in payload["artifacts"] if i["kind"] == "state")
        item["content"].update(pressure_status="reported", pressure_gpa=200.0)
        item["sha256"] = digest({k: v for k, v in item.items() if k != "sha256"})
        payload["assessments"][0]["assessment"]["state"]["sha256"] = item["sha256"]
    with pytest.raises(ValueError):
        PriorityRelease.model_validate(rehash(payload))


async def test_rps_publication_is_opt_in(client, monkeypatch, tmp_path):
    from config import get_settings
    from services.research_priority import canonical_json

    settings = get_settings()
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", False)
    response = await client.get("/v1/discovery/rps/releases")
    assert response.json()["status"] == "not_published"
    assert response.json()["items"] == []
    assert (await client.get("/v1/discovery/rps/policy")).json()["policy_hash"] == POLICY_HASH
    payload = release_payload()
    # pytest temporary file, never the configured production directory.
    path = tmp_path / "synthetic-release.json"
    path.write_text(canonical_json(payload), encoding="utf-8")
    monkeypatch.setattr(settings, "discovery_rps_public_enabled", True)
    monkeypatch.setattr(settings, "discovery_rps_release_dir", str(tmp_path))
    monkeypatch.setattr(
        settings,
        "discovery_rps_approved_releases",
        {"synthetic-release": payload["manifest_sha256"]},
    )
    response = await client.get("/v1/discovery/rps/releases/synthetic-release/assessments")
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["result"]["score_display"] == 7100
    etag = response.headers["etag"]
    assert (
        await client.get(
            "/v1/discovery/rps/releases/synthetic-release/assessments",
            headers={"If-None-Match": etag},
        )
    ).status_code == 304
    detail = await client.get("/v1/discovery/rps/releases/synthetic-release/assessments/test-1")
    assert detail.json()["evidence"][0]["source"]["locator"] == "test case 1"
    assert {item["id"] for item in detail.json()["evidence"]} == {"source", "execution-source"}
    assert len(detail.json()["assessment"]["action_requirements"]["resources"]) == 5
    assert (
        detail.json()["action"]["action_requirements_hash"]
        == detail.json()["result"]["action_requirements_hash"]
    )
    group = await client.get(
        "/v1/discovery/rps/releases/synthetic-release/assessments?group=mechanism&limit=1"
    )
    assert group.json()["total"] == 0 and group.json()["release_total"] == 1
    assert group.json()["items"] == [] and group.json()["group"] == "mechanism"
    assert (await client.get("/v1/discovery/rps/releases/missing/assessments")).status_code == 404
    path.write_text("{}", encoding="utf-8")
    assert (
        await client.get("/v1/discovery/rps/releases/synthetic-release/assessments")
    ).status_code == 503
