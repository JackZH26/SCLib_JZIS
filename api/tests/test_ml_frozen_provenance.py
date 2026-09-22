"""Frozen-row/source-review adversaries, using actual synthetic SQL capsules."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest
import pytest_asyncio

from services import ml_frozen_provenance as provenance
from services.research_release_manifest import canonical, digest
from services.source_registry import resolve_claim_source_witnesses
from tests.test_ml_task_dataset_sql import (
    add_target_derived_feature,
    freeze_task_candidates,
    seed_task_candidates,
)
from tests.test_research_freeze import db_session as db_session


@pytest_asyncio.fixture(loop_scope="function")
async def captured(db_session):
    fixture = await seed_task_candidates(db_session)
    lineage = await add_target_derived_feature(db_session, fixture)
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    return ({(item["table"], item["row_id"]): item for item in release["manifest"]["rows"]},
            artifact_bytes, fixture, lineage)


def root_ref(captured):
    return "material_claims", str(captured[2]["candidates"]["one"]["claim"]["id"])


def resolve(captured):
    return provenance.resolve_result_context(captured[0], root_ref(captured), captured[1])


def row(rows, table):
    return next(value for key, value in rows.items() if key[0] == table)


def reseal(envelope, *, registry=False):
    if registry:
        values = provenance._sql_values(envelope["table"], envelope["data"])
        envelope["data"]["record_sha256"] = digest({key: value for key, value in values.items()
                                                     if key not in {"created_at", "record_sha256"}})
    envelope["row_sha256"] = digest(envelope["data"])


async def test_frozen_exact_witness_matches_actual_existing_registry_resolver(db_session, captured):
    current = (await resolve_claim_source_witnesses(db_session, [root_ref(captured)[1]]))[root_ref(captured)[1]]
    context = resolve(captured)
    assert list(context.root.witnesses) == current
    assert context.root.temporal["status"] == "known_by"
    assert context.root.temporal["result_available_at"] == "2020-01-01T00:00:00Z"
    assert context.root.temporal["captured_at"] == "2026-01-01T00:00:00Z"
    assert context.root.temporal["first_appearance_established"] is False
    assert context.scientific_acceptance is context.reviewer_authority_authenticated is context.ml_training_approved is False
    assert "event_scientific_decision_contract_unavailable" in context.reason_codes
    assert context.root.source_audit[0]["review_binding_verified"] is True


async def test_batch_validates_once_shares_immutable_nodes_and_preserves_every_exact_hop(captured, monkeypatch):
    calls = []
    actual = provenance._rows
    def counted(rows):
        calls.append(len(rows))
        return actual(rows)
    monkeypatch.setattr(provenance, "_rows", counted)
    contexts = provenance.resolve_result_contexts(captured[0], captured[1])
    assert len(calls) == 1 and len(contexts) == 3
    target = root_ref(captured)
    leaf = ("event_properties", str(captured[3]["properties"][-1]["id"]))
    context = contexts[leaf]
    assert {node.ref for node in context.nodes} == set(contexts)
    assert len(context.edges) == 2 and all(edge.link_type == "derives_from" for edge in context.edges)
    assert all(edge.same_material and edge.same_state for edge in context.edges)
    assert next(node for node in context.nodes if node.ref == target) is contexts[target].root
    assert context.root.dependency_complete is True
    assert context.root.temporal["status"] == "unknown"
    assert context.root.temporal["result_available_at"] is None
    assert "property_source_occurrence_contract_unavailable" in context.root.reason_codes
    assert set(contexts[target].group_keys) <= set(context.group_keys)


async def test_result_and_locator_are_detached_and_frozen_without_mutable_input_aliases(captured):
    result = resolve(captured)
    before = result.root.result_data
    result.root.result_data["raw_record"].clear()
    result.root.temporal["witnesses"].clear()
    result.root.source_audit.clear()
    captured[0][root_ref(captured)]["data"]["raw_record"].clear()
    assert result.root.result_data == before and result.root.temporal["witnesses"]
    with pytest.raises(FrozenInstanceError): result.root.state_id = "changed"
    with pytest.raises(TypeError): result.root.witnesses[0].locator["page"] = 99


@pytest.mark.parametrize("kind", ["source", "review"])
@pytest.mark.parametrize("change", ["missing", "different_bytes"])
async def test_actual_capture_and_review_bytes_are_both_required_not_only_metadata(captured, kind, change):
    occurrence = row(captured[0], "claim_source_occurrences")["data"]
    artifact = (captured[0][("evidence_artifacts", occurrence["review_artifact_id"])]["data"]
                if kind == "review" else row(captured[0], "source_captures")["data"])
    key = artifact["bytes_sha256"]
    if change == "missing": captured[1].pop(key)
    else: captured[1][key] = b"different synthetic bytes"
    context = resolve(captured)
    assert context.root.temporal["status"] == "uncertain"
    assert context.root.temporal["result_available_at"] is None
    assert context.root.witnesses[0].binding_verified is False


async def test_verified_unrelated_review_bytes_do_not_witness_exact_metadata_payload(captured):
    occurrence = row(captured[0], "claim_source_occurrences")["data"]
    artifact = captured[0][("evidence_artifacts", occurrence["review_artifact_id"])]
    payload = canonical({"unrelated": "synthetic review without binding"})
    artifact["data"]["bytes_sha256"] = digest({"unrelated": "synthetic review without binding"})
    captured[1][artifact["data"]["bytes_sha256"]] = payload
    reseal(artifact)
    context = resolve(captured)
    assert "source_review_bytes_do_not_bind_payload" in context.reason_codes
    assert context.root.temporal["status"] == "uncertain"


@pytest.mark.parametrize("table", ["source_revisions", "source_captures", "claim_source_occurrences"])
async def test_frozen_outer_row_hash_cannot_replace_original_registry_hash(captured, table):
    envelope = row(captured[0], table)
    envelope["data"]["record_sha256"] = "0" * 64
    reseal(envelope)
    context = resolve(captured)
    assert "source_registry_record_hash_mismatch" in context.reason_codes
    assert context.root.temporal["status"] == "uncertain"


@pytest.mark.parametrize("change", ["claim", "mapping", "locator", "work_hold", "paper_hold"])
async def test_exact_claim_locator_work_mapping_and_frozen_hold_cannot_be_resealed_away(captured, change):
    if change == "claim":
        envelope = captured[0][root_ref(captured)]
        envelope["data"]["value_kelvin"] = 40.0
    elif change == "mapping":
        envelope = row(captured[0], "paper_work_map")
        envelope["data"]["review_status"] = "rejected"
    elif change == "locator":
        envelope = row(captured[0], "claim_source_occurrences")
        envelope["data"]["locator"] = {"table": "2", "row": 1}
    elif change == "work_hold":
        envelope = row(captured[0], "works")
        envelope["data"]["publication_status"] = "retracted"
    else:
        envelope = row(captured[0], "papers")
        envelope["data"]["status"] = "corrected"
    reseal(envelope, registry=change == "locator")
    assert resolve(captured).root.temporal["status"] == "uncertain"


async def test_work_and_claim_dates_are_not_source_revision_availability(captured):
    for key in list(captured[0]):
        if key[0] == "claim_source_occurrences": del captured[0][key]
    claim = captured[0][root_ref(captured)]
    claim["data"]["available_at"] = "1900-01-01"
    claim["data"]["raw_record"]["result_available_at"] = "1900-01-01T00:00:00Z"
    reseal(claim)
    work = row(captured[0], "works")
    work["data"]["available_at"] = "1800-01-01"
    reseal(work)
    context = resolve(captured)
    assert context.root.temporal["status"] == "unknown"
    assert context.root.temporal["result_available_at"] is None
    assert context.root.temporal["legacy_result_available_at"] == "1900-01-01"


@pytest.mark.parametrize("link_type", ["context", "supports", "refutes"])
async def test_noncausal_exact_links_retain_grouping_without_becoming_derives_from(captured, link_type):
    edge = row(captured[0], "event_evidence")
    edge["data"]["link_type"] = link_type
    reseal(edge)
    contexts = provenance.resolve_result_contexts(captured[0], captured[1])
    found = [item for context in contexts.values() for item in context.edges if item.event_evidence_id == edge["row_id"]]
    assert found and all(item.link_type == link_type for item in found)
    assert all(item.input_ref is not None for item in found)


@pytest.mark.parametrize("change", ["event_only", "foreign_state", "foreign_material"])
async def test_ambiguous_or_foreign_event_inputs_are_explicitly_incomplete(captured, change):
    edge = row(captured[0], "event_evidence")
    if change == "event_only":
        edge["data"].update(link_type="context", input_claim_id=None, input_property_id=None)
        reseal(edge)
    else:
        target_event = captured[0][("research_events", edge["data"]["input_event_id"])]
        # Resolve an actual second state/material row, never guess from labels.
        state = deepcopy(row(captured[0], "material_states"))
        from uuid import uuid4
        state["row_id"] = state["data"]["id"] = str(uuid4())
        if change == "foreign_material":
            material = deepcopy(row(captured[0], "materials"))
            material["row_id"] = material["data"]["id"] = "synthetic-other-material"
            reseal(material)
            captured[0][("materials", material["row_id"])] = material
            state["data"].update(material_id=material["row_id"], sample_id=None)
            target_event["data"]["material_id"] = material["row_id"]
            for (table, _), item in captured[0].items():
                if table == "material_claims" and item["data"]["event_id"] == target_event["row_id"]:
                    item["data"]["material_id"] = material["row_id"]
                    reseal(item)
        reseal(state)
        captured[0][("material_states", state["row_id"])] = state
        target_event["data"]["state_id"] = state["row_id"]
        reseal(target_event)
    context = provenance.resolve_result_contexts(captured[0], captured[1])
    affected = [item.root for item in context.values() if item.root.event_id == edge["data"]["event_id"]]
    assert affected and all(not node.dependency_complete for node in affected)
    reason = {"event_only": "event_only_dependency_unresolved", "foreign_state": "cross_state_dependency_unresolved",
              "foreign_material": "cross_material_dependency_unresolved"}[change]
    assert all(reason in node.reason_codes for node in affected)


async def test_identical_sample_strings_and_untrusted_example_groups_do_not_create_identity(captured):
    before = resolve(captured).group_keys
    for (table, _), envelope in captured[0].items():
        if table == "ml_examples": envelope["data"].update(duplicate_group="GLOBAL-SAME-SAMPLE", work_group="GLOBAL-SAME-WORK")
        elif table == "research_samples": envelope["data"]["sample_label"] = "GLOBAL-SAME-SAMPLE"
        elif table == "material_claims": envelope["data"]["sample_label"] = "GLOBAL-SAME-SAMPLE"
        reseal(envelope)
    assert resolve(captured).group_keys == before
    assert all("GLOBAL-SAME" not in value for _, value in before)


@pytest.mark.parametrize("kind", ["row_hash", "index_key", "result_kind", "result_missing", "rows_limit", "artifact_limit"])
async def test_malformed_bounded_callers_fail_without_partial_context(captured, kind):
    reference = root_ref(captured)
    if kind == "row_hash": captured[0][reference]["row_sha256"] = "0" * 64
    elif kind == "index_key": captured[0][("material_claims", "wrong")] = captured[0].pop(reference)
    elif kind == "result_kind": reference = ("research_events", reference[1])
    elif kind == "result_missing": reference = ("material_claims", "missing")
    elif kind == "rows_limit": captured[0].update({("bogus", str(i)): {} for i in range(1001)})
    else: captured[1].update({str(i): b"x" for i in range(201)})
    with pytest.raises(ValueError): provenance.resolve_result_context(captured[0], reference, captured[1])


@pytest.mark.parametrize("field,value", [("binding_verified", False), ("version_resolved", False),
    ("public_time_verified", False), ("public_time_verified", "true"), ("version", "unregistered-review")])
async def test_self_resealed_review_flags_and_policy_do_not_upgrade_source_availability(captured, field, value):
    occurrence = row(captured[0], "claim_source_occurrences")
    artifact = captured[0][("evidence_artifacts", occurrence["data"]["review_artifact_id"])]
    document = artifact["data"]["metadata"]["source_provenance_review"]
    document[field] = value
    artifact["data"]["record_sha256"] = digest(document)
    artifact["data"]["bytes_sha256"] = digest(document)
    captured[1][digest(document)] = canonical(document)
    occurrence["data"]["review_artifact_sha256"] = digest(document)
    reseal(artifact)
    reseal(occurrence, registry=True)
    assert resolve(captured).root.temporal["status"] == "uncertain"


async def test_legacy_claim_without_event_or_occurrence_returns_reasons_not_typeerror(captured):
    rows = captured[0]
    for key in list(rows):
        if key[0] in {"claim_source_occurrences", "event_evidence", "event_properties"}: del rows[key]
    claim = rows[root_ref(captured)]
    claim["data"].update(event_id=None, work_id=None, paper_id=None, sample_label="sample A")
    reseal(claim)
    context = resolve(captured)
    assert context.root.event_data is context.root.state_data is None
    assert context.root.temporal["status"] == "unknown"
    assert {"result_event_unresolved", "work_identity_unresolved", "sample_identity_unresolved"} <= set(context.reason_codes)


@pytest.mark.parametrize("limit", ["MAX_RESOLVED_EDGES", "MAX_CONTEXT_MEMBERSHIPS"])
async def test_expanded_graph_resources_are_bounded_before_returning_partial_context(captured, monkeypatch, limit):
    monkeypatch.setattr(provenance, limit, 1)
    with pytest.raises(ValueError, match="limit"):
        provenance.resolve_result_contexts(captured[0], captured[1])


async def test_same_work_same_sample_does_not_give_later_claim_an_earlier_versions_date(db_session):
    fixture = await seed_task_candidates(db_session, [
        {"key": "v1", "material_group": "same", "work_group": "same", "sample_group": "same",
         "available_at": "2020-01-01T00:00:00Z", "tc": 39.0},
        {"key": "v2", "material_group": "same", "work_group": "same", "sample_group": "same",
         "available_at": "2024-01-01T00:00:00Z", "tc": 39.0},
    ])
    release, artifacts = await freeze_task_candidates(db_session, fixture)
    rows = {(item["table"], item["row_id"]): item for item in release["manifest"]["rows"]}
    contexts = provenance.resolve_result_contexts(rows, artifacts)
    earlier = contexts[("material_claims", str(fixture["candidates"]["v1"]["claim"]["id"]))]
    later = contexts[("material_claims", str(fixture["candidates"]["v2"]["claim"]["id"]))]
    assert earlier.root.temporal["result_available_at"] == "2020-01-01T00:00:00Z"
    assert later.root.temporal["result_available_at"] == "2024-01-01T00:00:00Z"
    assert earlier.root.sample_id == later.root.sample_id
    assert set(earlier.group_keys) & set(later.group_keys)
