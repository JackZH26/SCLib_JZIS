"""Actual disposable SQL capsules for task-specific ML compilation.

Every source and review is synthetic. SQL review states are declarations in a
technical fixture, never authenticated reviewer authority or ML permission.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from models.ml_task import default_task
from services import research_freeze as freeze
from services import research_release_manifest as capsule
from services.ml_frozen_provenance import resolve_result_context
from services.source_registry import (
    SOURCE_REGISTRY_VERSION,
    import_source_provenance_bundle,
    normalize_source_provenance_bundle,
    provenance_sha256,
    resolve_claim_source_witnesses,
    source_occurrence_review_payload,
)
from tests.test_research_freeze import add, approved
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_release_schema import capture

db_session = _serializable_db_session


async def seed_task_candidates(db, specs=None):
    """Build a real candidate inventory, retaining bytes for every artifact."""
    specs = specs or [{"key": "one", "formula": "MgB2", "tc": 39.0}]
    token = uuid4().hex
    artifacts = {}

    async def artifact(kind, document, *, schema="synthetic-ml-fixture/1", metadata=None):
        payload = capsule.canonical(document)
        sha = hashlib.sha256(payload).hexdigest()
        artifacts[sha] = payload
        return await add(db, "evidence_artifacts", kind=kind, schema_version=schema,
            source="synthetic-disposable-ml-test", record_sha256=capsule.digest(document),
            bytes_sha256=sha, hash_status="verified", access="restricted",
            metadata=metadata if metadata is not None else {"synthetic": True})

    policies = [await artifact("policy", {"synthetic": True, "role": role})
                for role in ("task", "property_registry")]
    snapshot = await add(db, "source_snapshots", dataset_version="ml-task-" + token,
        schema_version="synthetic/1", material_count=len(specs), paper_count=len(specs))
    dataset = await add(db, "ml_dataset_snapshots", source_snapshot_id=snapshot["id"],
        name="synthetic-ml-task-" + token, version="1", label_policy_version="untrusted-legacy/1",
        feature_schema_version="untrusted-legacy/1", split_ruleset_version="untrusted-legacy/1",
        row_count=len(specs))
    candidates, materials, works, samples = {}, {}, {}, {}
    source_roots = []
    for index, spec in enumerate(specs):
        key = spec["key"]
        material_key = spec.get("material_group", key)
        work_key = spec.get("work_group", key)
        if material_key not in materials:
            parent = candidates[spec["parent_key"]]["material"]["id"] if spec.get("parent_key") else None
            materials[material_key] = await add(db, "materials", id=f"ml-task:{token}:{material_key}",
                formula=spec.get("formula", "MgB2"), formula_normalized=spec.get("formula", "MgB2"),
                parent_material_id=parent, records=[{"tc_kelvin": 7777, "synthetic_legacy": True}])
        material = materials[material_key]
        if work_key not in works:
            works[work_key] = await add(db, "works", canonical_title=f"Synthetic ML task {token} {work_key}")
        work = works[work_key]
        paper = await add(db, "papers", id=f"ml-task:{token}:{key}", source="arxiv",
            title=f"Synthetic candidate {key}", authors=[], abstract="Synthetic SQL fixture only",
            status="published")
        await add(db, "paper_work_map", paper_id=paper["id"], work_id=work["id"],
            relation_type="preprint", match_method="manual", review_status="accepted")
        locator = {"table": "1", "row": index + 1}
        source_artifact = await artifact("literature_locator", {"synthetic": True, "paper": paper["id"], **locator})
        sample_key = (material_key, spec.get("sample_group", key))
        if sample_key not in samples:
            samples[sample_key] = await add(db, "research_samples", material_id=material["id"],
                work_id=work["id"], sample_label=f"synthetic-specimen-{sample_key[1]}",
                source_artifact_id=source_artifact["id"])
        sample = samples[sample_key]
        pressure = spec.get("pressure", 0.0)
        pressure_status = spec.get("pressure_status", "explicit_ambient" if pressure == 0 else "reported")
        state_document = {"pressure_gpa": pressure, "pressure_status": pressure_status,
                          "sample_id": str(sample["id"]), "synthetic": True}
        material_state = await add(db, "material_states", material_id=material["id"],
            sample_id=sample["id"], resolution="source_scoped", condition_schema_version="synthetic/1",
            pressure_status=pressure_status, pressure_gpa=pressure, temperature_role="unknown",
            conditions={"magnetic_field_t": 0.0}, context_sha256=capsule.digest(state_document),
            source_artifact_id=source_artifact["id"])
        declared_reviewed = spec.get("reviewed", False)
        decision = await artifact("review", {"synthetic": True, "case": key,
            "purpose": "SQL declaration fixture, not authenticated scientific approval"}) if declared_reviewed else None
        event = await add(db, "research_events", material_id=material["id"], state_id=material_state["id"],
            event_type="measurement", knowledge_origin="Observed", record_sha256=capsule.digest(state_document),
            review_status="approved" if declared_reviewed else "pending",
            validity_status="accepted" if declared_reviewed else "pending",
            decision_artifact_id=decision["id"] if decision else None)
        tc = spec.get("tc", 39.0)
        raw = {"synthetic": True, "tc_kelvin": tc, "pressure_gpa": pressure,
               "sample_label": sample["sample_label"], "case": key}
        if not spec.get("missing_formula", False):
            raw["formula"] = material["formula"]
        raw.update(deepcopy(spec.get("raw_overrides", {})))
        claim_values = dict(property_type="tc", evidence_role="primary_experimental", result_status="observed",
            value_relation="exact" if tc is not None else "unreported", value_kelvin=tc,
            tc_definition=spec.get("tc_definition", "zero_resistance"), pressure_state=pressure_status,
            pressure_gpa=pressure, magnetic_field_t=0.0, measurement_method="resistivity",
            sample_label=sample["sample_label"], validity_status="accepted" if declared_reviewed else "pending")
        claim_values.update(spec.get("claim_overrides", {}))
        legacy = spec.get("legacy", False)
        claim = await add(db, "material_claims", material_id=material["id"], paper_id=paper["id"],
            work_id=work["id"], source_snapshot_id=snapshot["id"], event_id=None if legacy else event["id"],
            result_key=None if legacy else "tc-main", interpretation_revision=None if legacy else 1,
            source_record_hash=capsule.digest(raw), source_kind="table",
            extractor_version="synthetic-sql/1", source_locator=locator, raw_record=raw, **claim_values)
        await add(db, "claim_qc", claim_id=claim["id"], qc_version="synthetic/1",
            review_status="approved" if declared_reviewed else "pending",
            reviewed_at=datetime(2026, 1, 1, tzinfo=UTC) if declared_reviewed else None,
            is_gold=False, reviewer_notes="Synthetic technical fixture; no authenticated reviewer")
        member = await add(db, "snapshot_event_memberships", snapshot_id=snapshot["id"], event_id=event["id"],
            event_revision=1, source_occurrence_key=f"table:1:row:{index + 1}", locator=locator,
            source_record_sha256=capsule.digest(raw), result_manifest_sha256=capsule.digest({"claim": str(claim["id"])}))
        example = await add(db, "ml_examples", dataset_snapshot_id=dataset["id"], example_key=key,
            claim_id=claim["id"], material_id=material["id"], work_id=work["id"], split="test",
            task_type="tc_regression", label_data={"tc_kelvin": 9999, "synthetic_legacy": True},
            work_group="untrusted-" + key, material_group="untrusted-" + key,
            duplicate_group="untrusted-" + key, assignment_hash="f" * 64)
        capture_payload = capsule.canonical({"synthetic_source": True, "paper": paper["id"], "record": raw})
        capture_sha = hashlib.sha256(capture_payload).hexdigest()
        artifacts[capture_sha] = capture_payload
        bundle = {"version": SOURCE_REGISTRY_VERSION, "source_revisions": [{
            "id": str(uuid4()), "paper_id": paper["id"], "work_id": str(work["id"]),
            "revision_key": "arxiv-v1", "provider_revision": "v1", "version_status": "pinned",
            "availability_status": "known_by", "availability_basis": "verified_provider_version_history",
            "source_version_public_at": spec.get("available_at", "2020-01-01T00:00:00Z"),
            "metadata_sha256": capsule.digest({"synthetic": True, "paper": paper["id"]}),
        }], "source_captures": [], "claim_source_occurrences": []}
        bundle["source_captures"] = [{"id": str(uuid4()), "source_revision_id": bundle["source_revisions"][0]["id"],
            "capture_key": "synthetic-capture", "captured_at": "2026-01-01T00:00:00Z",
            "bytes_sha256": capture_sha, "representation": "arxiv_source"}]
        bundle["claim_source_occurrences"] = [{"id": str(uuid4()), "claim_id": str(claim["id"]),
            "work_id": str(work["id"]), "source_revision_id": bundle["source_revisions"][0]["id"],
            "capture_id": bundle["source_captures"][0]["id"], "occurrence_key": f"table-1-row-{index + 1}",
            "locator": locator, "binding_status": "pending"}]
        normalized = normalize_source_provenance_bundle(bundle)
        review = source_occurrence_review_payload(normalized["source_revisions"][0],
            normalized["source_captures"][0], normalized["claim_source_occurrences"][0], claim)
        review.update(binding_verified=True, version_resolved=True, public_time_verified=True)
        review_artifact = await artifact("review", review, schema="source-occurrence-review/1.0.0",
                                        metadata={"source_provenance_review": review})
        assert review_artifact["record_sha256"] == provenance_sha256(review)
        bundle["claim_source_occurrences"][0].update(binding_status="reviewed",
            review_artifact_id=str(review_artifact["id"]), review_artifact_sha256=review_artifact["record_sha256"])
        await import_source_provenance_bundle(db, bundle, dry_run=False)
        source_roots.extend([{"table": "snapshot_event_memberships", "row_id": str(member["id"])},
            {"table": "claim_source_occurrences", "row_id": bundle["claim_source_occurrences"][0]["id"]}])
        candidates[key] = {"material": material, "paper": paper, "work": work, "sample": sample,
            "state": material_state, "event": event, "claim": claim, "example": example,
            "source_bundle": bundle}
    snapshots = Base.metadata.tables["source_snapshots"]
    await db.execute(snapshots.update().where(snapshots.c.id == snapshot["id"]).values(
        material_count=len(materials), paper_count=len(specs)))
    return {"args": {"dataset_id": dataset["id"], "policy_artifact_ids": [item["id"] for item in policies],
                     "source_roots": source_roots, "artifact_bytes": artifacts}, "candidates": candidates}


async def freeze_task_candidates(db, fixture):
    _, arguments = await approved(db, fixture)
    result = await freeze.freeze_research_release(db, **arguments, dry_run=False)
    assert result["scientific_acceptance"] is result["ml_training_approved"] is False
    return result, arguments["artifact_bytes"]


async def add_target_derived_feature(db, fixture, key="one"):
    """Rename a two-hop target-derived input without erasing its SQL lineage."""
    candidate = fixture["candidates"][key]
    events, properties = [], []
    for index, (property_key, value, unit) in enumerate([
        ("electron_phonon_lambda", 1.2, "1"), ("dos_at_fermi", 3.0, "states/eV/formula_unit"),
    ]):
        event = await add(db, "research_events", material_id=candidate["material"]["id"],
            state_id=candidate["state"]["id"], event_type="curation", knowledge_origin="Inferred",
            record_sha256=capsule.digest({"synthetic": True, "hop": index, "key": key}))
        prop = await add(db, "event_properties", event_id=event["id"], property_key=property_key,
            relation="exact", value=value, unit=unit,
            record_sha256=capsule.digest({"synthetic": True, "property": property_key, "value": value}))
        await add(db, "event_evidence", event_id=event["id"], link_type="derives_from",
            input_event_id=events[-1]["id"] if events else candidate["event"]["id"],
            input_property_id=properties[-1]["id"] if properties else None,
            input_claim_id=None if properties else candidate["claim"]["id"])
        events.append(event)
        properties.append(prop)
    input_row = await add(db, "ml_example_inputs", example_id=candidate["example"]["id"],
        input_kind="property", input_event_id=events[-1]["id"], input_property_id=properties[-1]["id"],
        feature_key="innocent_composition_descriptor", matching_policy_version="synthetic/1",
        record_sha256=capsule.digest({"synthetic": True, "feature": str(properties[-1]["id"])}))
    return {"events": events, "properties": properties, "input": input_row}


def eligible_specs():
    return [{"key": key, "formula": formula, "tc": tc, "reviewed": True}
            for key, formula, tc in [("one", "MgB2", 39.0), ("two", "Nb", 9.2),
                                     ("three", "Pb", 7.2), ("four", "Ta", 4.5), ("five", "Sn", 3.7)]]


def compile_release(release, artifact_bytes, task=None):
    from services.ml_dataset_builder import build_task_dataset

    task = default_task() if task is None else task
    return build_task_dataset(release["manifest"], artifact_bytes=artifact_bytes,
        expected_manifest_sha256=release["manifest_sha256"], task=task,
        expected_task_sha256=capsule.digest(task))


async def test_actual_source_witnesses_and_candidate_rows_freeze_without_scientific_approval(db_session):
    fixture = await seed_task_candidates(db_session, [
        {"key": "one", "formula": "MgB2", "tc": 39.0},
        {"key": "two", "formula": "Nb", "tc": 9.2},
    ])
    claims = [item["claim"]["id"] for item in fixture["candidates"].values()]
    witnesses = await resolve_claim_source_witnesses(db_session, claims)
    assert all(len(witnesses[str(identifier)]) == 1 for identifier in claims)
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    verification = capsule.verify_manifest(release["manifest"], artifact_bytes=artifact_bytes,
        expected_manifest_sha256=release["manifest_sha256"])
    assert verification["integrity_verified"] is True
    assert verification["scientific_acceptance"] is verification["ml_training_approved"] is False
    rows = release["manifest"]["rows"]
    assert sum(row["table"] == "ml_examples" for row in rows) == 2
    assert sum(row["table"] == "source_captures" for row in rows) == 2
    assert sum(row["table"] == "claim_source_occurrences" for row in rows) == 2
    assert {row["data"]["value_kelvin"] for row in rows if row["table"] == "material_claims"} == {39.0, 9.2}
    indexed = {(row["table"], row["row_id"]): row for row in rows}
    for identifier in claims:
        context = resolve_result_context(indexed, ("material_claims", str(identifier)), artifact_bytes)
        assert context.root.temporal["status"] == "known_by"
        assert context.root.temporal["result_available_at"] == "2020-01-01T00:00:00Z"
        assert len(context.root.witnesses) == 1
        assert context.scientific_acceptance is context.ml_training_approved is False
        assert context.reviewer_authority_authenticated is False
    table = Base.metadata.tables["research_releases"]
    assert (await db_session.execute(sa.select(table.c.id).where(table.c.id == release["release_id"]))).scalar_one()


async def test_actual_freeze_preserves_transitive_target_lineage_even_after_feature_rename(db_session):
    fixture = await seed_task_candidates(db_session)
    dependency = await add_target_derived_feature(db_session, fixture)
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    assert capsule.verify_manifest(release["manifest"], artifact_bytes=artifact_bytes)["integrity_verified"] is True
    rows = {(item["table"], item["row_id"]): item["data"] for item in release["manifest"]["rows"]}
    actual_input = rows[("ml_example_inputs", str(dependency["input"]["id"]))]
    assert actual_input["feature_key"] == "innocent_composition_descriptor"
    assert actual_input["input_property_id"] == str(dependency["properties"][-1]["id"])
    edges = {row["event_id"]: row for (table, _), row in rows.items() if table == "event_evidence"}
    assert edges[str(dependency["events"][-1]["id"])]["input_property_id"] == str(dependency["properties"][0]["id"])
    assert edges[str(dependency["events"][0]["id"])]["input_claim_id"] == str(fixture["candidates"]["one"]["claim"]["id"])
    indexed = {(row["table"], row["row_id"]): row for row in release["manifest"]["rows"]}
    context = resolve_result_context(indexed, ("event_properties", str(dependency["properties"][-1]["id"])), artifact_bytes)
    assert {node.ref for node in context.nodes} == {
        ("material_claims", str(fixture["candidates"]["one"]["claim"]["id"])),
        *(("event_properties", str(row["id"])) for row in dependency["properties"]),
    }
    assert len(context.edges) == 2


async def test_frozen_candidate_compilation_uses_exact_claim_labels_and_is_reproducible(db_session):
    from services.ml_dataset_builder import verify_task_dataset

    fixture = await seed_task_candidates(db_session, eligible_specs())
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    task = default_task()
    bundle = compile_release(release, artifact_bytes, task)
    assert bundle["gate"]["status"] == "pass", bundle["coverage"]
    assert len(bundle["candidates"]) == len(bundle["rows"]) == 5
    assert all(item["status"] == "included" for item in bundle["candidates"])
    expected = {str(item["example"]["id"]): item for item in fixture["candidates"].values()}
    for row in bundle["rows"]:
        actual = expected[row["example_id"]]
        assert row["label"]["value"] == actual["claim"]["value_kelvin"]
        assert row["label"]["unit"] == "K"
        assert row["label"]["tc_definition"] == "zero_resistance"
        assert row["claim_id"] == str(actual["claim"]["id"])
        assert row["event_id"] == str(actual["event"]["id"])
        assert row["state_id"] == str(actual["state"]["id"])
    assert {row["split"] for row in bundle["rows"]} == {"train", "validation", "test"}
    assert compile_release(release, artifact_bytes, task) == bundle
    assert all(value is False for value in bundle["authority"].values())
    verify_task_dataset(bundle, manifest=release["manifest"], artifact_bytes=artifact_bytes,
        expected_manifest_sha256=release["manifest_sha256"], task=task,
        expected_task_sha256=capsule.digest(task), expected_bundle_sha256=capsule.digest(bundle))


async def test_actual_legacy_label_split_and_assignment_edits_do_not_change_training_content(db_session):
    fixture = await seed_task_candidates(db_session, eligible_specs())
    _, arguments = await approved(db_session, fixture)
    # A real SQL-captured final manifest, but rollback its pins so legacy input
    # metadata can be changed before a second independently reviewed capture.
    first_release = await freeze.freeze_research_release(db_session, **arguments, dry_run=True)
    first = compile_release(first_release, arguments["artifact_bytes"])
    assert len(first["rows"]) == 5
    examples = Base.metadata.tables["ml_examples"]
    for index, candidate in enumerate(fixture["candidates"].values()):
        await db_session.execute(examples.update().where(examples.c.id == candidate["example"]["id"]).values(
            label_data={"tc_kelvin": 8888 + index, "is_gold": True}, split="train",
            work_group="one-fake-group", material_group="one-fake-group", duplicate_group="one-fake-group",
            assignment_hash=capsule.digest({"untrusted_assignment": index})))
    second_release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    second = compile_release(second_release, artifact_bytes)
    assert len(second["rows"]) == 5
    assert first_release["manifest_sha256"] != second_release["manifest_sha256"]
    compared_fields = {"example_id", "claim_id", "label", "group_id", "split", "raw_features", "features", "missingness"}
    def training_content(bundle):
        return sorted([{key: value for key, value in row.items() if key in compared_fields}
                       for row in bundle["rows"]], key=lambda row: row["example_id"])
    assert training_content(first) == training_content(second)
    assert first["preprocessing"] == second["preprocessing"]


async def test_actual_work_sample_and_material_ancestry_force_same_split(db_session):
    specs = [
        {"key": "work_a", "formula": "MgB2", "work_group": "joint"},
        {"key": "work_b", "formula": "Nb", "work_group": "joint"},
        {"key": "sample_a", "formula": "Pb", "material_group": "sample", "sample_group": "shared"},
        {"key": "sample_b", "formula": "Pb", "material_group": "sample", "sample_group": "shared"},
        {"key": "parent", "formula": "FeSe"},
        {"key": "child", "formula": "FeSe0.5Te0.5", "parent_key": "parent"},
        {"key": "independent_a", "formula": "Ta"},
        {"key": "independent_b", "formula": "Sn"},
    ]
    fixture = await seed_task_candidates(db_session, [{**spec, "reviewed": True} for spec in specs])
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    bundle = compile_release(release, artifact_bytes)
    assert bundle["gate"]["status"] == "pass", bundle["coverage"]
    assert len(bundle["rows"]) == len(specs)
    rows = {row["example_id"]: row for row in bundle["rows"]}
    for left, right in [("work_a", "work_b"), ("sample_a", "sample_b"), ("parent", "child")]:
        pair = [rows[str(fixture["candidates"][key]["example"]["id"])] for key in (left, right)]
        assert pair[0]["group_id"] == pair[1]["group_id"]
        assert pair[0]["split"] == pair[1]["split"]
    assert len({row["group_id"] for row in rows.values()}) == 5


@pytest.mark.parametrize("kind", ["sample_trajectory", "structure_near_duplicate"])
async def test_actual_declared_grouping_links_bind_frozen_endpoint_rows_and_review_bytes(db_session, kind):
    from services.ml_dataset_builder import GROUP_REVIEW_VERSION

    specs = eligible_specs() + [{"key": "six", "formula": "Al", "tc": 1.2, "reviewed": True}]
    fixture = await seed_task_candidates(db_session, specs)
    selected = [fixture["candidates"][key] for key in ("one", "two")]
    table_name = "research_samples" if kind == "sample_trajectory" else "structure_records"
    if kind == "sample_trajectory":
        endpoint_ids = [str(item["sample"]["id"]) for item in selected]
    else:
        endpoint_ids = []
        events = Base.metadata.tables["research_events"]
        for candidate in selected:
            structure = await add(db_session, "structure_records", material_id=candidate["material"]["id"],
                structure_kind="prototype", source_version="synthetic/1",
                occupancy_context={"synthetic": True},
                record_sha256=capsule.digest({"synthetic_structure": candidate["material"]["id"]}))
            await db_session.execute(events.update().where(events.c.id == candidate["event"]["id"]).values(
                structure_id=structure["id"]))
            endpoint_ids.append(str(structure["id"]))
    endpoint_ids.sort()
    # The freezer renders captured timestamps in UTC. Hash the same actual SQL
    # row representation, not ORM defaults or guessed endpoint descriptors.
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    endpoint_rows = {identifier: await capture(db_session, table_name, identifier) for identifier in endpoint_ids}
    document = {"version": GROUP_REVIEW_VERSION, "kind": kind, "table": table_name,
        "left_id": endpoint_ids[0], "right_id": endpoint_ids[1],
        "left_row_sha256": capsule.digest(endpoint_rows[endpoint_ids[0]]),
        "right_row_sha256": capsule.digest(endpoint_rows[endpoint_ids[1]]),
        "merge_for_leakage_control": True, "reviewer_authority_authenticated": False,
        "scientific_acceptance": False}

    async def retain_review(body, label):
        payload = capsule.canonical(body)
        sha = hashlib.sha256(payload).hexdigest()
        artifact = await add(db_session, "evidence_artifacts", kind="review", schema_version=GROUP_REVIEW_VERSION,
            source="synthetic-declared-grouping-test", record_sha256=capsule.digest(body),
            bytes_sha256=sha, hash_status="verified", access="restricted", metadata={"synthetic": True})
        fixture["args"]["artifact_bytes"][sha] = payload
        # An actual owned evidence row makes the review reachable from the
        # root candidate closure. No claim or source-witness hash is rewritten.
        await add(db_session, "event_evidence", event_id=selected[0]["event"]["id"],
            link_type="source", artifact_id=artifact["id"], locator={"section": label})
        return artifact

    review = await retain_review(document, "declared leakage-control grouping")
    invalid_document = {**document, "left_row_sha256": "0" * 64}
    invalid_review = await retain_review(invalid_document, "synthetic stale endpoint pin regression")
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    indexed = {(row["table"], row["row_id"]): row for row in release["manifest"]["rows"]}
    for side, identifier in zip(("left", "right"), endpoint_ids):
        assert indexed[(table_name, identifier)]["data"] == endpoint_rows[identifier]
        assert indexed[(table_name, identifier)]["row_sha256"] == document[side + "_row_sha256"]
    assert ("evidence_artifacts", str(review["id"])) in indexed
    assert ("evidence_artifacts", str(invalid_review["id"])) in indexed
    assert artifact_bytes[review["bytes_sha256"]] == capsule.canonical(document)
    baseline = compile_release(release, artifact_bytes)
    ids = [str(candidate["example"]["id"]) for candidate in selected]
    original = {row["example_id"]: row for row in baseline["rows"]}
    assert len(baseline["rows"]) == 6
    assert original[ids[0]]["group_id"] != original[ids[1]]["group_id"]
    task = default_task()
    task["grouping_links"] = [{"kind": kind, "left_id": endpoint_ids[0], "right_id": endpoint_ids[1],
                               "review_artifact_id": str(review["id"])}]
    grouped = compile_release(release, artifact_bytes, task)
    assert grouped["gate"]["status"] == "pass"
    assert len(grouped["rows"]) == 6
    rows = {row["example_id"]: row for row in grouped["rows"]}
    assert rows[ids[0]]["group_id"] == rows[ids[1]]["group_id"]
    assert rows[ids[0]]["split"] == rows[ids[1]]["split"]
    assert len({row["group_id"] for row in grouped["rows"]}) == 5
    assert all(value is False for value in grouped["authority"].values())

    changed_bytes = {**artifact_bytes, review["bytes_sha256"]: b"changed grouping review bytes"}
    with pytest.raises(ValueError):
        compile_release(release, changed_bytes, task)
    changed_task = deepcopy(task)
    changed_task["grouping_links"][0]["review_artifact_id"] = str(invalid_review["id"])
    # This alternative artifact has genuine registered hashes and retained
    # bytes. Its endpoint hash is nevertheless wrong for the frozen SQL row.
    with pytest.raises(ValueError, match="group declaration not exactly bound"):
        compile_release(release, artifact_bytes, changed_task)


@pytest.mark.parametrize("reason,bad", [
    ("label_censored_missing_or_nonpoint", {"tc": None, "reviewed": False}),
    ("label_censored_missing_or_nonpoint", {"tc": None, "claim_overrides": {"value_relation": "lt", "value_upper_kelvin": 40.0}}),
    ("pressure_outside_task_scope_or_unknown", {"pressure": None, "pressure_status": "not_reported"}),
    ("tc_criterion_mismatch", {"tc_definition": "onset"}),
    ("declared_label_review_incomplete", {"reviewed": False}),
    ("claim_bound_composition_requires_resolution", {"missing_formula": True}),
    ("pressure_outside_task_scope_or_unknown", {"pressure": 0.0, "pressure_status": "reported"}),
    ("exact_label_revision_or_state_missing", {"legacy": True}),
    ("claim_sample_label_conflict", {"claim_overrides": {"sample_label": "different-source-specimen"}}),
    ("label_not_observed_tc_no_negative_inference", {"tc": None, "claim_overrides": {
        "property_type": "non_transition", "result_status": "not_detected", "minimum_temperature_k": 2.0}}),
])
async def test_actual_incompatible_results_are_excluded_without_invented_targets(db_session, reason, bad):
    specs = eligible_specs() + [{"key": "excluded", "formula": "Al", "reviewed": True, **bad}]
    fixture = await seed_task_candidates(db_session, specs)
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    bundle = compile_release(release, artifact_bytes)
    excluded_id = str(fixture["candidates"]["excluded"]["example"]["id"])
    candidate = next(item for item in bundle["candidates"] if item["example_id"] == excluded_id)
    assert candidate["status"] == "excluded"
    assert reason in candidate["reason_codes"]
    assert excluded_id not in {row["example_id"] for row in bundle["rows"]}
    assert len(bundle["candidates"]) == 6
    assert len(bundle["rows"]) == 5


async def test_actual_source_version_public_time_and_capture_time_are_distinct_cutoffs(db_session):
    fixture = await seed_task_candidates(db_session, eligible_specs())
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    task = default_task(cutoff="2021-01-01T00:00:00Z")
    public = compile_release(release, artifact_bytes, task)
    assert public["gate"]["status"] == "pass"
    assert len(public["rows"]) == 5
    task["temporal_mode"] = "operational_capture"
    operational = compile_release(release, artifact_bytes, task)
    assert operational["rows"] == []
    assert operational["gate"]["status"] == "no_go"
    assert len(operational["candidates"]) == 5
    assert all("label_temporal_ineligible" in row["reason_codes"] for row in operational["candidates"])


async def test_actual_legacy_available_at_never_backdates_exact_source_witness(db_session):
    specs = [{**spec, "claim_overrides": {"available_at": date(1900, 1, 1)}} for spec in eligible_specs()]
    fixture = await seed_task_candidates(db_session, specs)
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    bundle = compile_release(release, artifact_bytes, default_task(cutoff="2019-01-01T00:00:00Z"))
    assert bundle["rows"] == []
    assert bundle["gate"]["status"] == "no_go"
    assert len(bundle["candidates"]) == 5
    assert all("label_temporal_ineligible" in row["reason_codes"] for row in bundle["candidates"])


async def test_actual_transitive_target_dependency_cannot_be_laundered_by_feature_name(db_session):
    fixture = await seed_task_candidates(db_session, eligible_specs())
    await add_target_derived_feature(db_session, fixture)
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    bundle = compile_release(release, artifact_bytes)
    excluded_id = str(fixture["candidates"]["one"]["example"]["id"])
    excluded = next(item for item in bundle["candidates"] if item["example_id"] == excluded_id)
    assert excluded["status"] == "excluded"
    assert "target_dependency" in excluded["reason_codes"]
    assert excluded_id not in {row["example_id"] for row in bundle["rows"]}


async def test_owned_sibling_claim_in_capsule_is_not_an_extra_task_candidate(db_session):
    fixture = await seed_task_candidates(db_session, eligible_specs())
    candidate = fixture["candidates"]["one"]
    sibling = await add(db_session, "material_claims", material_id=candidate["material"]["id"],
        paper_id=candidate["paper"]["id"], work_id=candidate["work"]["id"],
        source_snapshot_id=candidate["claim"]["source_snapshot_id"], event_id=candidate["event"]["id"],
        result_key="unselected-sibling", interpretation_revision=1, property_type="tc",
        result_status="observed", value_relation="exact", value_kelvin=123.0,
        source_record_hash=capsule.digest({"synthetic_unselected_sibling": str(candidate["claim"]["id"])}),
        extractor_version="synthetic/1", raw_record={"synthetic": True, "tc_kelvin": 123.0, "formula": "MgB2"})
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    assert ("material_claims", str(sibling["id"])) in {
        (row["table"], row["row_id"]) for row in release["manifest"]["rows"]}
    bundle = compile_release(release, artifact_bytes)
    assert bundle["coverage"]["candidate_count"] == 5
    assert len(bundle["candidates"]) == len(bundle["rows"]) == 5
    assert str(sibling["id"]) not in {row["claim_id"] for row in bundle["candidates"]}


@pytest.mark.parametrize("target", ["manifest", "artifact", "output_label", "output_split", "output_feature"])
async def test_actual_capsule_and_compilation_tampering_fails_closed(db_session, target):
    from services.ml_dataset_builder import verify_task_dataset

    fixture = await seed_task_candidates(db_session, eligible_specs())
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    task = default_task()
    bundle = compile_release(release, artifact_bytes, task)
    changed_release = deepcopy(release)
    changed_bytes = dict(artifact_bytes)
    changed_bundle = deepcopy(bundle)
    if target == "manifest":
        row = next(item for item in changed_release["manifest"]["rows"] if item["table"] == "material_claims")
        row["data"]["value_kelvin"] = 1.0
        row["row_sha256"] = capsule.digest(row["data"])
    elif target == "artifact":
        sha = next(iter(changed_bytes))
        changed_bytes[sha] += b"tampered"
    elif target == "output_label":
        changed_bundle["rows"][0]["label"]["value"] = 123.0
    elif target == "output_split":
        row = changed_bundle["rows"][0]
        row["split"] = "train" if row["split"] != "train" else "test"
    else:
        changed_bundle["rows"][0]["features"][0] = 123.0
    with pytest.raises(ValueError):
        verify_task_dataset(changed_bundle, manifest=changed_release["manifest"], artifact_bytes=changed_bytes,
            expected_manifest_sha256=release["manifest_sha256"], task=task,
            expected_task_sha256=capsule.digest(task), expected_bundle_sha256=capsule.digest(changed_bundle))


async def cli_inputs(db, tmp_path, *, specs=None):
    fixture = await seed_task_candidates(db, eligible_specs() if specs is None else specs)
    release, artifacts = await freeze_task_candidates(db, fixture)
    # On macOS /var is a symlink; the audited reader intentionally requires
    # actual non-symlink ancestors rather than silently resolving user inputs.
    directory = tmp_path.resolve()
    capsule_directory = directory / "capsule"
    capsule_directory.mkdir()
    manifest_path = capsule_directory / "manifest.json"
    manifest_path.write_bytes(capsule.canonical(release["manifest"]))
    for sha, payload in artifacts.items():
        (capsule_directory / (sha + ".bin")).write_bytes(payload)
    task = default_task()
    task_path = directory / "task.json"
    task_path.write_bytes(capsule.canonical(task))
    output = directory / "task-dataset.json"
    return {"release": release, "artifacts": artifacts, "task": task,
            "manifest_path": manifest_path, "task_path": task_path, "output": output,
            "arguments": ["--manifest", str(manifest_path), "--manifest-sha256", release["manifest_sha256"],
                          "--task", str(task_path), "--task-sha256", capsule.digest(task)]}


def run_cli(mode, arguments):
    root = Path(__file__).resolve().parents[2]
    return subprocess.run([sys.executable, str(root / "scripts" / "ml_task_dataset.py"), mode, *arguments],
        cwd=root, env={**os.environ, "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
                      "REDIS_URL": "redis://127.0.0.1:1/0"},
        capture_output=True, text=True, timeout=30, check=False)


async def test_actual_sql_capsule_cli_build_and_independent_full_recomputation(db_session, tmp_path):
    inputs = await cli_inputs(db_session, tmp_path)
    built = run_cli("build", [*inputs["arguments"], "--output", str(inputs["output"])])
    assert built.returncode == 0, built.stderr
    report = json.loads(built.stdout)
    assert report["technical_gate"] == "pass" and report["output_written"] is True
    output_bytes = inputs["output"].read_bytes()
    bundle = json.loads(output_bytes)
    assert output_bytes == capsule.canonical(bundle)
    expected = compile_release(inputs["release"], inputs["artifacts"], inputs["task"])
    assert bundle == expected
    assert inputs["output"].stat().st_mode & 0o777 == 0o600
    independently_computed_sha = hashlib.sha256(output_bytes).hexdigest()
    assert report["bundle_sha256"] == independently_computed_sha
    verified = run_cli("verify", [*inputs["arguments"], "--bundle", str(inputs["output"]),
                                  "--bundle-sha256", independently_computed_sha])
    assert verified.returncode == 0, verified.stderr
    verification = json.loads(verified.stdout)
    assert verification["integrity_verified"] is True
    assert verification["technical_gate"] == "pass" and verification["output_written"] is False
    for key in ("scientific_acceptance", "public_release", "ml_training_approved", "reviewer_authority_authenticated"):
        assert report[key] is verification[key] is False


async def test_actual_sql_cli_no_go_retains_accounting_but_writes_no_dataset(db_session, tmp_path):
    inputs = await cli_inputs(db_session, tmp_path, specs=eligible_specs()[:2])
    result = run_cli("build", [*inputs["arguments"], "--output", str(inputs["output"])])
    assert result.returncode == 3, result.stderr
    report = json.loads(result.stdout)
    assert report["technical_gate"] == "no_go" and report["output_written"] is False
    assert report["coverage"]["candidate_count"] == 2
    assert report["gate_reason_codes"]
    assert not inputs["output"].exists()


@pytest.mark.parametrize("pin,missing", [
    ("--manifest-sha256", True), ("--task-sha256", True),
    ("--manifest-sha256", False), ("--task-sha256", False),
])
async def test_actual_sql_cli_requires_independent_matching_input_pins(db_session, tmp_path, pin, missing):
    inputs = await cli_inputs(db_session, tmp_path)
    arguments = list(inputs["arguments"])
    index = arguments.index(pin)
    if missing:
        del arguments[index:index + 2]
    else:
        arguments[index + 1] = "0" * 64
    result = run_cli("build", [*arguments, "--output", str(inputs["output"])])
    assert result.returncode == 2
    assert not inputs["output"].exists()
    assert not result.stdout
    if not missing:
        assert json.loads(result.stderr) == {"status": "invalid", "output_written": False}


@pytest.mark.parametrize("target", ["manifest", "capture", "bundle"])
async def test_actual_sql_cli_tampering_fails_without_sensitive_error_output(db_session, tmp_path, target):
    inputs = await cli_inputs(db_session, tmp_path)
    built = run_cli("build", [*inputs["arguments"], "--output", str(inputs["output"])])
    assert built.returncode == 0, built.stderr
    expected_bundle_sha = hashlib.sha256(inputs["output"].read_bytes()).hexdigest()
    if target == "manifest":
        manifest = deepcopy(inputs["release"]["manifest"])
        row = next(row for row in manifest["rows"] if row["table"] == "material_claims")
        row["data"]["value_kelvin"] = 99.0
        row["row_sha256"] = capsule.digest(row["data"])
        inputs["manifest_path"].write_bytes(capsule.canonical(manifest))
    elif target == "capture":
        row = next(row for row in inputs["release"]["manifest"]["rows"] if row["table"] == "source_captures")
        path = inputs["manifest_path"].parent / (row["data"]["bytes_sha256"] + ".bin")
        path.write_bytes(b"PRIVATE_SYNTHETIC_SOURCE_DO_NOT_EXPOSE")
    else:
        bundle = json.loads(inputs["output"].read_bytes())
        bundle["rows"][0]["label"]["value"] = 99.0
        payload = capsule.canonical(bundle)
        inputs["output"].write_bytes(payload)
        # Even a newly supplied digest cannot bypass recomputation from the
        # separately pinned original capsule and task.
        expected_bundle_sha = hashlib.sha256(payload).hexdigest()
    result = run_cli("verify", [*inputs["arguments"], "--bundle", str(inputs["output"]),
                                "--bundle-sha256", expected_bundle_sha])
    assert result.returncode == 2
    assert not result.stdout
    assert json.loads(result.stderr) == {"status": "invalid", "output_written": False}
    assert "PRIVATE_SYNTHETIC" not in result.stderr
    assert str(tmp_path.resolve()) not in result.stderr


async def test_actual_sql_cli_never_overwrites_existing_dataset(db_session, tmp_path):
    inputs = await cli_inputs(db_session, tmp_path)
    arguments = [*inputs["arguments"], "--output", str(inputs["output"])]
    assert run_cli("build", arguments).returncode == 0
    original = inputs["output"].read_bytes()
    repeated = run_cli("build", arguments)
    assert repeated.returncode == 2
    assert inputs["output"].read_bytes() == original
    assert not list(inputs["output"].parent.glob(".ml-task-*"))
