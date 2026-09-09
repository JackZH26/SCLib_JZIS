"""Exact rights-intent preparation on owned disposable SQL only.

Source/capsule fixtures and every reviewer declaration are synthetic. New-work
artifacts come exclusively from preparation. The explicitly labelled legacy
compatibility case reuses the unchanged old fixture's historical artifact path.
Recorded intent is not proof of a legal conclusion or scientific/ML approval.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, get_engine
from services import research_distribution as distribution
from services.research_access import ResearchAccessDenied
from services.research_priority import canonical_json, digest
from tests.rps_distribution_fixtures import publish_distribution, release_document
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_release_schema import capture


async def registered_fixture(db):
    """Actual registration only; no permission or rights artifact is preseeded."""
    context = await publish_distribution(db, release_document(), publish=False, permissions=False)
    assert context["permissions"] == []
    return context


def rights_arguments(context, *, dependency=None, head=None, decision="allow", request_key=None):
    dependency = dependency or context["registration"]["inventory"]["dependencies"][0]
    return {
        "actor_user_id": context["shared"]["actors"]["reviewer"],
        "request_key": request_key or "synthetic-rights:" + uuid4().hex,
        "package_id": context["registration"]["package_id"],
        "dependency_id": dependency["dependency_id"], "decision": decision,
        "license_code": "permission-on-file", "basis_code": "synthetic_disclosure_intent",
        "reason_code": "synthetic_rights_preparation",
        "expected_package_sha256": context["package"]["record_sha256"],
        "expected_inventory_sha256": context["registration"]["inventory_sha256"],
        "expected_dependency_row_sha256": dependency["row_sha256"],
        "expected_head_id": head["id"] if head else None,
        "expected_head_sha256": head["record_sha256"] if head else None,
    }


async def prepared_commit(db, arguments):
    from services.research_distribution_rights import prepare_distribution_rights

    preview = await prepare_distribution_rights(db, **arguments)
    result = await prepare_distribution_rights(
        db, **arguments, expected_intent_sha256=preview["intent_sha256"], dry_run=False,
    )
    return preview, result


async def test_preview_is_exact_canonical_intent_and_full_sql_noop(db_session):
    from services import research_distribution_rights as service

    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    before = await state(db_session)
    first = await service.prepare_distribution_rights(db_session, **arguments)
    second = await service.prepare_distribution_rights(db_session, **arguments)
    assert first == second
    assert before == await state(db_session)
    assert first["dry_run"] is True and first["committed"] is False
    assert first["artifact"] is None and first["permission"] is None
    expected = distribution.rights_review_payload(context["package"],
        context["registration"]["inventory"]["dependencies"][0], arguments["license_code"], arguments["basis_code"])
    assert first["rights_document"] == expected
    assert first["rights_bytes_sha256"] == digest(expected)
    assert first["intent_sha256"] == digest(first["intent"])
    assert first["scientific_acceptance"] is first["ml_training_approved"] is first["current_authorization_checked"] is False


async def test_commit_artifact_permission_and_unchanged_validator_replay_are_atomic(db_session):
    from services import research_distribution_rights as service

    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    before = await state(db_session)
    preview, result = await prepared_commit(db_session, arguments)
    assert result["committed"] is False and result["dry_run"] is False and result["replayed"] is False
    assert result["intent_sha256"] == preview["intent_sha256"]
    artifact = await capture(db_session, "evidence_artifacts", result["artifact"]["id"])
    assert artifact["kind"] == "review" and artifact["schema_version"] == distribution.RIGHTS_VERSION
    assert artifact["access"] == "restricted" and artifact["hash_status"] == "verified"
    assert artifact["metadata"] == {"distribution_rights": preview["rights_document"]}
    assert artifact["record_sha256"] == artifact["bytes_sha256"] == result["rights_bytes_sha256"]
    assert digest(artifact) == result["artifact"]["row_sha256"]
    after = await state(db_session)
    assert len(after["evidence_artifacts"]) == len(before["evidence_artifacts"]) + 1
    assert len(after["research_distribution_permissions"]) == len(before["research_distribution_permissions"]) + 1
    old = await distribution.decide_distribution_permission(
        db_session, **{key: arguments[key] for key in (
            "actor_user_id", "request_key", "package_id", "dependency_id", "decision", "license_code", "basis_code", "reason_code")},
        rights_artifact_id=result["artifact"]["id"], expected_rights_row_sha256=result["artifact"]["row_sha256"],
        rights_bytes=canonical_json(preview["rights_document"]).encode(), dry_run=False,
    )
    assert old["id"] == result["permission"]["id"] and old["replayed"] is True
    replay = await service.prepare_distribution_rights(db_session, **arguments,
        expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    assert replay["replayed"] is True and replay["permission"] == result["permission"]
    assert replay["artifact"] == result["artifact"] and after == await state(db_session)


@pytest.mark.parametrize("field", ["expected_package_sha256", "expected_inventory_sha256", "expected_dependency_row_sha256", "expected_intent_sha256"])
async def test_stale_independent_pins_refuse_without_artifact_or_epoch_change(db_session, field):
    from services import research_distribution_rights as service

    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    preview = await service.prepare_distribution_rights(db_session, **arguments)
    arguments.update(expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    arguments[field] = "0" * 64
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.prepare_distribution_rights(db_session, **arguments)
    assert before == await state(db_session)


async def test_same_key_different_intent_and_stale_head_never_create_replacement(db_session):
    from services import research_distribution_rights as service

    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    preview, first = await prepared_commit(db_session, arguments)
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.prepare_distribution_rights(db_session, **{**arguments, "reason_code": "different_intent"},
            expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    with pytest.raises(ValueError):
        await service.prepare_distribution_rights(db_session, **{**arguments, "request_key": "stale-head:" + uuid4().hex})
    assert before == await state(db_session)
    replacement = rights_arguments(context, head=first["permission"])
    _, second = await prepared_commit(db_session, replacement)
    assert second["permission"]["id"] != first["permission"]["id"]
    stable = await state(db_session)
    with pytest.raises(ValueError):
        await service.prepare_distribution_rights(db_session, **rights_arguments(context, head=first["permission"]))
    assert stable == await state(db_session)


@pytest.mark.parametrize("table", ["evidence_artifacts", "research_distribution_permissions"])
async def test_injected_insert_failure_rolls_back_artifact_and_permission(db_session, monkeypatch, table):
    from services import research_distribution_rights as service

    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    preview = await service.prepare_distribution_rights(db_session, **arguments)
    before = await state(db_session)
    execute = db_session.execute
    attempted = []

    async def fail(statement, *args, **kwargs):
        if getattr(statement, "is_insert", False):
            name = statement.table.name
            attempted.append(name)
            if name == table:
                raise SQLAlchemyError("PRIVATE_RIGHTS_FAILURE")
        return await execute(statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(db_session, "execute", fail)
        with pytest.raises(SQLAlchemyError):
            await service.prepare_distribution_rights(db_session, **arguments,
                expected_intent_sha256=preview["intent_sha256"], dry_run=False)
    assert table in attempted
    assert before == await state(db_session)


@pytest.mark.parametrize("role", ["admin", "curator", "publisher", "member"])
async def test_only_current_explicit_reviewer_can_prepare(db_session, role):
    from services import research_distribution_rights as service

    context = await registered_fixture(db_session)
    arguments = rights_arguments(context)
    arguments["actor_user_id"] = context["shared"]["actors"][role]
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await service.prepare_distribution_rights(db_session, **arguments)
    assert before == await state(db_session)


async def test_outer_rollback_removes_both_created_rows(db_session):
    context = await registered_fixture(db_session)
    await db_session.commit()
    before = await state(db_session)
    _, result = await prepared_commit(db_session, rights_arguments(context))
    assert result["artifact"] is not None and result["permission"] is not None
    await db_session.rollback()
    assert before == await state(db_session)


async def test_source_hold_blocks_positive_but_exact_protective_revoke_needs_no_old_bytes(db_session):
    from services import research_distribution_rights as service

    context = await registered_fixture(db_session)
    dependency = next(item for item in context["registration"]["inventory"]["dependencies"] if item["table"] == "papers")
    arguments = rights_arguments(context, dependency=dependency)
    _, first = await prepared_commit(db_session, arguments)
    await db_session.commit()
    await db_session.execute(sa.update(Base.metadata.tables["papers"]).where(
        Base.metadata.tables["papers"].c.id == context["shared"]["source"]["paper"]).values(status="retracted"))
    await db_session.execute(sa.update(Base.metadata.tables["evidence_artifacts"]).where(
        Base.metadata.tables["evidence_artifacts"].c.id == UUID(first["artifact"]["id"])).values(metadata={}))
    await db_session.commit()
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.prepare_distribution_rights(db_session, **rights_arguments(context, dependency=dependency, head=first["permission"]))
    assert before == await state(db_session)
    preview, revoked = await prepared_commit(db_session, rights_arguments(context, dependency=dependency, head=first["permission"], decision="revoke"))
    assert preview["rights_document"] == first["rights_document"]
    assert revoked["artifact"]["id"] == first["artifact"]["id"]
    assert len((await state(db_session))["evidence_artifacts"]) == len(before["evidence_artifacts"])


@pytest.mark.parametrize("existing_head", [False, True])
async def test_overlapping_writers_same_head_cannot_fork_or_leave_an_orphan(db_session, existing_head):
    from services import research_distribution_rights as service

    context = await registered_fixture(db_session)
    head = None
    if existing_head:
        _, predecessor = await prepared_commit(db_session, rights_arguments(context))
        head = predecessor["permission"]
    await db_session.commit()
    first, second = rights_arguments(context, head=head), rights_arguments(context, head=head)
    previews = [await service.prepare_distribution_rights(db_session, **arguments) for arguments in (first, second)]
    before = await state(db_session)
    await db_session.rollback()
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    async with AsyncSession(engine, expire_on_commit=False) as winner, AsyncSession(engine, expire_on_commit=False) as loser:
        await winner.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
        won = await service.prepare_distribution_rights(winner, **first,
            expected_intent_sha256=previews[0]["intent_sha256"], dry_run=False)
        # The first transaction owns a real appended artifact/permission and
        # governance locks, but has not committed. This is actual PostgreSQL
        # contention, not a mocked head query or simulated counter.
        await loser.execute(sa.text("SET LOCAL statement_timeout='1000ms'"))
        with pytest.raises(DBAPIError) as error:
            await service.prepare_distribution_rights(loser, **second,
                expected_intent_sha256=previews[1]["intent_sha256"], dry_run=False)
        assert error.value.orig.sqlstate == "55P03"
        await loser.rollback()
        await winner.commit()
        with pytest.raises(service.RightsPreparationConflict):
            await service.prepare_distribution_rights(loser, **second,
                expected_intent_sha256=previews[1]["intent_sha256"], dry_run=False)
        await loser.rollback()
    after = await state(db_session)
    assert len(after["evidence_artifacts"]) == len(before["evidence_artifacts"]) + 1
    assert len(after["research_distribution_permissions"]) == len(before["research_distribution_permissions"]) + 1
    permission = next(row for row in after["research_distribution_permissions"] if row["id"] == won["permission"]["id"])
    assert permission["supersedes_id"] == (head["id"] if head else None)


async def test_legacy_allow_is_not_a_preparation_receipt_but_can_be_protectively_revoked(db_session):
    from services import research_distribution_rights as service

    # Only this compatibility case uses the old synthetic fixture's direct
    # artifact construction. It is not evidence that the new path needs it.
    context = await publish_distribution(db_session, release_document(), publish=False)
    legacy = context["permissions"][0]
    permission = await distribution._get(db_session, "permissions", legacy["receipt"]["id"])
    document = distribution.rights_review_payload(context["package"], legacy["dependency"],
        permission["license_code"], permission["basis_code"])
    hypothetical = service._intent(context["package"], legacy["dependency"], permission, permission, None, document)
    before = await state(db_session)
    with pytest.raises(service.RightsPreparationConflict):
        await service.rights_preparation_outcome(db_session, actor_user_id=permission["actor_user_id"],
            package_id=permission["package_id"], dependency_id=permission["dependency_id"],
            request_key=permission["request_key"], expected_intent_sha256=digest(hypothetical))
    assert before == await state(db_session)
    arguments = rights_arguments(context, dependency=legacy["dependency"], head=legacy["receipt"], decision="revoke")
    preview, revoked = await prepared_commit(db_session, arguments)
    assert preview["rights_document"] == document
    assert revoked["artifact"]["id"] == str(legacy["arguments"]["rights_artifact_id"])
    stable = await state(db_session)
    assert len(stable["evidence_artifacts"]) == len(before["evidence_artifacts"])
    outcome = await service.rights_preparation_outcome(db_session,
        **{key: arguments[key] for key in ("actor_user_id", "package_id", "dependency_id", "request_key")},
        expected_intent_sha256=revoked["intent_sha256"])
    assert outcome["permission"] == revoked["permission"] and outcome["artifact"] == revoked["artifact"]
    assert outcome["replayed"] is True and await state(db_session) == stable
