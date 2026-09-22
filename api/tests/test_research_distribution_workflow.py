"""Actual disposable SQL service boundaries; all approvals are synthetic."""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from services import research_distribution as service
from services.research_distribution_contract import ResearchDistributionError
from tests.rps_distribution_fixtures import (
    distribution_inputs,
    publish_distribution,
    release_document,
)
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_freeze import state

db_session = _serializable_db_session


async def test_registration_preview_and_idempotence_have_real_transaction_semantics(db_session):
    context = await distribution_inputs(db_session, release_document())
    args = {**context["arguments"], "actor_user_id": context["shared"]["actors"]["curator"],
            "request_key": "synthetic:register:" + uuid4().hex}
    before = await state(db_session)
    preview = await service.register_distribution(db_session, **args)
    assert preview["dry_run"] is True and preview["committed"] is False
    assert preview["inventory"]["scientific_acceptance"] is False
    assert await state(db_session) == before
    first = await service.register_distribution(db_session, **args, dry_run=False)
    stable = await state(db_session)
    second = await service.register_distribution(db_session, **args, dry_run=False)
    assert {**first, "replayed": True} == second
    assert await state(db_session) == stable
    assert (await service.inspect_distribution(db_session, package_id=first["package_id"]))["inventory"] == first["inventory"]
    inspected = await state(db_session)
    assert len(inspected["research_distribution_packages"]) == len(before["research_distribution_packages"]) + 1


async def test_bad_actual_source_bytes_rollback_every_write(db_session):
    context = await distribution_inputs(db_session, release_document())
    args = {**context["arguments"], "actor_user_id": context["shared"]["actors"]["curator"],
            "request_key": "synthetic:bad-bytes:" + uuid4().hex, "dry_run": False}
    key = next(iter(args["artifact_bytes"]))
    args["artifact_bytes"] = {**args["artifact_bytes"], key: b"wrong bytes"}
    before = await state(db_session)
    with pytest.raises(ResearchDistributionError):
        await service.register_distribution(db_session, **args)
    assert await state(db_session) == before


async def test_published_package_keeps_all_authority_scopes_separate(db_session):
    context = await publish_distribution(db_session, release_document())
    package = context["package"]
    original = deepcopy(context["registration"]["inventory"])
    value = await service.admitted_distribution(db_session, package["id"])
    assert value["bundle_sha256"] == package["public_bundle_sha256"]
    assert original["scientific_acceptance"] is False
    assert original["ml_training_approved"] is False
    assert original["source_rights_verified"] is False
    assert original["database_observation_authenticated"] is False
    assert (await service.inspect_distribution(db_session, package_id=package["id"]))["inventory"] == original


@pytest.mark.parametrize("zone", ["Asia/Singapore", "America/New_York"])
async def test_direct_service_read_normalizes_timezone_without_changing_rows(db_session, zone):
    context = await publish_distribution(db_session, release_document())
    before = await state(db_session)
    await db_session.execute(sa.text("SELECT set_config('TimeZone', :zone, true)"), {"zone": zone})
    value = await service.admitted_distribution(db_session, context["package"]["id"])
    assert value["bundle_sha256"] == context["bundle"]["bundle_sha256"]
    assert await state(db_session) == before


@pytest.mark.parametrize("operation", ["inspect_distribution", "admitted_distribution"])
async def test_direct_reads_reject_mixed_snapshot_session(operation):
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.db import get_engine

    async with AsyncSession(get_engine().execution_options(isolation_level="READ COMMITTED")) as db:
        with pytest.raises(ResearchDistributionError, match="stable_read_session_required"):
            await getattr(service, operation)(db, package_id=uuid4())


async def test_permission_action_replay_is_same_record_not_a_new_grant(db_session):
    context = await publish_distribution(db_session, release_document())
    permission = context["permissions"][0]
    before = await state(db_session)
    result = await service.decide_distribution_permission(db_session,
        **permission["arguments"], request_key=context["request_prefix"] + ":permission:0", dry_run=False)
    assert result == {**permission["receipt"], "replayed": True}
    assert await state(db_session) == before
    with pytest.raises(ResearchDistributionError, match="request_key_conflict"):
        await service.decide_distribution_permission(db_session,
            **{**permission["arguments"], "reason_code": "different_intent"},
            request_key=context["request_prefix"] + ":permission:0", dry_run=False)


@pytest.mark.parametrize("role", ["curator", "reviewer"])
async def test_duplicate_active_grant_cannot_change_exact_replay_identity(db_session, monkeypatch, role):
    from services import research_publication as publication

    context = await publish_distribution(db_session, release_document())
    people = context["shared"]["actors"]
    # A lower replacement ID cannot change which grant is selected: the old
    # frozen 0055 SQL guard already forbids duplicate active account/role grants.
    lower = UUID(int=people["grants"][role].int // 2)
    before = await state(db_session)
    with monkeypatch.context() as patch:
        patch.setattr(publication, "uuid4", lambda: lower)
        with pytest.raises(IntegrityError, match="research_role_active_grant_exists"):
            await publication.grant_role(db_session, actor_user_id=people["admin"], user_id=people[role],
                role=role, reason_code="synthetic_additional_role", dry_run=False)
    assert await state(db_session) == before


@pytest.mark.parametrize("failure", ["bytes", "hash", "different_dependency"])
async def test_rights_document_cannot_be_reused_for_other_exact_intent(db_session, failure):
    context = await publish_distribution(db_session, release_document(), publish=False)
    permission = context["permissions"][0]
    args = {**permission["arguments"], "request_key": "synthetic:rights-reuse:" + uuid4().hex,
            "supersedes_id": permission["receipt"]["id"], "dry_run": False}
    if failure == "bytes":
        args["rights_bytes"] = b"some other review"
    elif failure == "hash":
        args["expected_rights_row_sha256"] = "0" * 64
    else:
        args["dependency_id"] = context["permissions"][1]["dependency"]["dependency_id"]
    before = await state(db_session)
    with pytest.raises(ResearchDistributionError):
        await service.decide_distribution_permission(db_session, **args)
    assert await state(db_session) == before


async def test_revoke_and_withdraw_are_possible_after_prior_rights_and_actor_drift(db_session):
    context = await publish_distribution(db_session, release_document())
    people, permission = context["shared"]["actors"], context["permissions"][0]
    await db_session.execute(sa.text("UPDATE evidence_artifacts SET metadata='{}'::jsonb WHERE id=:id"),
                             {"id": permission["arguments"]["rights_artifact_id"]})
    with pytest.raises(ResearchDistributionError):
        await service.admitted_distribution(db_session, context["package"]["id"])
    result = await service.decide_distribution_permission(db_session, actor_user_id=people["reviewer"],
        request_key="synthetic:revoke:" + uuid4().hex, package_id=context["package"]["id"],
        dependency_id=permission["dependency"]["dependency_id"], decision="revoke", license_code="permission-on-file",
        basis_code="rights_reconsidered", reason_code="synthetic_revoke", supersedes_id=permission["receipt"]["id"], dry_run=False)
    assert result["dry_run"] is False
    await db_session.execute(sa.text("UPDATE users SET is_active=false WHERE id=:id"), {"id": people["reviewer"]})
    result = await service.distribution_action(db_session, actor_user_id=people["publisher"],
        request_key="synthetic:withdraw:" + uuid4().hex, package_id=context["package"]["id"],
        expected_inventory_sha256=context["package"]["inventory_sha256"], review_id=context["review"]["id"],
        kind="withdraw", reason_code="synthetic_withdraw", dry_run=False)
    assert result["committed"] is False


async def test_negative_review_remains_possible_after_source_hold(db_session):
    context = await publish_distribution(db_session, release_document())
    await db_session.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"),
                             {"id": context["shared"]["source"]["paper"]})
    result = await service.review_distribution(db_session, actor_user_id=context["shared"]["actors"]["reviewer"],
        request_key="synthetic:negative:" + uuid4().hex, package_id=context["package"]["id"],
        expected_inventory_sha256=context["package"]["inventory_sha256"], disclosure_approved=False,
        reason_code="synthetic_source_hold", dry_run=False)
    assert result["scientific_acceptance"] is False


async def test_renewed_permission_needs_new_exact_review(db_session):
    context = await publish_distribution(db_session, release_document(), publish=False)
    people, package = context["shared"]["actors"], context["package"]
    review = await service.review_distribution(db_session, actor_user_id=people["reviewer"],
        request_key="synthetic:old-review:" + uuid4().hex, package_id=package["id"],
        expected_inventory_sha256=package["inventory_sha256"], disclosure_approved=True,
        reason_code="synthetic_review", dry_run=False)
    permission = context["permissions"][0]
    await service.decide_distribution_permission(db_session, **permission["arguments"],
        request_key="synthetic:renew:" + uuid4().hex, supersedes_id=permission["receipt"]["id"], dry_run=False)
    with pytest.raises(ResearchDistributionError, match="review_permissions_changed"):
        await service.distribution_action(db_session, actor_user_id=people["publisher"],
            request_key="synthetic:stale-review:" + uuid4().hex, package_id=package["id"],
            expected_inventory_sha256=package["inventory_sha256"], review_id=review["id"], kind="publish",
            reason_code="synthetic_publish", dry_run=False)


@pytest.mark.parametrize("pins", [[{"release_id": "x", "release_sha256": "0" * 64, "bundle_sha256": None}],
                                  [{"release_id": "x", "release_sha256": "0" * 64, "bundle_sha256": "1" * 64}] * 2])
async def test_invalid_public_pins_never_open_a_registry_snapshot(monkeypatch, pins):
    def fail():
        raise AssertionError("no database access is allowed for malformed pins")
    monkeypatch.setattr(service, "get_engine", fail)
    with pytest.raises(service.DistributionRegistryUnavailable):
        await service.prepare_rps_distribution_access(pins=pins, purpose="catalog")


async def test_forged_receipt_never_opens_a_database_snapshot(monkeypatch):
    def fail():
        raise AssertionError("no database access for arbitrary receipt containers")
    monkeypatch.setattr(service, "get_engine", fail)
    with pytest.raises(service.DistributionRegistryUnavailable):
        await service.recheck_rps_distribution_access({"admitted_release_ids": ["invented"]})
