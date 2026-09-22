"""Synthetic ML07 publication workflow on guarded disposable PostgreSQL."""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from services import research_freeze as freeze
from services import research_publication as service
from services.research_access import ResearchAccessDenied, require_research_operator
from services.research_public_contract import PublicResearchVerificationError
from services.research_release_manifest import canonical
from tests.test_research_freeze import add, approved, seed, state
from tests.test_research_freeze import db_session as _serializable_db_session

db_session = _serializable_db_session


async def actors(db):
    result = {}
    for role in ("admin", "curator", "reviewer", "publisher", "member"):
        uid = uuid4()
        await add(db, "users", id=uid, email=f"publication-{uid}@example.test", name="Synthetic reviewer",
                  is_active=True, email_verified=True, is_admin=role == "admin")
        result[role] = uid
    result["grants"] = {}
    for role in ("curator", "reviewer", "publisher"):
        grant = await service.grant_role(db, actor_user_id=result["admin"], user_id=result[role],
            role=role, reason_code="synthetic_role_review", dry_run=False)
        result["grants"][role] = UUID(grant["id"])
    return result


async def prepared(db, *, permissions=True):
    people = await actors(db)
    fixture = await seed(db)
    # These are only catalogue visibility fixtures, not accepted scientific
    # claims. Source values remain pending and never leave the public body.
    await db.execute(sa.text("UPDATE materials SET total_papers=1,needs_review=false WHERE id=:id"), {"id": fixture["material"]})
    await db.execute(sa.text("UPDATE works SET publication_status='active' WHERE id=:id"), {"id": fixture["work"]})
    _, arguments = await approved(db, fixture)
    release = await freeze.freeze_research_release(db, **arguments, dry_run=False)
    receipt_ids = []
    if permissions:
        for row in release["manifest"]["rows"]:
            receipt = await service.decide_permission(db, actor_user_id=people["reviewer"],
                release_id=release["release_id"], table_name=row["table"], row_id=row["row_id"],
                row_sha256=row["row_sha256"], decision="allow", license_code="permission-on-file",
                basis_code="synthetic_metadata_only", reason_code="synthetic_disclosure_review", dry_run=False)
            receipt_ids.append(UUID(receipt["id"]))
    return {"actors": people, "fixture": fixture, "arguments": arguments,
            "release": release, "permission_ids": receipt_ids}


async def proposed(db):
    context = await prepared(db)
    context["proposal"] = await service.propose_publication(db,
        actor_user_id=context["actors"]["curator"], release_id=context["release"]["release_id"],
        expected_capsule_sha256=context["release"]["manifest_sha256"],
        artifact_bytes=context["arguments"]["artifact_bytes"], dry_run=False)
    return context


async def published(db):
    context = await proposed(db)
    proposal, people = context["proposal"], context["actors"]
    context["review"] = await service.review_publication(db, actor_user_id=people["reviewer"],
        proposal_id=proposal["id"], expected_payload_sha256=proposal["payload_sha256"],
        disclosure_approved=True, reason_code="synthetic_independent_review", dry_run=False)
    context["action"] = await service.publication_action(db, actor_user_id=people["publisher"],
        proposal_id=proposal["id"], review_id=context["review"]["id"], expected_payload_sha256=proposal["payload_sha256"],
        kind="publish", reason_code="synthetic_publication", dry_run=False)
    return context


async def revoke_permission(db, context):
    permission = await service._get(db, "research_publication_permissions", context["permission_ids"][0])
    return await service.decide_permission(db, actor_user_id=context["actors"]["reviewer"],
        release_id=permission["release_id"], table_name=permission["table_name"], row_id=permission["row_id"],
        row_sha256=permission["row_sha256"], decision="revoke", license_code=permission["license_code"],
        basis_code="synthetic_rights_reconsidered", reason_code="synthetic_revocation",
        supersedes_id=permission["id"], dry_run=False)


async def test_full_metadata_publication_three_actors_and_withdrawal(db_session):
    context = await published(db_session)
    proposal = context["proposal"]
    admitted = await service.admitted_publication(db_session, proposal["id"])
    assert admitted["public_payload"] == proposal["public_payload"]
    encoded = canonical(admitted["public_payload"])
    for forbidden in (b"MgB2", b"39 K", b"Synthetic", b"password", b"abstract", b"freeze-paper:"):
        assert forbidden not in encoded
    assert admitted["public_payload"]["scientific_acceptance"] is False
    assert admitted["public_payload"]["ml_training_approved"] is False
    before = await service._get(db_session, "research_publication_proposals", proposal["id"])
    await service.publication_action(db_session, actor_user_id=context["actors"]["publisher"],
        proposal_id=proposal["id"], review_id=context["review"]["id"], expected_payload_sha256=proposal["payload_sha256"],
        kind="withdraw", reason_code="synthetic_withdrawal", dry_run=False)
    with pytest.raises(service.PublicationUnavailable):
        await service.admitted_publication(db_session, proposal["id"])
    assert await service._get(db_session, "research_publication_proposals", proposal["id"]) == before


@pytest.mark.parametrize("role", ["member", "admin"])
async def test_legacy_account_flags_do_not_grant_research_access(db_session, role):
    people = await actors(db_session)
    with pytest.raises(ResearchAccessDenied):
        await require_research_operator(db_session, people[role])
    with pytest.raises(ResearchAccessDenied):
        await service.grant_role(db_session, actor_user_id=people["member"], user_id=people["member"],
            role="publisher", reason_code="self_declared")


async def test_missing_or_stale_actual_bytes_and_permissions_block_proposal(db_session):
    context = await prepared(db_session, permissions=False)
    args = dict(actor_user_id=context["actors"]["curator"], release_id=context["release"]["release_id"],
        expected_capsule_sha256=context["release"]["manifest_sha256"], artifact_bytes=context["arguments"]["artifact_bytes"])
    before = await state(db_session)
    with pytest.raises(PublicResearchVerificationError):
        await service.propose_publication(db_session, **args, dry_run=False)
    assert await state(db_session) == before
    with pytest.raises(PublicResearchVerificationError):
        await service.propose_publication(db_session, **{**args, "artifact_bytes": {}})


async def test_full_dry_run_rollback_and_rejection_after_permission_revocation(db_session):
    context = await prepared(db_session)
    args = dict(actor_user_id=context["actors"]["curator"], release_id=context["release"]["release_id"],
        expected_capsule_sha256=context["release"]["manifest_sha256"], artifact_bytes=context["arguments"]["artifact_bytes"])
    before = await state(db_session)
    rehearsal = await service.propose_publication(db_session, **args)
    assert rehearsal["dry_run"] is True and rehearsal["committed"] is False
    assert await state(db_session) == before
    await revoke_permission(db_session, context)
    with pytest.raises(service.PublicationUnavailable):
        await service.propose_publication(db_session, **args, dry_run=False)


@pytest.mark.parametrize("change", ["permission", "curator_role", "reviewer_role", "publisher_role", "material", "paper", "work", "actor_inactive"])
async def test_current_governance_removes_access_without_changing_public_body(db_session, change):
    context = await published(db_session)
    original = deepcopy(context["proposal"]["public_payload"])
    if change == "permission":
        await revoke_permission(db_session, context)
    elif change.endswith("_role"):
        await service.revoke_role(db_session, actor_user_id=context["actors"]["admin"],
            grant_id=context["actors"]["grants"][change.removesuffix("_role")], reason_code="synthetic_revocation", dry_run=False)
    elif change == "actor_inactive":
        await db_session.execute(sa.text("UPDATE users SET is_active=false WHERE id=:id"), {"id": context["actors"]["publisher"]})
    else:
        table_name, column, value = {"material": ("materials", "needs_review", True),
            "paper": ("papers", "status", "retracted"), "work": ("works", "publication_status", "retracted")}[change]
        await db_session.execute(sa.text(f"UPDATE {table_name} SET {column}=:value WHERE id=:id"),
                                 {"id": context["fixture"][change], "value": value})
    with pytest.raises((service.PublicationUnavailable, ResearchAccessDenied)):
        await service.admitted_publication(db_session, context["proposal"]["id"])
    saved = await service._get(db_session, "research_publication_proposals", context["proposal"]["id"])
    assert saved["public_payload"] == original


async def test_review_requires_independent_actor_and_exact_digest(db_session):
    context = await proposed(db_session)
    people, proposal = context["actors"], context["proposal"]
    await service.grant_role(db_session, actor_user_id=people["admin"], user_id=people["curator"],
        role="reviewer", reason_code="synthetic_dual_role", dry_run=False)
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await service.review_publication(db_session, actor_user_id=people["curator"], proposal_id=proposal["id"],
            expected_payload_sha256=proposal["payload_sha256"], disclosure_approved=True, reason_code="self_review", dry_run=False)
    assert await state(db_session) == before
    with pytest.raises(service.PublicationUnavailable):
        await service.review_publication(db_session, actor_user_id=people["reviewer"], proposal_id=proposal["id"],
            expected_payload_sha256="0" * 64, disclosure_approved=True, reason_code="wrong_hash")


async def test_publisher_requires_third_actor_and_approved_review(db_session):
    context = await proposed(db_session)
    people, proposal = context["actors"], context["proposal"]
    review = await service.review_publication(db_session, actor_user_id=people["reviewer"], proposal_id=proposal["id"],
        expected_payload_sha256=proposal["payload_sha256"], disclosure_approved=False,
        reason_code="synthetic_rejected", dry_run=False)
    with pytest.raises(service.PublicationUnavailable):
        await service.publication_action(db_session, actor_user_id=people["publisher"], proposal_id=proposal["id"],
            review_id=review["id"], expected_payload_sha256=proposal["payload_sha256"], kind="publish", reason_code="rejected")


async def test_published_action_retries_cannot_republish_or_rewrite_history(db_session):
    context = await published(db_session)
    before = await state(db_session)
    with pytest.raises(DBAPIError):
        await service.publication_action(db_session, actor_user_id=context["actors"]["publisher"],
            proposal_id=context["proposal"]["id"], review_id=context["review"]["id"],
            expected_payload_sha256=context["proposal"]["payload_sha256"], kind="publish", reason_code="retry", dry_run=False)
    assert await state(db_session) == before


async def test_negative_review_after_publication_cannot_be_erased_by_later_approval(db_session):
    context = await published(db_session)
    args = dict(actor_user_id=context["actors"]["reviewer"], proposal_id=context["proposal"]["id"],
                expected_payload_sha256=context["proposal"]["payload_sha256"], reason_code="synthetic_reconsideration")
    await service.review_publication(db_session, **args, disclosure_approved=False, dry_run=False)
    await service.review_publication(db_session, **args, disclosure_approved=True, dry_run=False)
    with pytest.raises(service.PublicationUnavailable, match="disclosure-review hold"):
        await service.admitted_publication(db_session, context["proposal"]["id"])


async def test_multiple_role_grants_cannot_waive_distinct_publishing_account(db_session):
    context = await proposed(db_session)
    proposal, people = context["proposal"], context["actors"]
    await service.grant_role(db_session, actor_user_id=people["admin"], user_id=people["reviewer"],
        role="publisher", reason_code="synthetic_dual_role", dry_run=False)
    review = await service.review_publication(db_session, actor_user_id=people["reviewer"], proposal_id=proposal["id"],
        expected_payload_sha256=proposal["payload_sha256"], disclosure_approved=True,
        reason_code="synthetic_review", dry_run=False)
    with pytest.raises(ResearchAccessDenied, match="third distinct actor"):
        await service.publication_action(db_session, actor_user_id=people["reviewer"], proposal_id=proposal["id"],
            review_id=review["id"], expected_payload_sha256=proposal["payload_sha256"], kind="publish", reason_code="dual_role")
