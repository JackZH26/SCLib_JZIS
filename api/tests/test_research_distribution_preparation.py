"""Actual synthetic source roots; descriptor creation belongs to preparation.

No preseeded RPS descriptor artifacts, scientific acceptance, or rights grants.
Run exclusively through the guarded disposable native API test runner.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from services import research_distribution as distribution
from services import research_distribution_contract as contract
from services.priority_public_bundle import build_public_bundle
from services.research_distribution_inputs import build_inventory, load_live_closure
from services.research_priority import canonical_json, digest
from services.research_publication import grant_role, revoke_role
from tests.rps_distribution_fixtures import release_document, source_capture_context, source_context
from tests.test_priority_public_bundle import disclosure_for, reseal_public_release
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_release_schema import capture


async def preparation_fixture(db, *, root_kind="frozen_result"):
    """Actual source rows/bytes only; safe to reuse for independent HTTP tests."""
    from services import research_distribution_preparation as service

    assert root_kind in {"source_capture", "frozen_result"}
    shared = await (source_capture_context(db) if root_kind == "source_capture" else source_context(db))
    release = release_document(source_kind=shared["evidence_source_kind"])
    bundle = build_public_bundle(release, disclosure=disclosure_for(release))
    source, capsule = shared["source"], shared["capsule"]
    claim = next(row for row in capsule["manifest"]["rows"]
        if row["table"] == "material_claims" and row["row_id"] == str(source["claim"]))
    root = deepcopy(shared.get("evidence_root", {"kind": "frozen_result",
        "manifest_sha256": capsule["manifest_sha256"], "table": "material_claims",
        "row_id": claim["row_id"], "row_sha256": claim["row_sha256"]}))
    roots, identities, live_roots = [], [], []
    for artifact in sorted(release["artifacts"], key=lambda row: row["id"]):
        if artifact["kind"] == "evidence":
            roots.append({"artifact_id": artifact["id"], "root": deepcopy(root)})
        if artifact["kind"] in {"material", "state"}:
            table = "materials" if artifact["kind"] == "material" else "material_states"
            identifier = source["material"] if table == "materials" else str(source["state"])
            actual = await capture(db, table, identifier)
            identities.append({"artifact_id": artifact["id"], "table": table,
                "row_id": identifier, "row_sha256": digest(actual)})
            live_roots.append({"table": table, "row_id": identifier})
    if root_kind == "source_capture":
        live_roots.extend([{"table": "source_revisions", "row_id": root["source_revision_id"]},
                           {"table": "source_captures", "row_id": root["capture_id"]}])
    live = await load_live_closure(db, live_roots)
    required = {row["data"]["bytes_sha256"] for row in live
                if row["table"] in {"evidence_artifacts", "source_captures"}}
    known = {**shared["capsule_bytes"], **shared.get("source_bytes", {})}
    selections = {"version": service.SELECTION_VERSION, "evidence_roots": roots, "identities": identities}
    arguments = {"release": release, "selections": selections, "public_bundle": bundle,
        "expected_release_sha256": release["manifest_sha256"],
        "expected_selections_sha256": digest(selections), "expected_public_bundle_sha256": bundle["bundle_sha256"],
        "artifact_bytes": {sha: known[sha] for sha in required},
        "capsule_artifact_bytes": {capsule["manifest_sha256"]: shared["capsule_bytes"]}
            if root_kind == "frozen_result" else {}}
    assert shared["internal_artifacts"] == {}
    return {"shared": shared, "arguments": arguments, "release": release, "bundle": bundle}


def operation_arguments(context):
    return {**deepcopy(context["arguments"]), "actor_user_id": context["shared"]["actors"]["curator"],
            "request_key": "synthetic-distribution-preparation:" + uuid4().hex}


async def committed(db, arguments):
    from services import research_distribution_preparation as service
    preview = await service.prepare_distribution(db, **arguments)
    await db.commit()
    result = await service.prepare_distribution(db, **arguments,
        expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    await db.commit()
    return preview, result


@pytest.mark.parametrize("root_kind", ["source_capture", "frozen_result"])
async def test_preview_has_stable_intent_across_transactions_and_no_sql_writes(db_session, root_kind):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session, root_kind=root_kind)
    arguments = operation_arguments(context)
    await db_session.commit()
    before = await state(db_session)
    first = await service.prepare_distribution(db_session, **arguments)
    assert await state(db_session) == before
    await db_session.commit()
    second = await service.prepare_distribution(db_session, **arguments)
    assert first == second
    assert first["package"] is None and first["dry_run"] is True and first["committed"] is False
    assert first["intent_sha256"] == digest(first["intent"])
    assert first["descriptor_count"] == sum(item["kind"] != "evidence" for item in context["release"]["artifacts"])
    assert await state(db_session) == before


@pytest.mark.parametrize("root_kind", ["source_capture", "frozen_result"])
async def test_commit_generates_exact_descriptors_and_old_inventory_is_rebuildable(db_session, root_kind):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session, root_kind=root_kind)
    arguments = operation_arguments(context)
    await db_session.commit()
    before = await state(db_session)
    preview, result = await committed(db_session, arguments)
    assert result["intent_sha256"] == preview["intent_sha256"]
    assert result["committed"] is False and result["dry_run"] is False and result["replayed"] is False
    assert result["scientific_acceptance"] is result["ml_training_approved"] is result["current_authorization_checked"] is False
    inspected = await distribution.inspect_distribution(db_session, package_id=result["package"]["id"])
    bindings, known_bytes = inspected["bindings"], dict(arguments["artifact_bytes"])
    artifacts = {item["id"]: item for item in context["release"]["artifacts"]}
    generated = []
    for binding in bindings["bindings"]:
        artifact = artifacts[binding["artifact_id"]]
        if artifact["kind"] == "evidence":
            assert binding["root"]["kind"] == root_kind
            continue
        row = await capture(db_session, "evidence_artifacts", UUID(binding["root"]["evidence_artifact_id"]))
        payload = canonical_json(artifact).encode()
        checksum = hashlib.sha256(payload).hexdigest()
        assert row["kind"] == contract.INTERNAL_KINDS[artifact["kind"]]
        assert row["schema_version"] == contract.INTERNAL_SCHEMA
        assert row["record_sha256"] == row["bytes_sha256"] == checksum
        assert row["hash_status"] == "verified" and row["access"] == "restricted"
        assert row["uri"] is row["license"] is None
        assert row["source"] == "sclib:rps-distribution-preparation" and row["source_version"] == service.VERSION
        assert row["metadata"]["rps_artifact_json"].encode("utf-8") == payload
        assert json.loads(row["metadata"]["rps_artifact_json"]) == artifact
        assert row["metadata"]["preparation"]["version"] == service.VERSION
        assert set(row["metadata"]) == {"rps_artifact_json", "preparation"}
        known_bytes[checksum] = payload
        generated.append(row)
    rebuilt = await build_inventory(db_session, release=arguments["release"], bindings=bindings,
        public_bundle=arguments["public_bundle"], expected_release_sha256=arguments["expected_release_sha256"],
        expected_bindings_sha256=result["package"]["bindings_sha256"],
        expected_public_bundle_sha256=arguments["expected_public_bundle_sha256"], artifact_bytes=known_bytes,
        capsule_artifact_bytes=arguments["capsule_artifact_bytes"])
    assert rebuilt == inspected["inventory"]
    assert digest(rebuilt) == result["package"]["inventory_sha256"]
    after = await state(db_session)
    assert len(after["evidence_artifacts"]) == len(before["evidence_artifacts"]) + len(generated)
    assert len(after["research_distribution_packages"]) == len(before["research_distribution_packages"]) + 1
    assert len(after["research_distribution_dependencies"]) == len(before["research_distribution_dependencies"]) + len(rebuilt["dependencies"])
    changed = {key for key in before if before[key] != after[key]}
    assert changed <= {"evidence_artifacts", "research_distribution_packages", "research_distribution_dependencies",
                       "research_distribution_epoch", "research_publication_epoch", "research_integrity_epoch",
                       "source_lifecycle_epoch"}


@pytest.mark.parametrize("case", ["release_pin", "selection_pin", "bundle_pin", "material_pin", "state_pin",
    "missing_root", "duplicate_root", "internal_evidence_root", "frozen_result_pin", "source_bytes",
    "missing_source_bytes", "extra_source_bytes", "capsule_bytes", "missing_capsule"])
async def test_invalid_exact_source_and_identity_inputs_leave_no_orphans(db_session, case):
    from services import research_distribution_preparation as service
    root_kind = "source_capture" if case in {"source_bytes", "missing_source_bytes"} else "frozen_result"
    context = await preparation_fixture(db_session, root_kind=root_kind)
    arguments = operation_arguments(context)
    if case in {"release_pin", "selection_pin", "bundle_pin"}:
        key = {"release_pin": "expected_release_sha256", "selection_pin": "expected_selections_sha256",
               "bundle_pin": "expected_public_bundle_sha256"}[case]
        arguments[key] = "0" * 64
    elif case in {"material_pin", "state_pin"}:
        table = "materials" if case == "material_pin" else "material_states"
        next(item for item in arguments["selections"]["identities"] if item["table"] == table)["row_sha256"] = "0" * 64
    elif case == "missing_root":
        arguments["selections"]["evidence_roots"].pop()
    elif case == "duplicate_root":
        arguments["selections"]["evidence_roots"].append(deepcopy(arguments["selections"]["evidence_roots"][0]))
    elif case == "internal_evidence_root":
        arguments["selections"]["evidence_roots"][0]["root"] = {"kind": "internal_artifact",
            "evidence_artifact_id": str(uuid4()), "artifact_kind": "other", "record_sha256": "0" * 64, "bytes_sha256": "0" * 64}
    elif case == "frozen_result_pin":
        arguments["selections"]["evidence_roots"][0]["root"]["row_sha256"] = "0" * 64
    elif case in {"source_bytes", "missing_source_bytes"}:
        key = context["shared"]["evidence_root"]["bytes_sha256"]
        if case == "source_bytes":
            arguments["artifact_bytes"][key] = b"substituted source"
        else:
            arguments["artifact_bytes"].pop(key)
    elif case == "extra_source_bytes":
        payload = b"undeclared source leaf"
        arguments["artifact_bytes"][hashlib.sha256(payload).hexdigest()] = payload
    elif case == "capsule_bytes":
        payloads = next(iter(arguments["capsule_artifact_bytes"].values()))
        payloads[next(iter(payloads))] = b"substituted capsule artifact"
    elif case == "missing_capsule":
        arguments["capsule_artifact_bytes"] = {}
    if case not in {"release_pin", "selection_pin", "bundle_pin"}:
        arguments["expected_selections_sha256"] = digest(arguments["selections"])
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.prepare_distribution(db_session, **arguments)
    assert await state(db_session) == before


async def test_outer_rollback_removes_generated_artifacts_and_package(db_session):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session)
    arguments = operation_arguments(context)
    await db_session.commit()
    before = await state(db_session)
    preview = await service.prepare_distribution(db_session, **arguments)
    result = await service.prepare_distribution(db_session, **arguments,
        expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    assert result["package"] is not None
    await db_session.rollback()
    assert await state(db_session) == before


async def test_deferred_outer_failure_retains_no_partial_registration(db_session):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session)
    arguments = operation_arguments(context)
    await db_session.commit()
    before = await state(db_session)
    preview = await service.prepare_distribution(db_session, **arguments)
    await service.prepare_distribution(db_session, **arguments, expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    await db_session.execute(sa.text("CREATE TEMP TABLE synthetic_preparation_deferred (id integer PRIMARY KEY, parent integer "
        "REFERENCES synthetic_preparation_deferred(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"))
    await db_session.execute(sa.text("INSERT INTO synthetic_preparation_deferred VALUES (1,2)"))
    with pytest.raises(DBAPIError):
        await db_session.commit()
    await db_session.rollback()
    assert await state(db_session) == before


async def test_exact_replay_and_recovery_ignore_later_current_source_drift_without_writes(db_session):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session, root_kind="source_capture")
    arguments = operation_arguments(context)
    preview, result = await committed(db_session, arguments)
    papers = Base.metadata.tables["papers"]
    await db_session.execute(papers.update().where(papers.c.id == context["shared"]["source"]["paper"]).values(status="retracted"))
    await db_session.commit()
    before = await state(db_session)
    replay = await service.prepare_distribution(db_session, **arguments,
        expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    assert replay == {**result, "replayed": True}
    assert await state(db_session) == before
    await db_session.rollback()
    await db_session.execute(sa.text("SET TRANSACTION READ ONLY"))
    outcome = await service.preparation_outcome(db_session, actor_user_id=arguments["actor_user_id"],
        request_key=arguments["request_key"], expected_intent_sha256=preview["intent_sha256"])
    assert outcome["package"] == result["package"] and outcome["intent_sha256"] == preview["intent_sha256"]
    assert await state(db_session) == before


async def test_missing_preview_and_changed_intent_never_write(db_session):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session)
    arguments = operation_arguments(context)
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.prepare_distribution(db_session, **arguments, dry_run=False)
    assert await state(db_session) == before
    preview, result = await committed(db_session, arguments)
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.prepare_distribution(db_session, **arguments, expected_intent_sha256="0" * 64, dry_run=False)
    assert await state(db_session) == before
    changed = deepcopy(arguments)
    changed["selections"]["identities"][0]["row_sha256"] = "1" * 64
    changed["expected_selections_sha256"] = digest(changed["selections"])
    with pytest.raises(ValueError):
        await service.prepare_distribution(db_session, **changed,
            expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    assert await state(db_session) == before
    assert result["package"] is not None


async def test_source_drift_after_preview_rejects_commit_without_new_descriptors(db_session):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session, root_kind="source_capture")
    arguments = operation_arguments(context)
    await db_session.commit()
    preview = await service.prepare_distribution(db_session, **arguments)
    await db_session.commit()
    papers = Base.metadata.tables["papers"]
    await db_session.execute(papers.update().where(papers.c.id == context["shared"]["source"]["paper"]).values(status="retracted"))
    await db_session.commit()
    before = await state(db_session)
    with pytest.raises(service.PreparationConflict):
        await service.prepare_distribution(db_session, **arguments,
            expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("role", ["admin", "reviewer", "publisher", "member"])
async def test_only_current_curator_may_prepare(db_session, role):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session)
    arguments = operation_arguments(context)
    arguments["actor_user_id"] = context["shared"]["actors"][role]
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.prepare_distribution(db_session, **arguments)
    assert await state(db_session) == before


async def test_historical_lookup_accepts_replacement_grant_but_post_does_not_rebind(db_session):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session)
    arguments = operation_arguments(context)
    people = context["shared"]["actors"]
    preview, result = await committed(db_session, arguments)
    await revoke_role(db_session, actor_user_id=people["admin"], grant_id=people["grants"]["curator"],
        reason_code="synthetic_preparation_revoke", dry_run=False)
    await db_session.commit()
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.preparation_outcome(db_session, actor_user_id=arguments["actor_user_id"],
            request_key=arguments["request_key"], expected_intent_sha256=preview["intent_sha256"])
    assert await state(db_session) == before
    await grant_role(db_session, actor_user_id=people["admin"], user_id=people["curator"],
        role="curator", reason_code="synthetic_preparation_regrant", dry_run=False)
    await db_session.commit()
    before = await state(db_session)
    recovered = await service.preparation_outcome(db_session, actor_user_id=arguments["actor_user_id"],
        request_key=arguments["request_key"], expected_intent_sha256=preview["intent_sha256"])
    assert recovered["package"] == result["package"] and recovered["intent"] == result["intent"]
    assert await state(db_session) == before
    with pytest.raises(service.PreparationConflict):
        await service.prepare_distribution(db_session, **arguments,
            expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    assert await state(db_session) == before


async def test_real_preparation_rights_publication_and_live_revoke_pipeline(db_session):
    from services import research_distribution_rights as rights
    context = await preparation_fixture(db_session)
    arguments = operation_arguments(context)
    people = context["shared"]["actors"]
    _, result = await committed(db_session, arguments)
    package = result["package"]
    inspected = await distribution.inspect_distribution(db_session, package_id=package["id"])
    inventory = inspected["inventory"]
    permissions = []
    for dependency in inventory["dependencies"]:
        request = {"actor_user_id": people["reviewer"], "request_key": "synthetic-full-rights:" + uuid4().hex,
            "package_id": package["id"], "dependency_id": dependency["dependency_id"], "decision": "allow",
            "license_code": "permission-on-file", "basis_code": "synthetic_disclosure_intent",
            "reason_code": "synthetic_full_pipeline", "expected_package_sha256": package["record_sha256"],
            "expected_inventory_sha256": package["inventory_sha256"], "expected_dependency_row_sha256": dependency["row_sha256"],
            "expected_head_id": None, "expected_head_sha256": None}
        preview = await rights.prepare_distribution_rights(db_session, **request)
        permission = await rights.prepare_distribution_rights(db_session, **request,
            expected_intent_sha256=preview["intent_sha256"], dry_run=False)
        permissions.append((request, permission))
    review = await distribution.review_distribution(db_session, actor_user_id=people["reviewer"],
        request_key="synthetic-full-review:" + uuid4().hex, package_id=package["id"],
        expected_inventory_sha256=package["inventory_sha256"], disclosure_approved=True,
        reason_code="synthetic_disclosure_only", dry_run=False)
    await distribution.distribution_action(db_session, actor_user_id=people["publisher"],
        request_key="synthetic-full-publish:" + uuid4().hex, package_id=package["id"], review_id=review["id"],
        expected_inventory_sha256=package["inventory_sha256"], kind="publish", reason_code="synthetic_publication", dry_run=False)
    await db_session.commit()
    pins = [{"release_id": context["release"]["id"], "release_sha256": arguments["expected_release_sha256"],
             "bundle_sha256": arguments["expected_public_bundle_sha256"]}]
    before = await state(db_session)
    receipt = await distribution.prepare_rps_distribution_access(pins=pins, purpose="download")
    assert receipt.admitted_release_ids == (context["release"]["id"],)
    assert await distribution.recheck_rps_distribution_access(receipt) is None
    assert await state(db_session) == before
    original, permission = permissions[0]
    revoke = {**original, "request_key": "synthetic-full-revoke:" + uuid4().hex, "decision": "revoke",
              "expected_head_id": permission["permission"]["id"],
              "expected_head_sha256": permission["permission"]["record_sha256"]}
    preview = await rights.prepare_distribution_rights(db_session, **revoke)
    await rights.prepare_distribution_rights(db_session, **revoke,
        expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    await db_session.commit()
    before = await state(db_session)
    denied = await distribution.prepare_rps_distribution_access(pins=pins, purpose="download")
    assert denied.admitted_release_ids == ()
    with pytest.raises(distribution.DistributionAdmissionChanged):
        await distribution.recheck_rps_distribution_access(receipt)
    assert (await distribution.inspect_distribution(db_session, package_id=package["id"]))["inventory"] == inventory
    assert await state(db_session) == before


async def test_signed_zero_descriptor_bytes_survive_postgres_jsonb_and_recovery(db_session):
    from services import research_distribution_preparation as service
    context = await preparation_fixture(db_session)
    release = deepcopy(context["release"])
    original = next(item for item in release["artifacts"] if item["kind"] == "state")
    original["content"]["pressure_gpa"] = -0.0
    release = reseal_public_release(release)
    bundle = build_public_bundle(release, disclosure=disclosure_for(release))
    arguments = {**operation_arguments(context), "release": release, "public_bundle": bundle,
        "expected_release_sha256": release["manifest_sha256"], "expected_public_bundle_sha256": bundle["bundle_sha256"]}
    preview, result = await committed(db_session, arguments)
    inspected = await distribution.inspect_distribution(db_session, package_id=result["package"]["id"])
    binding = next(row for row in inspected["bindings"]["bindings"] if row["artifact_kind"] == "state")
    descriptor = await capture(db_session, "evidence_artifacts", UUID(binding["root"]["evidence_artifact_id"]))
    artifact = next(item for item in release["artifacts"] if item["kind"] == "state")
    raw = canonical_json(artifact).encode()
    assert b'"pressure_gpa":-0.0' in raw
    assert descriptor["metadata"]["rps_artifact_json"].encode() == raw
    assert descriptor["bytes_sha256"] == hashlib.sha256(raw).hexdigest()
    before = await state(db_session)
    outcome = await service.preparation_outcome(db_session, actor_user_id=arguments["actor_user_id"],
        request_key=arguments["request_key"], expected_intent_sha256=preview["intent_sha256"])
    assert outcome["package"] == result["package"]
    assert await state(db_session) == before


async def test_actual_pending_import_extraction_is_not_a_calculation_evidence_root(db_session, monkeypatch):
    from services import research_distribution_preparation as service
    from services import research_freeze
    from services import scientific_pending_import as imports
    from tests.test_research_freeze import add, approved
    from tests.test_scientific_pending_import import seed_import
    context = await preparation_fixture(db_session)
    imported = await seed_import(db_session)
    start = await imports.start_import(db_session, actor_user_id=imported["actors"]["curator"],
        request_key="synthetic-not-a-calculation:" + uuid4().hex, package=imported["package"], dry_run=False)
    await db_session.commit()
    terminal = await imports.finish_import(db_session, actor_user_id=imported["actors"]["curator"],
        attempt_id=start["attempt_id"], prepared=imports.compile_input(imported["package"]), dry_run=False)
    await db_session.commit()
    assert terminal["status"] == "success_pending"
    event = await capture(db_session, "research_events", UUID(terminal["row_ids"]["event"]))
    assert event["event_type"] == "extraction" and event["knowledge_origin"] == "Computed"
    blobs = Base.metadata.tables["scientific_import_blobs"]
    actual_bytes = {row.bytes_sha256: bytes(row.payload) for row in (await db_session.execute(
        sa.select(blobs.c.bytes_sha256, blobs.c.payload).where(blobs.c.package_id == UUID(start["package_id"])))).all()}
    # An explicit technical snapshot membership is an allowed 0054 root; it
    # does not invent a source Paper or turn the extraction into calculation.
    snapshot = await add(db_session, "source_snapshots", dataset_version="synthetic:" + uuid4().hex,
        schema_version="synthetic/1", material_count=1, paper_count=0)
    member = await add(db_session, "snapshot_event_memberships", snapshot_id=snapshot["id"],
        event_id=UUID(terminal["row_ids"]["event"]), event_revision=event["revision"],
        source_occurrence_key="synthetic-retained-import:" + terminal["outcome_id"],
        locator={"synthetic_import_outcome_id": terminal["outcome_id"]},
        source_record_sha256=terminal["request_sha256"], result_manifest_sha256=terminal["report_sha256"])
    source = deepcopy(context["shared"]["source"])
    source["args"]["source_roots"].append({"table": "snapshot_event_memberships", "row_id": str(member["id"])})
    source["args"]["artifact_bytes"].update(actual_bytes)
    _, freeze_arguments = await approved(db_session, source)
    capsule = await research_freeze.freeze_research_release(db_session, **freeze_arguments, dry_run=False)
    row = next(item for item in capsule["manifest"]["rows"]
        if item["table"] == "event_properties" and item["row_id"] == terminal["row_ids"]["property"])
    release = release_document(source_kind="calculation")
    bundle = build_public_bundle(release, disclosure=disclosure_for(release))
    arguments = operation_arguments(context)
    arguments.update(release=release, public_bundle=bundle, expected_release_sha256=release["manifest_sha256"],
        expected_public_bundle_sha256=bundle["bundle_sha256"],
        capsule_artifact_bytes={capsule["manifest_sha256"]: freeze_arguments["artifact_bytes"]})
    for entry in arguments["selections"]["evidence_roots"]:
        entry["root"] = {"kind": "frozen_result", "manifest_sha256": capsule["manifest_sha256"],
                         "table": "event_properties", "row_id": row["row_id"], "row_sha256": row["row_sha256"]}
    arguments["expected_selections_sha256"] = digest(arguments["selections"])
    before = await state(db_session)
    original, observed = contract._frozen_result, []
    def checked_origin(artifact, root, found, artifact_bytes):
        assert artifact["content"]["source_kind"] == "calculation"
        assert root["row_id"] == terminal["row_ids"]["property"]
        actual = found[("research_events", terminal["row_ids"]["event"])]["data"]
        assert actual["event_type"] == "extraction" and actual["knowledge_origin"] == "Computed"
        observed.append(root["row_id"])
        return original(artifact, root, found, artifact_bytes)
    monkeypatch.setattr(contract, "_frozen_result", checked_origin)
    with pytest.raises(contract.ResearchDistributionError):
        await service.prepare_distribution(db_session, **arguments)
    assert observed == [terminal["row_ids"]["property"]]
    assert await state(db_session) == before
