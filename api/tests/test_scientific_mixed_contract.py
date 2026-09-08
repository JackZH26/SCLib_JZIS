"""Strict mixed reporting and actual HTTP response cross-binding regressions."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import ValidationError

from models.scientific_mixed import MixedEvidenceAssociation, ScientificMixedEvidence
from models.search import AskResponse
from tests.test_scientific_mixed_ask import AMBIENT_MIXED
from tests.test_scientific_mixed_ask import mixed_generation as _mixed_generation

mixed_generation = _mixed_generation


def association_payload():
    return {
        "parent_result_revision_id": str(uuid4()),
        "result_source_snapshot_sha256": "a" * 64,
        "source_index": 1,
        "source_vector_id": "ig62_" + uuid4().hex + "_" + "b" * 64,
        "source_evidence_revision_id": str(uuid4()),
        "source_evidence_record_sha256": "c" * 64,
        "source_content_sha256": "d" * 64,
        "catalogue_relation": "same_snapshot",
    }


def completed_payload():
    return {
        "status": "completed", "result_count": 1, "source_count": 1,
        "max_selected_inputs": 2, "associations": [association_payload()],
        "reason_codes": ["numerical_explanation_not_established", "reviewed_result_passage_bridge_missing"],
    }


@pytest.mark.parametrize("value", [True, 0, 1, "false", None, {}, []])
def test_mixed_reporting_never_coerces_scientific_acceptance(value):
    with pytest.raises(ValidationError):
        ScientificMixedEvidence.model_validate({"scientific_acceptance": value})


@pytest.mark.parametrize("field,value", [
    ("status", "established"), ("status", "supported"), ("source_index", True),
    ("source_index", "1"), ("source_index", 0), ("source_index", 21),
    ("parent_result_revision_id", "not-a-uuid"),
    ("source_vector_id", "legacy_chunk_identifier"),
    ("source_content_sha256", "A" * 64),
    ("reason_code", "same_paper_proves_claim"), ("scientific_acceptance", True),
])
def test_association_disallows_positive_authority_coercion_or_loose_identity(field, value):
    payload = association_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        MixedEvidenceAssociation.model_validate(payload)


@pytest.mark.parametrize("change", [
    "over_budget", "absent_pair", "unknown_reason", "missing_qualification",
    "false_missing_result", "false_missing_original", "repeated_reason",
    "unavailable_with_inventory", "not_requested_with_inventory", "independence_claim",
])
def test_closed_inventory_refuses_inconsistent_measurements(change):
    payload = completed_payload()
    if change == "over_budget":
        payload["max_selected_inputs"] = 1
    elif change == "absent_pair":
        payload["associations"] = []
    elif change == "unknown_reason":
        payload["reason_codes"].append("raw_provider_exception")
    elif change == "missing_qualification":
        payload["reason_codes"].remove("numerical_explanation_not_established")
    elif change == "false_missing_result":
        payload["reason_codes"].append("no_matching_extraction")
    elif change == "false_missing_original":
        payload["reason_codes"].append("no_original_context")
    elif change == "repeated_reason":
        payload["reason_codes"].append(payload["reason_codes"][0])
    elif change == "unavailable_with_inventory":
        payload["status"] = "unavailable"
    elif change == "not_requested_with_inventory":
        payload["status"] = "not_requested"
    else:
        payload["independent_support_count"] = 1
    with pytest.raises(ValidationError):
        ScientificMixedEvidence.model_validate(payload)


def test_completed_zero_by_zero_is_explicitly_no_extraction_and_no_context_not_absence_of_superconductivity():
    report = ScientificMixedEvidence(status="completed", max_selected_inputs=4,
        reason_codes=["numerical_explanation_not_established", "reviewed_result_passage_bridge_missing",
                      "no_matching_extraction", "no_original_context"])
    assert report.result_count == report.source_count == 0
    assert report.associations == [] and report.scientific_acceptance is False


@pytest_asyncio.fixture(loop_scope="function")
async def mixed_payload(client, mixed_generation):
    response = await client.post("/v1/ask", json={"question": AMBIENT_MIXED, "max_sources": 3})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["scientific_results"]) == 1 and len(payload["sources"]) == 2
    assert mixed_generation["forbidden_calls"] == []
    AskResponse.model_validate(payload)
    return payload


@pytest.mark.parametrize("change", [
    "duplicate_pair", "unknown_parent", "unknown_source", "swapped_source_vectors",
    "changed_source_evidence", "changed_source_hash", "changed_source_content",
    "conflicting_parent_snapshots", "false_catalogue_relation", "non_original_source",
    "restricted_source", "stale_source", "repeated_numerical_parent",
    "causal_synthesis", "generated_assessment", "claimed_provider_tokens", "public_scientific_acceptance",
])
async def test_actual_http_response_rejects_tampered_pair_or_scientific_claim(mixed_payload, change):
    payload = deepcopy(mixed_payload)
    mixed = payload["scientific_mixed"]
    pair = mixed["associations"][0]
    if change == "duplicate_pair":
        mixed["associations"][1] = deepcopy(pair)
    elif change == "unknown_parent":
        pair["parent_result_revision_id"] = str(uuid4())
    elif change == "unknown_source":
        pair["source_index"] = 3
    elif change == "swapped_source_vectors":
        pair["source_vector_id"] = mixed["associations"][1]["source_vector_id"]
    elif change == "changed_source_evidence":
        pair["source_evidence_revision_id"] = str(uuid4())
    elif change == "changed_source_hash":
        pair["source_evidence_record_sha256"] = "0" * 64
    elif change == "changed_source_content":
        pair["source_content_sha256"] = "0" * 64
    elif change == "conflicting_parent_snapshots":
        pair["result_source_snapshot_sha256"] = "0" * 64
        pair["catalogue_relation"] = "not_same_snapshot"
    elif change == "false_catalogue_relation":
        pair["catalogue_relation"] = "not_same_snapshot"
    elif change == "non_original_source":
        payload["sources"][0]["evidence_provenance"]["chunk_kind"] = "abstract"
    elif change == "restricted_source":
        payload["sources"][0]["evidence_provenance"]["permission_status"] = "restricted"
    elif change == "stale_source":
        payload["sources"][0]["evidence_provenance"]["currentness"] = "stale"
    elif change == "repeated_numerical_parent":
        payload["scientific_results"].append(deepcopy(payload["scientific_results"][0]))
        mixed["result_count"] = 2
        mixed["max_selected_inputs"] = 4
        mixed["associations"] *= 2
    elif change == "causal_synthesis":
        payload["answer_mode"] = "synthesis"
    elif change == "generated_assessment":
        payload["assessment_scope"] = "generated_draft"
    elif change == "claimed_provider_tokens":
        payload["tokens_used"] = 1
    else:
        mixed["scientific_acceptance"] = True
    with pytest.raises(ValidationError):
        AskResponse.model_validate(payload)


async def test_unavailable_response_cannot_retain_either_half_of_completed_inventory(mixed_payload):
    payload = deepcopy(mixed_payload)
    payload["scientific_mixed"] = ScientificMixedEvidence(status="unavailable", max_selected_inputs=3,
        reason_codes=["mixed_currentness_unavailable"]).model_dump(mode="json")
    with pytest.raises(ValidationError):
        AskResponse.model_validate(payload)


async def test_synthetic_mixed_http_wire_round_trip(mixed_payload, tmp_path):
    """Only this synthetic disposable fixture is written for consumer rehearsal."""
    target = tmp_path / "synthetic-mixed-ask-response.json"
    target.write_text(AskResponse.model_validate(mixed_payload).model_dump_json(indent=2), encoding="utf-8")
    loaded = AskResponse.model_validate_json(target.read_text(encoding="utf-8"))
    assert loaded.model_dump(mode="json") == mixed_payload
    assert loaded.scientific_mixed.scientific_acceptance is False
    print("SYNTHETIC_MIXED_WIRE_PATH=" + str(target))
