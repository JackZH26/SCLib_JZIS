"""Direct SQL governance regression tests on guarded disposable PostgreSQL."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from models.db import Base, get_engine, get_session_factory
from models.research_publication_v1 import LOCK_FUNCTION, TABLE_ORDER
from models.research_release_v1 import ALLOWED_TABLES
from services.research_public_contract import EXCLUSIONS, LIMITS, VERSION, public_object_sha256
from services.research_release_manifest import digest
from tests.test_research_release_schema import flush_constraints, release, seed


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        await session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        await session.execute(sa.text("SET LOCAL TimeZone='UTC'"))
        yield session


async def add(db, table_name, /, **values):
    if table_name in TABLE_ORDER[1:] and "record_sha256" not in values:
        values["record_sha256"] = digest({key: str(value) if isinstance(value, UUID) else value
                                         for key, value in values.items() if key not in ("id", "created_at")})
    table = Base.metadata.tables[table_name]
    return (await db.execute(table.insert().values(**values).returning(table))).mappings().one()


async def user(db, **overrides):
    return await add(db, "users", id=uuid4(), name="Synthetic governance actor", email=uuid4().hex + "@example.invalid",
                     **{"is_active": True, "email_verified": True, "is_admin": False, **overrides})


async def role(db, subject, admin, name):
    return await add(db, "research_role_grants", id=uuid4(), user_id=subject["id"], role=name,
                     granted_by=admin["id"], reason_code="synthetic_authorization")


async def actors(db):
    admin = await user(db, is_admin=True)
    result = {"admin": admin}
    for name in ("curator", "reviewer", "publisher"):
        subject = await user(db)
        grant = await role(db, subject, admin, name)
        result[name] = subject
        result[name + "_grant"] = grant
    return result


def actor_fields(people, name):
    return {"actor_user_id": people[name]["id"], "actor_grant_id": people[name + "_grant"]["id"]}


def test_governance_is_additive_and_metadata_only():
    assert len(TABLE_ORDER) == 7
    assert set(TABLE_ORDER) <= set(Base.metadata.tables)
    proposal = Base.metadata.tables["research_publication_proposals"]
    assert str(next(iter(proposal.c.release_id.foreign_keys)).column) == "research_releases.id"
    review = Base.metadata.tables["research_publication_reviews"]
    assert "scientific_acceptance=false" in " ".join(str(item.sqltext) for item in review.constraints
                                                     if isinstance(item, sa.CheckConstraint))


@pytest.mark.parametrize("field", ["is_active", "email_verified", "is_admin"])
async def test_admin_grant_requires_all_three_account_checks(db_session, field):
    admin = await user(db_session, **{"is_admin": True, field: False})
    subject = await user(db_session)
    with pytest.raises(DBAPIError, match="active_admin_and_user"):
        async with db_session.begin_nested():
            await role(db_session, subject, admin, "curator")


@pytest.mark.parametrize("field", ["is_active", "email_verified"])
async def test_grantee_must_be_active_verified(db_session, field):
    admin = await user(db_session, is_admin=True)
    subject = await user(db_session, **{field: False})
    with pytest.raises(DBAPIError, match="active_admin_and_user"):
        async with db_session.begin_nested():
            await role(db_session, subject, admin, "curator")


async def test_legacy_admin_reviewer_flags_do_not_create_research_roles(db_session):
    subject = await user(db_session, is_admin=True, is_reviewer=True)
    allowed = await db_session.scalar(sa.text("SELECT public.sclib_research_publication_role_v1(:user,:grant,'reviewer')"),
                                      {"user": subject["id"], "grant": uuid4()})
    assert allowed is False


async def test_explicit_grant_revocation_and_regrant_are_append_only(db_session):
    people = await actors(db_session)
    with pytest.raises(DBAPIError, match="active_grant_exists"):
        async with db_session.begin_nested():
            await role(db_session, people["curator"], people["admin"], "curator")
    revoked = await add(db_session, "research_role_revocations", id=uuid4(), grant_id=people["curator_grant"]["id"],
                        revoked_by=people["admin"]["id"], reason_code="synthetic_revocation")
    assert revoked["grant_id"] == people["curator_grant"]["id"]
    replacement = await role(db_session, people["curator"], people["admin"], "curator")
    for grant, expected in ((people["curator_grant"], False), (replacement, True)):
        result = await db_session.scalar(sa.text("SELECT public.sclib_research_publication_role_v1(:user,:grant,'curator')"),
                                         {"user": people["curator"]["id"], "grant": grant["id"]})
        assert result is expected


async def test_nonadmin_cannot_revoke_research_roles(db_session):
    people = await actors(db_session)
    with pytest.raises(DBAPIError, match="revoke_requires_active_admin"):
        async with db_session.begin_nested():
            await add(db_session, "research_role_revocations", id=uuid4(), grant_id=people["curator_grant"]["id"],
                      revoked_by=people["reviewer"]["id"], reason_code="synthetic_revocation")


@pytest.mark.parametrize("role_name", ["admin", "reader", "", "Reviewer"])
async def test_undeclared_role_names_rejected(db_session, role_name):
    admin = await user(db_session, is_admin=True)
    subject = await user(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await role(db_session, subject, admin, role_name)


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_grant_history_rejects_mutation(db_session, operation):
    await actors(db_session)
    command = {"UPDATE": "UPDATE research_role_grants SET role=role", "DELETE": "DELETE FROM research_role_grants",
               "TRUNCATE": "TRUNCATE research_role_grants CASCADE"}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(command))


async def test_writer_requires_serializable_and_epoch(db_session):
    engine = get_engine()
    try:
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="requires_serializable"):
                await connection.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        await db_session.execute(sa.text("DELETE FROM research_publication_epoch"))
        with pytest.raises(DBAPIError, match="epoch_missing"):
            async with db_session.begin_nested():
                await db_session.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
    finally:
        await engine.dispose()


async def test_contending_writer_fails_without_waiting(db_session):
    await db_session.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="busy_retry_transaction"):
                await asyncio.wait_for(connection.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()")), timeout=3)
    finally:
        await engine.dispose()


async def test_stale_serializable_writer_must_retry():
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with engine.connect() as stale, engine.connect() as writer:
            await stale.execute(sa.text("SELECT epoch FROM research_publication_epoch"))
            await writer.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
            await writer.commit()
            with pytest.raises(DBAPIError, match="concurrent update|serialize"):
                await stale.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
    finally:
        await engine.dispose()


async def permission(db, case, row, **overrides):
    values = {"release_id": case["capsule"]["id"], "manifest_sha256": case["capsule"]["manifest_sha256"],
              "table_name": row["table"], "row_id": row["row_id"], "row_sha256": row["row_sha256"],
              "decision": "allow", "scope": "metadata_only", "license_code": "permission-on-file",
              "basis_code": "synthetic_disclosure_assertion", "supersedes_id": None,
              "reason_code": "synthetic_metadata_permission", **actor_fields(case["people"], "reviewer"), **overrides}
    return await add(db, "research_publication_permissions", id=uuid4(), **values)


def document(case):
    objects = []
    root = None
    for row, decision in zip(case["rows"], case["permissions"], strict=True):
        object_hash = public_object_sha256(capsule_sha256=case["capsule"]["manifest_sha256"],
                                          table=row["table"], row_id=row["row_id"], row_sha256=row["row_sha256"])
        objects.append({"table": row["table"], "object_sha256": object_hash, "permission_id": str(decision["id"]),
                        "permission_sha256": decision["record_sha256"], "scope": "metadata_only",
                        "license_code": decision["license_code"]})
        if row["table"] == "ml_dataset_snapshots" and row["row_id"] == str(case["capsule"]["dataset_snapshot_id"]):
            root = object_hash
    return {"version": VERSION, "scope": "metadata_only", "capsule_sha256": case["capsule"]["manifest_sha256"],
            "dataset_object_sha256": root, "objects": sorted(objects, key=lambda row: (row["table"], row["object_sha256"])),
            "counts": [{"table": name, "object_count": sum(row["table"] == name for row in objects)}
                       for name in sorted(ALLOWED_TABLES)], "exclusions": dict(EXCLUSIONS), "limits": dict(LIMITS),
            "scientific_acceptance": False, "ml_training_approved": False}


async def proposal(db, case, **overrides):
    body = document(case)
    values = {"release_id": case["capsule"]["id"], "manifest_sha256": case["capsule"]["manifest_sha256"],
              "public_payload": body, "payload_sha256": digest(body), "policy_version": VERSION,
              **actor_fields(case["people"], "curator"), **overrides}
    return await add(db, "research_publication_proposals", id=uuid4(), **values)


async def review(db, case, **overrides):
    prop = case["proposal"]
    values = {"proposal_id": prop["id"], "manifest_sha256": prop["manifest_sha256"], "payload_sha256": prop["payload_sha256"],
              "disclosure_approved": True, "scientific_acceptance": False, "ml_training_approved": False,
              "reason_code": "synthetic_metadata_review", **actor_fields(case["people"], "reviewer"), **overrides}
    return await add(db, "research_publication_reviews", id=uuid4(), **values)


async def action(db, case, **overrides):
    prop = case["proposal"]
    values = {"proposal_id": prop["id"], "manifest_sha256": prop["manifest_sha256"], "payload_sha256": prop["payload_sha256"],
              "kind": "publish", "review_id": case["review"]["id"], "reason_code": "synthetic_metadata_action",
              **actor_fields(case["people"], "publisher"), **overrides}
    return await add(db, "research_publication_actions", id=uuid4(), **values)


async def prepared(db, *, with_proposal=True, with_review=True):
    people = await actors(db)
    fixture = await seed(db)
    capsule, rows = await release(db, fixture)
    await flush_constraints(db)
    case = {"people": people, "capsule": capsule, "rows": rows, "fixture": fixture, "permissions": []}
    for row in rows:
        case["permissions"].append(await permission(db, case, row))
    if with_proposal:
        case["proposal"] = await proposal(db, case)
        if with_review:
            case["review"] = await review(db, case)
    return case


async def test_complete_metadata_publication_then_withdraw_preserves_capsule_flags(db_session):
    case = await prepared(db_session)
    published = await action(db_session, case)
    withdrawn = await action(db_session, case, kind="withdraw")
    assert published["review_id"] == withdrawn["review_id"]
    actual = (await db_session.execute(sa.select(Base.metadata.tables["research_releases"]).where(
        Base.metadata.tables["research_releases"].c.id == case["capsule"]["id"]))).mappings().one()
    assert actual["scientific_acceptance"] is False and actual["public_release"] is False
    assert actual["manifest_sha256"] == case["capsule"]["manifest_sha256"]


@pytest.mark.parametrize("mutated", ["row_id", "row_sha256", "manifest_sha256", "table_name", "scope", "license_code"])
async def test_permission_requires_exact_pin_and_narrow_scope(db_session, mutated):
    case = await prepared(db_session, with_proposal=False)
    changes = {"row_id": "does-not-exist", "row_sha256": "0" * 64, "manifest_sha256": "0" * 64,
               "table_name": "users", "scope": "full_text", "license_code": "unknown"}
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await permission(db_session, case, case["rows"][0], **{mutated: changes[mutated]})


async def test_permission_revoke_requires_latest_exact_predecessor(db_session):
    case = await prepared(db_session)
    current = case["permissions"][0]
    revoked = await permission(db_session, case, case["rows"][0], decision="revoke", supersedes_id=current["id"])
    with pytest.raises(DBAPIError, match="predecessor_mismatch"):
        async with db_session.begin_nested():
            await permission(db_session, case, case["rows"][0], supersedes_id=current["id"])
    with pytest.raises(DBAPIError, match="predecessor_mismatch"):
        async with db_session.begin_nested():
            await permission(db_session, case, case["rows"][1], supersedes_id=revoked["id"])
    renewed = await permission(db_session, case, case["rows"][0], supersedes_id=revoked["id"])
    assert renewed["decision"] == "allow"
    # A newly allowed head cannot make an older captured receipt current.
    with pytest.raises(DBAPIError, match="current_exact_receipt"):
        async with db_session.begin_nested():
            await action(db_session, case)


@pytest.mark.parametrize("position", ["top", "object", "counts", "exclusions", "limits"])
async def test_nested_unreviewed_payload_fields_rejected_even_when_rehashed(db_session, position):
    case = await prepared(db_session, with_proposal=False)
    body = deepcopy(document(case))
    target = {"top": body, "object": body["objects"][0], "counts": body["counts"][0],
              "exclusions": body["exclusions"], "limits": body["limits"]}[position]
    target["restricted_text_canary"] = "Synthetic restricted source text"
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await proposal(db_session, case, public_payload=body, payload_sha256=digest(body))


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "permission_hash", "opaque_hash", "license", "dataset", "approval"])
async def test_resealed_receipts_cannot_omit_replace_or_expand_dependency(db_session, change):
    case = await prepared(db_session, with_proposal=False)
    body = deepcopy(document(case))
    if change == "missing":
        body["objects"].pop()
    elif change == "extra":
        body["objects"].append(deepcopy(body["objects"][0]))
    elif change == "duplicate":
        body["objects"][1] = deepcopy(body["objects"][0])
    elif change == "permission_hash":
        body["objects"][0]["permission_sha256"] = "0" * 64
    elif change == "opaque_hash":
        body["objects"][0]["object_sha256"] = "0" * 64
    elif change == "license":
        body["objects"][0]["license_code"] = "CC0-1.0"
    elif change == "dataset":
        body["dataset_object_sha256"] = "0" * 64
    else:
        body["scientific_acceptance"] = True
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await proposal(db_session, case, public_payload=body, payload_sha256=digest(body))


@pytest.mark.parametrize("actor_name", ["curator", "reviewer"])
async def test_publisher_must_be_third_actor_even_when_separately_granted(db_session, actor_name):
    case = await prepared(db_session)
    grant = await role(db_session, case["people"][actor_name], case["people"]["admin"], "publisher")
    with pytest.raises(DBAPIError, match="independent_"):
        async with db_session.begin_nested():
            await action(db_session, case, actor_user_id=case["people"][actor_name]["id"], actor_grant_id=grant["id"])


async def test_review_must_be_independent_of_proposer(db_session):
    case = await prepared(db_session, with_review=False)
    grant = await role(db_session, case["people"]["curator"], case["people"]["admin"], "reviewer")
    with pytest.raises(DBAPIError, match="independent_actor"):
        async with db_session.begin_nested():
            await review(db_session, case, actor_user_id=case["people"]["curator"]["id"], actor_grant_id=grant["id"])


@pytest.mark.parametrize("override", [{"disclosure_approved": False}, {"payload_sha256": "0" * 64},
                                     {"manifest_sha256": "0" * 64}, {"scientific_acceptance": True},
                                     {"ml_training_approved": True}])
async def test_review_never_promotes_science_or_approves_a_different_payload(db_session, override):
    case = await prepared(db_session, with_review=False)
    if override == {"disclosure_approved": False}:
        case["review"] = await review(db_session, case, **override)
        with pytest.raises(DBAPIError, match="approved_exact_review"):
            async with db_session.begin_nested():
                await action(db_session, case)
    else:
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await review(db_session, case, **override)


@pytest.mark.parametrize("name", ["curator", "reviewer", "publisher"])
async def test_revoked_actor_grant_prevents_publication(db_session, name):
    case = await prepared(db_session)
    await add(db_session, "research_role_revocations", id=uuid4(), grant_id=case["people"][name + "_grant"]["id"],
              revoked_by=case["people"]["admin"]["id"], reason_code="synthetic_revocation")
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await action(db_session, case)


async def test_withdraw_cannot_precede_publish_or_change_review(db_session):
    case = await prepared(db_session)
    with pytest.raises(DBAPIError, match="withdraw_requires_publication"):
        async with db_session.begin_nested():
            await action(db_session, case, kind="withdraw")
    await action(db_session, case)
    other_review = await review(db_session, case, reason_code="another_valid_review")
    with pytest.raises(DBAPIError, match="withdraw_requires_publication"):
        async with db_session.begin_nested():
            await action(db_session, case, kind="withdraw", review_id=other_review["id"])
    await action(db_session, case, kind="withdraw")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await action(db_session, case)


async def test_negative_review_cannot_be_waived_by_another_positive_review(db_session):
    case = await prepared(db_session)
    await review(db_session, case, disclosure_approved=False, reason_code="metadata_disclosure_rejected")
    latest = await review(db_session, case, disclosure_approved=True, reason_code="later_positive_review")
    with pytest.raises(DBAPIError, match="negative_review_hold"):
        async with db_session.begin_nested():
            await action(db_session, case, review_id=latest["id"])


async def test_withdraw_remains_possible_after_negative_review_or_role_hold(db_session):
    case = await prepared(db_session)
    await action(db_session, case)
    await review(db_session, case, disclosure_approved=False, reason_code="post_publication_rejection")
    await add(db_session, "research_role_revocations", id=uuid4(), grant_id=case["people"]["curator_grant"]["id"],
              revoked_by=case["people"]["admin"]["id"], reason_code="synthetic_revocation")
    assert (await action(db_session, case, kind="withdraw"))["kind"] == "withdraw"


@pytest.mark.parametrize("name", TABLE_ORDER[1:])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_all_governance_history_is_append_only(db_session, name, operation):
    case = await prepared(db_session)
    await action(db_session, case)
    await add(db_session, "research_role_revocations", id=uuid4(), grant_id=case["people"]["curator_grant"]["id"],
              revoked_by=case["people"]["admin"]["id"], reason_code="synthetic_revocation")
    command = {"UPDATE": f"UPDATE {name} SET id=id", "DELETE": f"DELETE FROM {name}", "TRUNCATE": f"TRUNCATE {name} CASCADE"}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(command))


@pytest.mark.parametrize("identifier", ["synthetic", 'quote-"-slash-\\', "Unicode-晶体-Δ"])
async def test_sql_opaque_object_digest_matches_pure_contract(db_session, identifier):
    actual = await db_session.scalar(sa.text("SELECT public.sclib_research_publication_object_v1(:capsule,:table,:row,:hash)"),
                                     {"capsule": "a" * 64, "table": "materials", "row": identifier, "hash": "b" * 64})
    assert actual == public_object_sha256(capsule_sha256="a" * 64, table="materials", row_id=identifier, row_sha256="b" * 64)
