"""Actual disposable SQL audit capture; fixtures never authenticate science."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from services import ml_review_capture as capture_service
from services import research_publication as publication
from services.ml_feature_review_companion import verify_ml_review_companion
from services.ml_review_source_observation import parse
from services.research_access import ResearchAccessDenied, active_grant
from services.research_release_manifest import canonical, digest
from tests.test_ml_physical_feature_sql import (
    freeze_scientific_candidates,
    seed_scientific_candidates,
)
from tests.test_research_freeze import add, state
from tests.test_research_freeze import db_session as db_session
from tests.test_research_publication import actors
from tests.test_scientific_adjudication_schema import capture, decision_for, item_for, request_for


async def stable(db):
    await db.commit()
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))


async def reviewed_fixture(db, *, decision="reject", properties=None):
    people = await actors(db)
    grant = await publication.grant_role(db, actor_user_id=people["admin"], user_id=people["admin"],
        role="curator", reason_code="synthetic_private_full_audit", dry_run=False)
    fixture = await seed_scientific_candidates(db, properties=properties or ["phonon_min_frequency", "band_gap"])
    inputs = await freeze_scientific_candidates(db, fixture)
    first = next(iter(fixture["physics"]))
    prop = fixture["physics"][first]["phonon_min_frequency"]["property"] if "phonon_min_frequency" in fixture["physics"][first] else None
    await stable(db)
    review = None
    if decision is not None:
        subject = dict(await add(db, "scientific_result_subjects", **await capture(db, prop["id"])))
        item = await item_for(db, subject, profile="recorded-sampled-frequency-fidelity/1.0.0", decision=decision)
        reviewer = {"reviewer": people["reviewer"], "grant": await active_grant(db, people["reviewer"], role="reviewer")}
        request = await request_for(db, reviewer, [item])
        result = await decision_for(db, request, subject, item)
        await db.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
        review = {"subject": subject, "item": item, "request": request, "decision": result}
        await stable(db)
    args = {"actor_user_id": people["admin"], "expected_actor_grant_id": UUID(grant["id"]),
        "export_scope": capture_service.EXPORT_SCOPE, "base_manifest": inputs["release"]["manifest"],
        "expected_base_manifest_sha256": inputs["release"]["manifest_sha256"],
        "source_companion": inputs["companion"], "expected_source_companion_sha256": digest(inputs["companion"]),
        "artifact_bytes": inputs["artifact_bytes"]}
    return {"fixture": fixture, "inputs": inputs, "people": people, "args": args,
            "review": review, "first": first, "property_id": str(prop["id"]) if prop else None}


def verify(value, seeded):
    args = seeded["args"]
    return verify_ml_review_companion(value, **{key: args[key] for key in (
        "base_manifest", "expected_base_manifest_sha256", "source_companion", "expected_source_companion_sha256")},
        expected_review_companion_sha256=digest(value))


async def test_actual_capture_preserves_full_sql_and_all_old_frozen_bytes(db_session):
    seeded = await reviewed_fixture(db_session)
    old = canonical({key: seeded["args"][key] for key in ("base_manifest", "source_companion")})
    before = await state(db_session)
    value = await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    receipt = verify(value, seeded)
    assert receipt["property_holds"][seeded["property_id"]]
    assert all(flag is False for flag in receipt["authority"].values())
    assert value == await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    assert before == await state(db_session)
    assert old == canonical({key: seeded["args"][key] for key in ("base_manifest", "source_companion")})
    users = [parse(row["row_text"]) for row in value["observation"]["audit_rows"] if row["table"] == "users"]
    assert users and all(set(row) == {"id", "is_active", "email_verified", "is_admin"} for row in users)
    reviewed = [row for row in value["observation"]["properties"] if any(row["heads"].values())]
    assert len(reviewed) == 1 and reviewed[0]["property_id"] == seeded["property_id"]
    assert all(row["current_subject_text"] is None and row["current_subject_sha256"] is None
               for row in value["observation"]["properties"] if not any(row["heads"].values()))


async def test_unreviewed_capture_does_not_fabricate_scientific_or_fidelity_acceptance(db_session):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    value = await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    receipt = verify(value, seeded)
    assert all(not codes for codes in receipt["property_holds"].values())
    assert all(not codes for codes in receipt["input_source_holds"].values())
    assert not any(row["table"].startswith("scientific_") for row in value["observation"]["audit_rows"])


@pytest.mark.parametrize("role", ["reviewer", "curator", "publisher", "member", "admin_wrong_grant"])
async def test_full_private_audit_export_requires_admin_and_exact_curator(db_session, role):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    args = dict(seeded["args"])
    if role == "admin_wrong_grant":
        args["expected_actor_grant_id"] = seeded["people"]["grants"]["curator"]
    else:
        args["actor_user_id"] = seeded["people"][role]
        args["expected_actor_grant_id"] = seeded["people"]["grants"].get(role, uuid4())
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await capture_service.capture_ml_review_companion(db_session, **args)
    assert before == await state(db_session)


@pytest.mark.parametrize("scope", [None, "curator", "ml_review_full_audit/2.0.0", True])
async def test_export_scope_is_explicit_and_cannot_be_coerced(scope):
    with pytest.raises(capture_service.MlReviewCaptureError, match="scope"):
        await capture_service.capture_ml_review_companion(None, actor_user_id=uuid4(), expected_actor_grant_id=uuid4(),
            export_scope=scope, base_manifest={}, expected_base_manifest_sha256="0" * 64,
            source_companion={}, expected_source_companion_sha256="0" * 64, artifact_bytes={})


@pytest.mark.parametrize("source_kind", ["papers", "works"])
async def test_independent_0064_source_hold_is_captured_not_dropped_or_old_companion_mutated(db_session, source_kind):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    fixture = seeded["fixture"]
    source = fixture["feature_bindings"][(seeded["first"], "band_gap")]["source"]
    key = source["revision"]["paper_id" if source_kind == "papers" else "work_id"]
    table = Base.metadata.tables[source_kind]
    await db_session.execute(table.update().where(table.c.id == (key if source_kind == "papers" else UUID(key))).values(
        **{"status" if source_kind == "papers" else "publication_status": "retracted"}))
    await stable(db_session)
    old = canonical(seeded["args"]["source_companion"])
    value = await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    receipt = verify(value, seeded)
    input_id = str(fixture["physics"][seeded["first"]]["band_gap"]["input"]["id"])
    assert "current_source_held" in receipt["input_source_holds"][input_id]
    assert any(row["table"] == "source_lifecycle_events" for row in value["observation"]["source_observation"]["rows"])
    assert old == canonical(seeded["args"]["source_companion"])


async def test_active_source_identity_change_holds_input_without_rewriting_historical_companion(db_session):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    source = seeded["fixture"]["feature_bindings"][(seeded["first"], "band_gap")]["source"]
    original = canonical(seeded["args"]["source_companion"])
    await db_session.execute(sa.text("UPDATE papers SET doi='10.5555/synthetic-changed-identity' WHERE id=:id"),
        {"id": source["revision"]["paper_id"]})
    await stable(db_session)
    value = await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    report = verify(value, seeded)
    input_id = str(seeded["fixture"]["physics"][seeded["first"]]["band_gap"]["input"]["id"])
    assert "feature_source_identity_changed" in report["input_source_holds"][input_id]
    assert "current_source_held" not in report["input_source_holds"][input_id]
    assert original == canonical(seeded["args"]["source_companion"])


async def test_new_capture_sibling_is_observed_instead_of_reusing_old_binding_inventory(db_session):
    from services.source_registry import SOURCE_REGISTRY_VERSION, import_source_provenance_bundle
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    source = seeded["fixture"]["feature_bindings"][(seeded["first"], "band_gap")]["source"]
    identifier = str(uuid4())
    await import_source_provenance_bundle(db_session, {"version": SOURCE_REGISTRY_VERSION,
        "source_revisions": [], "claim_source_occurrences": [], "source_captures": [{
            "id": identifier, "source_revision_id": source["revision"]["id"], "capture_key": "synthetic-additional-capture",
            "captured_at": "2026-01-02T00:00:00Z", "bytes_sha256": source["sha"], "representation": "arxiv_source"}]}, dry_run=False)
    await stable(db_session)
    value = await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    assert any(row["table"] == "source_captures" and row["row_id"] == identifier
               for row in value["observation"]["source_observation"]["rows"])
    input_id = str(seeded["fixture"]["physics"][seeded["first"]]["band_gap"]["input"]["id"])
    assert "feature_source_binding_changed" in verify(value, seeded)["input_source_holds"][input_id]


async def test_bad_independent_pin_refuses_capture_without_partial_result(db_session):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    args = dict(seeded["args"], expected_source_companion_sha256="0" * 64)
    before = await state(db_session)
    with pytest.raises(ValueError):
        await capture_service.capture_ml_review_companion(db_session, **args)
    assert before == await state(db_session)


@pytest.mark.parametrize("change", ["reviewer_revoked", "source_held", "subject_changed"])
async def test_old_verified_artifact_is_historical_and_fresh_recheck_refuses_change(db_session, change):
    seeded = await reviewed_fixture(db_session, decision="accept", properties=["phonon_min_frequency"])
    old = await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    receipt = verify(old, seeded)
    recheck = await capture_service.recheck_ml_review_companion(db_session, **seeded["args"],
        review_companion=old, expected_review_companion_sha256=digest(old))
    assert recheck["observation_sha256"] == old["observation_sha256"]
    assert all(flag is False for flag in recheck["authority"].values())
    await stable(db_session)
    if change == "reviewer_revoked":
        await publication.revoke_role(db_session, actor_user_id=seeded["people"]["admin"],
            grant_id=seeded["people"]["grants"]["reviewer"], reason_code="synthetic_changed_reviewer", dry_run=False)
    elif change == "source_held":
        source = seeded["fixture"]["feature_bindings"][(seeded["first"], "phonon_min_frequency")]["source"]
        await db_session.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"),
            {"id": source["revision"]["paper_id"]})
    else:
        material = seeded["fixture"]["candidates"][seeded["first"]]["material"]["id"]
        await db_session.execute(sa.text("UPDATE materials SET formula='MgB3' WHERE id=:id"), {"id": material})
    await stable(db_session)
    assert receipt == verify(old, seeded)
    with pytest.raises(capture_service.MlReviewCaptureError, match="ml_review_observation_changed"):
        await capture_service.recheck_ml_review_companion(db_session, **seeded["args"],
            review_companion=old, expected_review_companion_sha256=digest(old))
    new = await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    assert new["observation_sha256"] != old["observation_sha256"]
    if change != "source_held":
        assert verify(new, seeded)["property_holds"][seeded["property_id"]]


async def test_actual_twenty_one_reviewed_properties_are_not_interactive_twenty_truncated(db_session):
    people = await actors(db_session)
    grant = await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=people["admin"],
        role="curator", reason_code="synthetic_batch_audit", dry_run=False)
    fixture = await seed_scientific_candidates(db_session, properties=["phonon_min_frequency"])
    first = next(iter(fixture["candidates"]))
    sample = fixture["physics"][first]["phonon_min_frequency"]
    properties = [value["phonon_min_frequency"]["property"]["id"] for value in fixture["physics"].values()]
    for index in range(16):
        # One property/component per event is an existing immutable SQL rule.
        # These audit-only curation events do not claim additional DFPT runs.
        event = await add(db_session, "research_events", material_id=sample["event"]["material_id"],
            state_id=sample["event"]["state_id"], structure_id=sample["event"]["structure_id"],
            event_type="curation", knowledge_origin="Inferred", record_sha256=digest({"synthetic_extra_event": index}))
        prop = await add(db_session, "event_properties", event_id=event["id"],
            property_key="phonon_min_frequency", relation="exact", value=float(index), unit="THz",
            raw={"synthetic": True, "row": index}, record_sha256=digest({"synthetic_extra": index}))
        await add(db_session, "ml_example_inputs", example_id=fixture["candidates"][first]["example"]["id"],
            input_kind="property", input_event_id=event["id"], input_property_id=prop["id"],
            feature_key="synthetic-extra-" + str(index), matching_policy_version="synthetic-audit-only/1",
            record_sha256=digest({"synthetic_extra_input": index}))
        properties.append(prop["id"])
    inputs = await freeze_scientific_candidates(db_session, fixture)
    await stable(db_session)
    subjects = [dict(await add(db_session, "scientific_result_subjects", **await capture(db_session, identifier)))
                for identifier in properties]
    reviewer = {"reviewer": people["reviewer"], "grant": await active_grant(db_session, people["reviewer"], role="reviewer")}
    request_ids = []
    for start in (0, 20):
        selected = subjects[start:start + 20]
        items = [await item_for(db_session, subject, profile="recorded-sampled-frequency-fidelity/1.0.0", decision="reject")
                 for subject in selected]
        request = await request_for(db_session, reviewer, items)
        request_ids.append(str(request["id"]))
        for index, (subject, item) in enumerate(zip(selected, items, strict=True)):
            await decision_for(db_session, request, subject, item, index=index)
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    await stable(db_session)
    args = {"actor_user_id": people["admin"], "expected_actor_grant_id": UUID(grant["id"]),
        "export_scope": capture_service.EXPORT_SCOPE, "base_manifest": inputs["release"]["manifest"],
        "expected_base_manifest_sha256": inputs["release"]["manifest_sha256"], "source_companion": inputs["companion"],
        "expected_source_companion_sha256": digest(inputs["companion"]), "artifact_bytes": inputs["artifact_bytes"]}
    value = await capture_service.capture_ml_review_companion(db_session, **args)
    receipt = verify(value, {"args": args})
    reviewed = [row for row in value["observation"]["properties"] if any(row["heads"].values())]
    assert len(reviewed) == 21
    assert all(receipt["property_holds"][str(identifier)] for identifier in properties)
    assert receipt["property_holds"][str(properties[20])]
    retained = {row["row_id"] for row in value["observation"]["audit_rows"] if row["table"] == "scientific_adjudication_requests"}
    assert retained == set(request_ids)


async def test_capture_stable_snapshot_and_fresh_transaction_observe_concurrent_source_change(db_session):
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.db import get_engine
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    old = await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    source = seeded["fixture"]["feature_bindings"][(seeded["first"], "band_gap")]["source"]
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine) as writer:
            await writer.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"),
                {"id": source["revision"]["paper_id"]})
            await writer.commit()
        # Repeatable-read/SERIALIZABLE observations are not silently mixed.
        assert old == await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
        await stable(db_session)
        with pytest.raises(capture_service.MlReviewCaptureError, match="ml_review_observation_changed"):
            await capture_service.recheck_ml_review_companion(db_session, **seeded["args"],
                review_companion=old, expected_review_companion_sha256=digest(old))
    finally:
        await engine.dispose()


@pytest.mark.parametrize("limit", ["bytes", "reviewed", "deadline"])
async def test_capture_resource_limits_never_return_partial_success(db_session, monkeypatch, limit):
    from services import ml_review_source_observation as source
    seeded = await reviewed_fixture(db_session)
    before = await state(db_session)
    if limit == "bytes":
        monkeypatch.setattr(source, "MAX_BYTES", 1024)
    elif limit == "reviewed":
        monkeypatch.setattr(capture_service, "MAX_REVIEWED", 0)
    else:
        actual = capture_service.time.monotonic
        calls = 0
        def clock():
            nonlocal calls
            calls += 1
            return actual() + (100 if calls > 1 else 0)
        monkeypatch.setattr(capture_service, "time", type("Clock", (), {"monotonic": staticmethod(clock)}))
    with pytest.raises(capture_service.MlReviewCaptureError):
        await capture_service.capture_ml_review_companion(db_session, **seeded["args"])
    assert before == await state(db_session)
