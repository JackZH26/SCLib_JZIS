"""Real SQL→0054/0064/0067 capture→v3 replay, all source/science synthetic."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa

from models.db import Base
from models.ml_task_v2 import CONTEXT_VERSION, selector_for
from models.ml_task_v3 import REVIEW_POLICY
from services import research_publication
from services.ml_dataset_builder_v3 import build_task_dataset_v3, verify_task_dataset_v3
from services.ml_feature_review_companion import verify_ml_review_companion
from services.ml_review_capture import capture_ml_review_companion
from services.ml_scientific_features import validate_property_feature
from services.research_access import active_grant
from services.research_release_manifest import canonical, digest
from tests.test_ml_physical_feature_sql import (
    assert_fair_views,
    audit_for,
    compile_scientific,
    computed_property,
    freeze_scientific_candidates,
    seed_scientific_candidates,
    write_cli_capsule,
)
from tests.test_ml_review_capture import reviewed_fixture, stable
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as db_session
from tests.test_research_publication import actors
from tests.test_research_release_schema import capture as capture_frozen
from tests.test_scientific_adjudication_schema import capture, decision_for, item_for, request_for
from tests.test_scientific_pending_import import _finish, _start, seed_import


def compiler_inputs(seeded, review):
    inputs = seeded["inputs"]
    task = deepcopy(inputs["task"])
    task.update(version="ml-task/3.0.0", exact_result_review_policy=REVIEW_POLICY)
    return {
        "manifest": inputs["release"]["manifest"],
        "artifact_bytes": inputs["artifact_bytes"],
        "expected_manifest_sha256": inputs["release"]["manifest_sha256"],
        "companion": inputs["companion"],
        "expected_companion_sha256": digest(inputs["companion"]),
        "review_companion": review,
        "expected_review_companion_sha256": digest(review),
        "task": task,
        "expected_task_sha256": digest(task),
    }


def assignments(bundle):
    return {row["example_id"]: (row["group_id"], row["split"]) for row in bundle["rows"]}


async def append_review(db, seeded, key, *, decision="reject"):
    prop = seeded["fixture"]["physics"][key]["phonon_min_frequency"]["property"]
    subject = dict(await add(db, "scientific_result_subjects", **await capture(db, prop["id"])))
    item = await item_for(
        db, subject, profile="recorded-sampled-frequency-fidelity/1.0.0", decision=decision
    )
    reviewer = {
        "reviewer": seeded["people"]["reviewer"],
        "grant": await active_grant(db, seeded["people"]["reviewer"], role="reviewer"),
    }
    request = await request_for(db, reviewer, [item])
    result = await decision_for(db, request, subject, item)
    await db.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    await stable(db)
    return result


async def test_actual_unreviewed_v3_preserves_v2_raw_baseline_and_fair_views(db_session):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["phonon_min_frequency"])
    original = canonical(
        {
            "manifest": seeded["inputs"]["release"]["manifest"],
            "source_companion": seeded["inputs"]["companion"],
        }
    )
    review = await capture_ml_review_companion(db_session, **seeded["args"])
    arguments = compiler_inputs(seeded, review)
    old = compile_scientific(seeded["inputs"])
    bundle = build_task_dataset_v3(**arguments)
    assert bundle == build_task_dataset_v3(**arguments)
    assert assignments(bundle) == assignments(old)
    assert bundle["cohorts"] == old["cohorts"]
    assert bundle["split_report"] == old["split_report"]
    assert bundle["views"]["C@B"]["preprocessing"] == old["views"]["C@B"]["preprocessing"]
    for name, view in bundle["views"].items():
        assert view["preprocessing"] == old["views"][name]["preprocessing"]
        assert [row["raw_features"] for row in view["rows"]] == [
            row["raw_features"] for row in old["views"][name]["rows"]
        ]
    assert [row["assignment_sha256"] for row in bundle["rows"]] != [
        row["assignment_sha256"] for row in old["rows"]
    ]
    assert_fair_views(bundle)
    verified = verify_task_dataset_v3(bundle, expected_bundle_sha256=digest(bundle), **arguments)
    assert verified["integrity_verified"] is True and verified["ml_training_approved"] is False
    assert all(value is False for value in bundle["authority"].values())
    assert original == canonical(
        {
            "manifest": seeded["inputs"]["release"]["manifest"],
            "source_companion": seeded["inputs"]["companion"],
        }
    )


@pytest.mark.parametrize("decision", ["reject", "request_clarification"])
async def test_exact_negative_rebuilds_optional_cohorts_but_not_base_labels_or_splits(
    db_session, decision
):
    seeded = await reviewed_fixture(
        db_session, decision=decision, properties=["phonon_min_frequency"]
    )
    review = await capture_ml_review_companion(db_session, **seeded["args"])
    old = compile_scientific(seeded["inputs"])
    bundle = build_task_dataset_v3(**compiler_inputs(seeded, review))
    identifier = str(seeded["fixture"]["candidates"][seeded["first"]]["example"]["id"])
    assert bundle["coverage"]["cohort_counts"] == {"B": 5, "P": 4, "S": 5, "PS": 4}
    assert assignments(bundle) == assignments(old)
    assert bundle["views"]["C@B"]["preprocessing"] == old["views"]["C@B"]["preprocessing"]
    assert identifier in bundle["cohorts"]["B"]["example_ids"]
    assert identifier not in bundle["cohorts"]["P"]["example_ids"]
    assert (
        "exact_result_review_held"
        in audit_for(bundle, seeded["fixture"], seeded["first"], "phonon_min_frequency")[
            "reason_codes"
        ]
    )
    assert (
        audit_for(bundle, seeded["fixture"], seeded["first"], "structure")["status"] == "admitted"
    )
    assert_fair_views(bundle)


async def test_actual_shared_scientific_context_does_not_reject_unrelated_sibling_feature(
    db_session,
):
    seeded = await reviewed_fixture(db_session)
    review = await capture_ml_review_companion(db_session, **seeded["args"])
    bundle = build_task_dataset_v3(**compiler_inputs(seeded, review))
    assert bundle["coverage"]["cohort_counts"] == {"B": 5, "P": 5, "S": 5, "PS": 5}
    first = seeded["first"]
    assert (
        audit_for(bundle, seeded["fixture"], first, "phonon_min_frequency")["status"] == "excluded"
    )
    assert audit_for(bundle, seeded["fixture"], first, "band_gap")["status"] == "admitted"
    view = bundle["views"]["CP@P"]
    identifier = str(seeded["fixture"]["candidates"][first]["example"]["id"])
    row = next(row for row in view["rows"] if row["example_id"] == identifier)
    assert row["raw_features"][view["feature_names"].index("phonon_min_frequency")] is None
    assert row["raw_features"][view["feature_names"].index("band_gap")] == 0.0
    assert_fair_views(bundle)


async def test_later_train_property_rejection_refits_raw_subset_and_preserves_old_replay(
    db_session,
):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["phonon_min_frequency"])
    before_review = await capture_ml_review_companion(db_session, **seeded["args"])
    before_args = compiler_inputs(seeded, before_review)
    before = build_task_dataset_v3(**before_args)
    selected = next(row for row in before["rows"] if row["split"] == "train")
    key = next(
        key
        for key, candidate in seeded["fixture"]["candidates"].items()
        if str(candidate["example"]["id"]) == selected["example_id"]
    )
    await append_review(db_session, seeded, key)
    after_review = await capture_ml_review_companion(db_session, **seeded["args"])
    after = build_task_dataset_v3(**compiler_inputs(seeded, after_review))
    assert digest(after_review) != digest(before_review)
    assert assignments(before) == assignments(after)
    assert after["cohorts"]["P"]["example_ids"] == sorted(
        set(before["cohorts"]["P"]["example_ids"]) - {selected["example_id"]}
    )
    old_fit, new_fit = [
        bundle["views"]["CP@P"]["preprocessing"]["parameters"] for bundle in (before, after)
    ]
    assert new_fit["train_row_count"] == old_fit["train_row_count"] - 1
    assert new_fit != old_fit
    assert after["views"]["C@B"]["preprocessing"] == before["views"]["C@B"]["preprocessing"]
    assert_fair_views(after)
    assert before == build_task_dataset_v3(**before_args)
    assert (
        verify_task_dataset_v3(before, expected_bundle_sha256=digest(before), **before_args)[
            "integrity_verified"
        ]
        is True
    )


@pytest.mark.parametrize("target", ["feature", "fit", "assignment", "review_audit", "authority"])
async def test_full_v3_recompute_rejects_repinned_output_tampering(db_session, target):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["phonon_min_frequency"])
    review = await capture_ml_review_companion(db_session, **seeded["args"])
    arguments = compiler_inputs(seeded, review)
    bundle = build_task_dataset_v3(**arguments)
    changed = deepcopy(bundle)
    if target == "feature":
        changed["views"]["CP@P"]["rows"][0]["raw_features"][-1] = 9999.0
    elif target == "fit":
        changed["views"]["CP@P"]["preprocessing"]["parameters"]["statistics"][0]["median"] = 9999.0
    elif target == "assignment":
        changed["rows"][0]["split"] = "invalid"
    elif target == "review_audit":
        changed["dependency_manifest"]["feature_admission"][0]["captured_review"][
            "reason_codes"
        ] = ["fabricated"]
    else:
        changed["authority"]["ml_training_approved"] = True
    with pytest.raises(ValueError, match="recomputation mismatch"):
        verify_task_dataset_v3(changed, expected_bundle_sha256=digest(changed), **arguments)


async def test_real_capture_new_cli_build_verify_and_no_network_or_database_connections(
    db_session, tmp_path
):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["phonon_min_frequency"])
    review = await capture_ml_review_companion(db_session, **seeded["args"])
    arguments = compiler_inputs(seeded, review)
    inputs = {**seeded["inputs"], "task": arguments["task"]}
    cli_args = write_cli_capsule(tmp_path, inputs)
    review_path = tmp_path.resolve() / "review.json"
    review_path.write_bytes(canonical(review))
    cli_args += [
        "--review-companion",
        str(review_path),
        "--review-companion-sha256",
        digest(review),
    ]
    output = tmp_path.resolve() / "compiled-v3.json"
    root = Path(__file__).resolve().parents[2]
    # The child owns no service capability. Audit hooks make an attempted socket
    # connection/process escape fail, rather than merely pointing at port 1.
    runner = """import runpy,sys
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'}:
        raise RuntimeError('offline_io_forbidden')
sys.addaudithook(audit)
path=sys.argv.pop(1)
runpy.run_path(path,run_name='__main__')
"""

    def invoke(mode, extra):
        return subprocess.run(
            [
                sys.executable,
                "-c",
                runner,
                str(root / "scripts/ml_reviewed_dataset.py"),
                mode,
                *cli_args,
                *extra,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env={
                **os.environ,
                "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
                "REDIS_URL": "redis://127.0.0.1:1/0",
            },
        )

    built = invoke("build", ["--output", str(output)])
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)["output_written"] is True
    document = json.loads(output.read_bytes())
    assert document == build_task_dataset_v3(**arguments)
    verified = invoke("verify", ["--bundle", str(output), "--bundle-sha256", digest(document)])
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["integrity_verified"] is True
    assert output.stat().st_mode & 0o777 == 0o600


async def test_current_shared_source_hold_rebuilds_features_without_erasing_base_or_old_replay(
    db_session,
):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["phonon_min_frequency"])
    old_review = await capture_ml_review_companion(db_session, **seeded["args"])
    old_arguments = compiler_inputs(seeded, old_review)
    before = build_task_dataset_v3(**old_arguments)
    source = seeded["fixture"]["feature_bindings"][(seeded["first"], "phonon_min_frequency")][
        "source"
    ]
    papers = Base.metadata.tables["papers"]
    await db_session.execute(
        papers.update()
        .where(papers.c.id == source["revision"]["paper_id"])
        .values(status="retracted")
    )
    await stable(db_session)
    new_review = await capture_ml_review_companion(db_session, **seeded["args"])
    after = build_task_dataset_v3(**compiler_inputs(seeded, new_review))
    assert assignments(after) == assignments(before)
    assert after["coverage"]["cohort_counts"] == {"B": 5, "P": 4, "S": 4, "PS": 4}
    assert (
        "dependency_feature_source_held"
        in audit_for(after, seeded["fixture"], seeded["first"], "phonon_min_frequency")[
            "reason_codes"
        ]
    )
    assert (
        "feature_source_review_held"
        in audit_for(after, seeded["fixture"], seeded["first"], "structure")["reason_codes"]
    )
    assert_fair_views(after)
    assert before == build_task_dataset_v3(**old_arguments)


async def test_actual_native_import_both_scopes_accepted_still_cannot_become_dfpt_feature(
    db_session,
):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    native = await seed_import(db_session)
    started = await _start(db_session, native)
    await stable(db_session)
    finished = await _finish(db_session, native, started)
    assert finished["status"] == "success_pending"
    property_id = UUID(finished["row_ids"]["property"])
    first = next(iter(fixture["candidates"]))
    feature_input = await add(
        db_session,
        "ml_example_inputs",
        example_id=fixture["candidates"][first]["example"]["id"],
        input_kind="property",
        input_event_id=UUID(finished["row_ids"]["event"]),
        input_property_id=property_id,
        feature_key="phonon_min_frequency",
        matching_policy_version="ml-feature-application/1.0.0",
        record_sha256=digest({"synthetic_native_input": str(property_id)}),
    )
    # Retain actual source/report/coordinate/producer bytes. Do not invent the
    # missing upstream calculation manifests or a public-time source witness.
    blobs = Base.metadata.tables["scientific_import_blobs"]
    actual_blobs = (
        await db_session.execute(
            sa.select(blobs.c.bytes_sha256, blobs.c.payload).where(
                blobs.c.package_id == UUID(started["package_id"])
            )
        )
    ).all()
    fixture["args"]["artifact_bytes"].update({sha: bytes(payload) for sha, payload in actual_blobs})
    selector = selector_for(fixture["protocols"]["phonon_min_frequency"])
    fixture["task"]["physical_features"].append(selector)
    fixture["task"]["physical_features"].sort(key=lambda row: row["feature_key"])
    inputs = await freeze_scientific_candidates(db_session, fixture)
    await stable(db_session)
    subject = dict(
        await add(
            db_session, "scientific_result_subjects", **await capture(db_session, property_id)
        )
    )
    reviewer = {
        "reviewer": native["actors"]["reviewer"],
        "grant": await active_grant(db_session, native["actors"]["reviewer"], role="reviewer"),
    }
    fidelity = await item_for(db_session, subject)
    fidelity_request = await request_for(db_session, reviewer, [fidelity])
    fidelity_decision = await decision_for(db_session, fidelity_request, subject, fidelity)
    science = await item_for(db_session, subject, profile="sampled-phonon-minimum-review/1.0.0")
    science["extraction_decision_id"] = str(fidelity_decision["id"])
    science_request = await request_for(db_session, reviewer, [science])
    scientific_decision = await decision_for(db_session, science_request, subject, science)
    assert fidelity_decision["decision"] == scientific_decision["decision"] == "accept"
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    grant = await research_publication.grant_role(
        db_session,
        actor_user_id=native["actors"]["admin"],
        user_id=native["actors"]["admin"],
        role="curator",
        reason_code="synthetic_private_full_audit",
        dry_run=False,
    )
    await stable(db_session)
    capture_args = {
        "actor_user_id": native["actors"]["admin"],
        "expected_actor_grant_id": UUID(grant["id"]),
        "export_scope": "ml_review_full_audit/1.0.0",
        "base_manifest": inputs["release"]["manifest"],
        "expected_base_manifest_sha256": inputs["release"]["manifest_sha256"],
        "source_companion": inputs["companion"],
        "expected_source_companion_sha256": digest(inputs["companion"]),
        "artifact_bytes": inputs["artifact_bytes"],
    }
    review = await capture_ml_review_companion(db_session, **capture_args)
    receipt = verify_ml_review_companion(
        review,
        **{
            key: capture_args[key]
            for key in (
                "base_manifest",
                "expected_base_manifest_sha256",
                "source_companion",
                "expected_source_companion_sha256",
            )
        },
        expected_review_companion_sha256=digest(review),
    )
    assert [
        scope["status"] for scope in receipt["property_statuses"][str(property_id)]["scopes"]
    ] == ["accepted", "accepted"]
    bundle = build_task_dataset_v3(**compiler_inputs({"inputs": inputs}, review))
    assert bundle["coverage"]["cohort_counts"]["B"] == 5
    audit = next(
        row
        for row in bundle["dependency_manifest"]["feature_admission"]
        if row["input_id"] == str(feature_input["id"])
    )
    assert audit["status"] == "excluded"
    assert "independent_feature_source_binding_missing" in audit["reason_codes"]
    # Independent existing semantic validation makes the method/conditions
    # failure explicit; the mismatched material alone is not the evidence here.
    rows = {
        name: await capture_frozen(db_session, table, UUID(finished["row_ids"][name]))
        for name, table in (
            ("property", "event_properties"),
            ("event", "research_events"),
            ("state", "material_states"),
            ("run", "research_runs"),
            ("structure", "structure_records"),
        )
    }
    assert rows["run"]["run_kind"] == rows["event"]["event_type"] == "extraction"
    assert rows["event"]["review_status"] == rows["event"]["validity_status"] == "pending"
    assert rows["state"]["pressure_gpa"] is None and rows["state"]["temperature_k"] is None
    context = {
        "version": CONTEXT_VERSION,
        "normal_state": True,
        "target_derived": False,
        "protocol": fixture["protocols"]["phonon_min_frequency"],
    }
    validation = validate_property_feature(
        rows["property"],
        rows["event"],
        rows["state"],
        rows["run"],
        rows["structure"],
        selector,
        context,
        source_formula="AlAs",
    )
    assert validation["status"] != "admitted"
    assert {
        "computed_calculation_required",
        "completed_exact_producer_run_required",
        "input_pressure_unresolved",
        "input_temperature_unresolved",
    } <= set(validation["reason_codes"])
    assert all(value is False for value in bundle["authority"].values())


async def test_captured_acceptance_never_bypasses_actual_tc_ancestor_in_retained_producer_input(
    db_session,
):
    people = await actors(db_session)
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    first = next(iter(fixture["candidates"]))
    candidate = fixture["candidates"][first]
    target = {
        "table": "material_claims",
        "row_id": str(candidate["claim"]["id"]),
        "event_id": candidate["event"]["id"],
    }
    item = await computed_property(
        db_session,
        fixture,
        first,
        "phonon_min_frequency",
        structure=fixture["structures"][first],
        protocol=fixture["protocols"]["phonon_min_frequency"],
        settings=fixture["settings"]["phonon_min_frequency"],
        reference_artifacts=fixture["reference_artifacts"],
        value=1.0,
        dependencies=[target],
    )
    fixture["physics"][first]["phonon_min_frequency"] = item
    fixture["task"]["physical_features"].append(
        selector_for(fixture["protocols"]["phonon_min_frequency"])
    )
    fixture["task"]["physical_features"].sort(key=lambda row: row["feature_key"])
    inputs = await freeze_scientific_candidates(db_session, fixture)
    await stable(db_session)
    seeded = {"inputs": inputs, "fixture": fixture, "people": people}
    await append_review(db_session, seeded, first, decision="accept")
    grant = await research_publication.grant_role(
        db_session,
        actor_user_id=people["admin"],
        user_id=people["admin"],
        role="curator",
        reason_code="synthetic_private_full_audit",
        dry_run=False,
    )
    await stable(db_session)
    review = await capture_ml_review_companion(
        db_session,
        actor_user_id=people["admin"],
        expected_actor_grant_id=UUID(grant["id"]),
        export_scope="ml_review_full_audit/1.0.0",
        base_manifest=inputs["release"]["manifest"],
        expected_base_manifest_sha256=inputs["release"]["manifest_sha256"],
        source_companion=inputs["companion"],
        expected_source_companion_sha256=digest(inputs["companion"]),
        artifact_bytes=inputs["artifact_bytes"],
    )
    bundle = build_task_dataset_v3(**compiler_inputs(seeded, review))
    audit = audit_for(bundle, fixture, first, "phonon_min_frequency")
    assert audit["status"] == "excluded" and "target_dependency" in audit["reason_codes"]
    assert audit["captured_review"]["reason_codes"] == []
    assert (
        audit["validation"]["status"] == "admitted"
    )  # scalar contract alone cannot override the DAG
    assert len(bundle["rows"]) == 5 and bundle["coverage"]["cohort_counts"]["B"] == 5
    assert audit_for(bundle, fixture, first, "band_gap")["status"] == "admitted"
    run = next(
        row
        for row in bundle["dependency_manifest"]["run_manifests"]
        if row["ref"] == ["event_properties", str(item["property"]["id"])]
    )
    assert ["material_claims", str(candidate["claim"]["id"])] in run["dependencies"]
