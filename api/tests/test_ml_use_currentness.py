"""Real SQL full-audit comparisons; worker receipts here are labeled test doubles.

The actual eight-input compiler/HTTP path is tested separately in the request
pipeline module. These smaller cases target currentness and audit inventories.
"""
from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, User, get_engine
from models.ml_use_request import INPUTS, prepare_request
from services import ml_label_capture, ml_review_capture, research_publication
from services import ml_use_currentness as service
from services.ml_audited_dataset import canonical, digest
from services.ml_dataset_builder import AUTHORITY
from services.ml_review_source_observation import parse
from services.ml_use_preflight import MlUsePreflightConflict
from services.ml_use_reconstruction import VERSION, decode_envelope
from services.research_access import ResearchAccessDenied, active_grant
from services.source_registry import SOURCE_REGISTRY_VERSION, import_source_provenance_bundle
from tests.test_ml_label_capture import db_session as db_session
from tests.test_ml_label_capture import read_snapshot, write_snapshot
from tests.test_ml_review_capture import reviewed_fixture
from tests.test_ml_use_governance import arguments, decide
from tests.test_research_freeze import state
from tests.test_scientific_adjudication_schema import decision_for, item_for, request_for


async def setup(db):
    seeded = await reviewed_fixture(db, decision="accept", properties=["phonon_min_frequency"])
    db.info.setdefault("ml_label_fixture_material_ids", set()).update(
        item["material"]["id"] for item in seeded["fixture"]["candidates"].values())
    people = seeded["people"]
    operator = people["curator"]
    await db.execute(sa.update(User).where(User.id == operator).values(is_admin=True))
    role = await decide(db, arguments(people, user_id=str(operator)))
    await read_snapshot(db)
    review = await ml_review_capture.capture_ml_review_companion(db, **seeded["args"])
    label_args = {**seeded["args"], "export_scope": ml_label_capture.EXPORT_SCOPE,
                  "review_companion": review, "expected_review_companion_sha256": digest(review)}
    label = await ml_label_capture.capture_ml_label_companion(db, **label_args)
    values = {name: {"unit_test_only_no_real_worker": name} for name in INPUTS}
    values.update(manifest=seeded["inputs"]["release"]["manifest"], companion=seeded["inputs"]["companion"],
                  review_companion=review, label_companion=label)
    pins = {name + "_sha256": digest(value) for name, value in values.items()}
    request = prepare_request(manifest=values["manifest"], companion=values["companion"], input_pins=pins)
    envelope = {"version": VERSION, "request": request, "expected_request_sha256": digest(request),
        "expected_requester_grant_id": role["decision"]["id"], "expected_curator_grant_id": str(people["grants"]["curator"]),
        "inputs_base64": {name: base64.b64encode(canonical(value)).decode() for name, value in values.items()},
        "artifacts_base64": {pin: base64.b64encode(raw).decode() for pin, raw in seeded["inputs"]["artifact_bytes"].items()}}
    raw = canonical(envelope)
    proof = {"request_sha256": digest(request), "envelope_sha256": hashlib.sha256(raw).hexdigest(),
             "input_pins": pins, "all_eight_input_bytes_verified": True, "dataset_and_preparation_rebuilt": True,
             "unit_test_double_not_compiler_evidence": True}
    return seeded, {"actor_user_id": operator, "raw": raw, "reconstruction": proof}


async def test_complete_sql_audit_inventory_includes_review_request_subject_roles_and_members(db_session):
    seeded, args = await setup(db_session)
    before = await state(db_session)
    original = deepcopy(args)
    result = await service.inspect_current_inputs(db_session, **args)
    assert await state(db_session) == before and args == original
    assert result["companion_observations_rechecked_online"] and result["online_private_input_reconstruction_verified"]
    assert result["admission"]["actor_user_id"] != result["companion_capture_identity_claim"]["actor_user_id"]
    assert result["dependency_inventory_sha256"] == digest(result["dependency_inventory"])
    inventory = result["dependency_inventory"]
    keys = {(row["table"], row["row_id"]) for row in inventory["rows"]}
    assert ("scientific_result_decisions", str(seeded["review"]["decision"]["id"])) in keys
    assert ("scientific_adjudication_requests", str(seeded["review"]["request"]["id"])) in keys
    assert ("scientific_result_subjects", str(seeded["review"]["subject"]["id"])) in keys
    assert ("users", str(seeded["people"]["reviewer"])) in keys
    assert ("research_role_grants", str(seeded["people"]["grants"]["reviewer"])) in keys
    subject = json.loads(seeded["review"]["subject"]["basis_json"])
    assert {(row["table"], row["row_id"]) for row in subject["rows"]} <= keys
    members = [pin for row in inventory["rows"] for pin in row["representations"]
               if pin["encoding"] == "scientific-subject-membership/1.0.0"]
    assert members and all(pin["container_sha256"] for pin in members)
    assert inventory["row_count"] == len(keys) and inventory["independent_support_count"] is None
    assert any(pin["scope"] == "historical_subject" for pin in members)
    assert any(pin["scope"] == "current_observation" for pin in members)
    assert all(result[key] is False for key in (*AUTHORITY, "historical_capture_session_authenticated",
        "source_permission_granted", "run_authorization_granted", "request_persisted", "database_mutated"))
    for text in ("Synthetic review declaration", "basis_json", "source text", "password_hash", "reviewer@"):
        assert text not in canonical(result).decode()


@pytest.mark.parametrize("change", ["new_decision", "reviewer_revoked", "reviewer_inactive", "capturer_revoked",
                                     "capturer_inactive", "material_hold", "paper_retraction", "source_occurrence"])
async def test_current_sql_changes_refuse_old_companion_even_when_all_old_pins_still_verify(db_session, change):
    seeded, args = await setup(db_session)
    await service.inspect_current_inputs(db_session, **args)
    await write_snapshot(db_session)
    people = seeded["people"]
    if change == "new_decision":
        old = seeded["review"]
        item = await item_for(db_session, old["subject"], profile="recorded-sampled-frequency-fidelity/1.0.0",
                              decision="request_clarification", predecessor=old["decision"]["id"])
        reviewer = {"reviewer": people["reviewer"], "grant": await active_grant(db_session, people["reviewer"], role="reviewer")}
        request = await request_for(db_session, reviewer, [item])
        await decision_for(db_session, request, old["subject"], item)
        await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    elif change.endswith("revoked"):
        grant = people["grants"]["reviewer"] if change == "reviewer_revoked" else seeded["args"]["expected_actor_grant_id"]
        await research_publication.revoke_role(db_session, actor_user_id=people["admin"], grant_id=grant,
                                               reason_code="synthetic_currentness_revoke", dry_run=False)
    elif change.endswith("inactive"):
        user = people["reviewer"] if change == "reviewer_inactive" else people["admin"]
        await db_session.execute(sa.update(User).where(User.id == user).values(is_active=False))
    else:
        first = seeded["fixture"]["candidates"][seeded["first"]]
        if change == "material_hold":
            await db_session.execute(Base.metadata.tables["materials"].update().where(
                Base.metadata.tables["materials"].c.id == first["material"]["id"]).values(needs_review=True))
        elif change == "paper_retraction":
            await db_session.execute(Base.metadata.tables["papers"].update().where(
                Base.metadata.tables["papers"].c.id == first["paper"]["id"]).values(status="retracted"))
        else:
            old = first["source_bundle"]["claim_source_occurrences"][0]
            await import_source_provenance_bundle(db_session, {"version": SOURCE_REGISTRY_VERSION,
                "source_revisions": [], "source_captures": [], "claim_source_occurrences": [{
                    "id": str(uuid4()), "claim_id": str(first["claim"]["id"]), "work_id": str(first["work"]["id"]),
                    "source_revision_id": old["source_revision_id"], "capture_id": old["capture_id"],
                    "occurrence_key": "synthetic-new-currentness", "locator": {"page": 2}, "binding_status": "pending"}]}, dry_run=False)
    await read_snapshot(db_session)
    before = await state(db_session)
    with pytest.raises((MlUsePreflightConflict, ResearchAccessDenied)):
        await service.inspect_current_inputs(db_session, **args)
    assert await state(db_session) == before


@pytest.mark.parametrize("field", ["request_sha256", "envelope_sha256", "input_pins", "all_eight_input_bytes_verified",
                                    "dataset_and_preparation_rebuilt"])
async def test_worker_output_cannot_be_retargeted_to_another_captured_input(db_session, field):
    _, args = await setup(db_session)
    args["reconstruction"][field] = False
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.inspect_current_inputs(db_session, **args)
    assert await state(db_session) == before


async def test_service_refuses_mutable_transaction_and_inventory_budget_overflow(db_session, monkeypatch):
    _, args = await setup(db_session)
    await write_snapshot(db_session)
    with pytest.raises(ValueError, match="readonly_snapshot"):
        await service.inspect_current_inputs(db_session, **args)
    await read_snapshot(db_session)
    monkeypatch.setattr(service, "MAX_ROWS", 1)
    with pytest.raises(ValueError, match="currentness_invalid"):
        await service.inspect_current_inputs(db_session, **args)


async def test_inventory_qualifies_distinct_historical_current_and_membership_pins(db_session):
    _, args = await setup(db_session)
    result = await service.inspect_current_inputs(db_session, **args)
    _, values, artifacts = decode_envelope(args["raw"])
    first = service.dependency_inventory(values, artifacts, result)
    assert first == service.dependency_inventory(deepcopy(values), dict(reversed(list(artifacts.items()))), result)
    assert first["source_permission_granted"] is first["external_dependency_completeness_proven"] is False
    users = [row for row in values["review_companion"]["observation"]["audit_rows"] if row["table"] == "users"]
    assert users and all(set(parse(row["row_text"])) == {"id", "is_admin", "is_active", "email_verified"} for row in users)


async def test_currentness_receipt_is_one_snapshot_not_a_durable_lease(db_session):
    seeded, args = await setup(db_session)
    first = await service.inspect_current_inputs(db_session, **args)
    candidate = seeded["fixture"]["candidates"][seeded["first"]]
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as writer:
        await writer.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
        await writer.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
        await writer.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"), {"id": candidate["paper"]["id"]})
        await writer.commit()
    same = await service.inspect_current_inputs(db_session, **args)
    assert same == first  # already established snapshot correctly remains historical
    await db_session.rollback()
    await read_snapshot(db_session)
    with pytest.raises(MlUsePreflightConflict):
        await service.inspect_current_inputs(db_session, **args)


async def test_unavailable_capture_does_not_report_an_empty_current_inventory(db_session, monkeypatch):
    _, args = await setup(db_session)
    before = await state(db_session)

    async def unavailable(*_args, **_kwargs):
        raise ml_label_capture.MlLabelCaptureUnavailable("PRIVATE_SQL")
    monkeypatch.setattr(service, "recheck_ml_label_companion", unavailable)
    with pytest.raises(TimeoutError, match="^ml_use_currentness_unavailable$"):
        await service.inspect_current_inputs(db_session, **args)
    assert await state(db_session) == before


def test_upload_openapi_is_closed_and_does_not_accept_a_client_worker_receipt():
    from routers.ml_use_preflight import ReconstructionEnvelope
    schema = ReconstructionEnvelope.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"version", "request", "expected_request_sha256", "expected_requester_grant_id",
                                       "expected_curator_grant_id", "inputs_base64", "artifacts_base64"}
    assert schema["properties"]["version"]["const"] == VERSION
    assert schema["properties"]["inputs_base64"]["minProperties"] == schema["properties"]["inputs_base64"]["maxProperties"] == 8
    assert set(schema["properties"]["inputs_base64"]["properties"]) == set(INPUTS)
    assert schema["properties"]["inputs_base64"]["additionalProperties"] is False


async def test_actual_native_subject_inventory_includes_import_package_outcome_and_files(db_session):
    from tests.test_scientific_adjudication_schema import capture
    from tests.test_scientific_adjudication_schema import fixture as native_fixture
    seeded = await native_fixture(db_session)
    captured = await capture(db_session, seeded["property_id"])
    subject = json.loads(captured["basis_json"])
    # Isolated projection test of a genuine SQL native subject, not a fabricated
    # complete ML upload or an alternate bypass of the actual HTTP worker.
    values = {"manifest": {"rows": []}, "companion": {"source_rows": [], "bindings": [], "artifacts_base64": {}},
        "review_companion": {"observation": {"audit_rows": [], "source_observation": {"rows": [], "lifecycle": []},
            "properties": [{"property_id": str(seeded["property_id"]), "current_subject_text": captured["basis_json"],
                            "current_subject_sha256": captured["subject_sha256"]}]}},
        "label_companion": {"observation": {"rows": [], "lifecycle": []}}}
    inventory = service.dependency_inventory(values, {}, {"requirements": [], "input_pins": {}})
    index = {(row["table"], row["row_id"]): row for row in inventory["rows"]}
    native = subject["native_import"]
    expected = {("scientific_import_outcomes", native["outcome_id"]), ("scientific_import_packages", native["package_id"])}
    expected.update(("scientific_import_files", item["file_id"]) for item in native["source_files"])
    assert expected <= index.keys()
    for key in expected:
        pin = index[key]["representations"][0]
        assert pin["container_sha256"] == captured["subject_sha256"]
        assert pin["encoding"] == "scientific-subject-membership/1.0.0"
        assert pin["sha256"] == digest({"subject_sha256": captured["subject_sha256"], "table": key[0], "row_id": key[1]})
    byte_refs = {item["sha256"]: item for item in inventory["artifact_digests"]}
    assert {item["sha256"] for item in native["source_files"]} <= byte_refs.keys()
    assert all(item["uploaded_size_bytes"] is None for item in byte_refs.values())
