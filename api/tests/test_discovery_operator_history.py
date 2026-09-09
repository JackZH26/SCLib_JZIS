"""Historical metadata on owned synthetic services, not positive admission."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_engine
from routers import discovery_projections as router
from services import discovery_operator_history as history
from services import discovery_projection_governance as governance
from services import research_publication as publication
from tests.test_discovery_projection_governance import (
    action_args,
    register,
    review_args,
)
from tests.test_discovery_projection_http import BASE, protected
from tests.test_research_distribution_operators import auth
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors


def no_bodies(value):
    if isinstance(value, dict):
        assert not set(value) & {
            "payload",
            "payload_json",
            "public_bundle",
            "public_bundle_json",
            "selection_json",
            "dependency_ids_json",
            "scientific_pins_json",
            "rights",
            "rights_json",
            "request_key",
            "request_sha256",
        }
        for item in value.values():
            no_bodies(item)
    elif isinstance(value, list):
        for item in value:
            no_bodies(item)


async def test_column_only_header_hashes_match_native_full_record_without_current_rebuild(
    db_session, monkeypatch
):
    context, arguments, receipt = await register(db_session)
    reviewed = await governance.review_projection(
        db_session, **review_args(context, receipt), dry_run=False
    )
    before = await state(db_session)

    def forbidden(*_args, **_kwargs):
        pytest.fail(
            "Historical metadata must not inspect current source/payload or the full-row helper"
        )

    monkeypatch.setattr(governance, "_current", forbidden)
    monkeypatch.setattr(governance, "_package", forbidden)
    monkeypatch.setattr(governance, "_rows", forbidden)
    result = await history.inspect_governance(
        db_session, actor_user_id=arguments["actor_user_id"], package_id=receipt["id"]
    )
    page = await history.review_history(
        db_session, actor_user_id=context["shared"]["actors"]["publisher"], package_id=receipt["id"]
    )
    assert result["package"]["record_sha256"] == receipt["record_sha256"]
    assert (
        result["review_count"] == 1 and result["rejection_count"] == 0 and result["actions"] == []
    )
    assert page["reviews"][0]["record_sha256"] == reviewed["record_sha256"]
    assert page["reviews"][0]["id"] == reviewed["id"] and page["next_after"] is None
    assert result["history_sha256"] == page["history_sha256"]
    assert result["current_publication_eligibility"] == "not_checked"
    assert all(result[k] is False for k in history.AUTHORITY)
    no_bodies(result)
    no_bodies(page)
    assert before == await state(db_session)


async def test_actual_sql_projects_scalar_subquery_not_payload_columns(db_session):
    _, arguments, receipt = await register(db_session)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    connection = await db_session.connection()
    sa.event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        await history.inspect_governance(
            db_session, actor_user_id=arguments["actor_user_id"], package_id=receipt["id"]
        )
    finally:
        sa.event.remove(connection.sync_connection, "before_cursor_execute", capture)
    sql = "\n".join(statements)
    for field in governance._JSON_FIELDS:
        assert field not in sql
    assert "sclib_discovery_projection_hash_v1(to_jsonb(anon_1))" in sql


async def test_paginated_full_snapshot_rejects_new_appends_and_unknown_cursor(db_session):
    context, args, receipt = await register(db_session)
    retained = []
    for _ in range(27):
        retained.append(
            await governance.review_projection(
                db_session, **review_args(context, receipt, decision="reject"), dry_run=False
            )
        )
    actor, package = args["actor_user_id"], receipt["id"]
    before = await state(db_session)
    first = await history.review_history(db_session, actor_user_id=actor, package_id=package)
    assert first["review_count"] == first["rejection_count"] == 27 and first["has_rejection"]
    assert first["returned_count"] == len(first["reviews"]) == 25
    second = await history.review_history(
        db_session,
        actor_user_id=actor,
        package_id=package,
        after=first["next_after"],
        expected_history_sha256=first["history_sha256"],
    )
    assert second["returned_count"] == 2 and second["next_after"] is None
    assert [row["id"] for row in first["reviews"] + second["reviews"]] == [
        row["id"] for row in retained
    ]
    assert before == await state(db_session)
    with pytest.raises(governance.DiscoveryGovernanceConflict):
        await history.review_history(
            db_session,
            actor_user_id=actor,
            package_id=package,
            after=str(uuid4()),
            expected_history_sha256=first["history_sha256"],
        )
    await governance.review_projection(
        db_session, **review_args(context, receipt, decision="reject"), dry_run=False
    )
    with pytest.raises(governance.DiscoveryGovernanceConflict):
        await history.review_history(
            db_session,
            actor_user_id=actor,
            package_id=package,
            after=first["next_after"],
            expected_history_sha256=first["history_sha256"],
        )
    new = await history.inspect_governance(db_session, actor_user_id=actor, package_id=package)
    assert new["review_count"] == 28 and new["history_sha256"] != first["history_sha256"]


async def test_later_approval_does_not_erase_rejection_or_create_current_head(db_session):
    context, args, receipt = await register(db_session)
    negative = review_args(context, receipt, decision="reject")
    negative.update(representative_selection_approved=True, disclosure_approved=True)
    rejected = await governance.review_projection(db_session, **negative, dry_run=False)
    approved = await governance.review_projection(
        db_session, **review_args(context, receipt), dry_run=False
    )
    result = await history.review_history(
        db_session, actor_user_id=args["actor_user_id"], package_id=receipt["id"]
    )
    assert result["has_rejection"] and result["rejection_count"] == 1
    assert [row["id"] for row in result["reviews"]] == [rejected["id"], approved["id"]]
    assert result["reviews"][0]["representative_selection_approved"] is True
    assert "head" not in result and "current_review" not in result
    with pytest.raises(ValueError, match="review_held"):
        await governance.projection_action(db_session, **action_args(context, receipt, approved))


async def test_withdraw_before_publish_is_recorded_without_inventing_publication(db_session):
    context, args, receipt = await register(db_session)
    reviewed = await governance.review_projection(
        db_session, **review_args(context, receipt), dry_run=False
    )
    withdrawn = await governance.projection_action(
        db_session, **action_args(context, receipt, reviewed, kind="withdraw"), dry_run=False
    )
    header = await history.inspect_governance(
        db_session, actor_user_id=args["actor_user_id"], package_id=receipt["id"]
    )
    assert header["has_withdrawal"] and header["actions"][0]["kind"] == "withdraw"
    assert header["actions"][0]["id"] == withdrawn["id"] and len(header["actions"]) == 1
    assert header["current_publication_eligibility"] == "not_checked"


async def test_holds_and_historical_grant_revocation_preserve_metadata_and_protective_actions(
    db_session,
):
    context, args, receipt = await register(db_session)
    people = context["shared"]["actors"]
    reviewed = await governance.review_projection(
        db_session, **review_args(context, receipt), dry_run=False
    )
    await publication.revoke_role(
        db_session,
        actor_user_id=people["admin"],
        grant_id=people["grants"]["curator"],
        reason_code="synthetic_hold",
        dry_run=False,
    )
    await db_session.execute(
        sa.text("UPDATE materials SET needs_review=true WHERE id=:id"),
        {"id": context["shared"]["source"]["material"]},
    )
    for role in ("reviewer", "publisher"):
        result = await history.inspect_governance(
            db_session, actor_user_id=people[role], package_id=receipt["id"]
        )
        assert result["package"]["actor_grant_id"] == str(people["grants"]["curator"])
        no_bodies(result)
    with pytest.raises(ValueError):
        await governance.inspect_projection(
            db_session, actor_user_id=people["reviewer"], package_id=receipt["id"]
        )
    rejected = await governance.review_projection(
        db_session, **review_args(context, receipt, decision="reject"), dry_run=False
    )
    await publication.revoke_role(
        db_session,
        actor_user_id=people["admin"],
        grant_id=people["grants"]["reviewer"],
        reason_code="synthetic_hold",
        dry_run=False,
    )
    withdrawn = await governance.projection_action(
        db_session, **action_args(context, receipt, reviewed, kind="withdraw"), dry_run=False
    )
    result = await history.review_history(
        db_session, actor_user_id=people["publisher"], package_id=receipt["id"]
    )
    assert result["has_rejection"] and result["has_withdrawal"]
    assert (
        result["reviews"][-1]["id"] == rejected["id"]
        and result["actions"][0]["id"] == withdrawn["id"]
    )


async def test_bound_exceeded_rejects_whole_inventory_not_truncated_success(
    db_session, monkeypatch
):
    context, args, receipt = await register(db_session)
    for _ in range(3):
        await governance.review_projection(
            db_session, **review_args(context, receipt, decision="reject"), dry_run=False
        )
    monkeypatch.setattr(history, "MAX_REVIEWS", 2)
    with pytest.raises(ValueError, match="inventory_limit"):
        await history.inspect_governance(
            db_session, actor_user_id=args["actor_user_id"], package_id=receipt["id"]
        )


@pytest.mark.parametrize("role", [None, "admin", "member", "curator", "reviewer", "publisher"])
async def test_actual_access_only_current_explicit_roles(client, db_session, role):
    people = await actors(db_session)
    await db_session.commit()
    response = await client.get(
        BASE + "/operator/access", headers={} if role is None else auth(people[role])
    )
    assert response.status_code == (
        401 if role is None else 403 if role in {"admin", "member"} else 200
    ), response.text
    protected(response)
    if response.status_code == 200:
        result = response.json()
        assert result["grants"] == [{"role": role, "id": str(people["grants"][role])}]
        assert result["actor_user_id"] == str(people[role])
        assert all(result[k] is False for k in history.AUTHORITY)


async def test_access_reports_all_explicit_roles_and_regrant_not_legacy_flags(db_session):
    people = await actors(db_session)
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db_session.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
    for role in ("publisher", "reviewer"):
        await publication.grant_role(
            db_session,
            actor_user_id=people["admin"],
            user_id=people["curator"],
            role=role,
            reason_code="synthetic_multiple_roles",
            dry_run=False,
        )
    result = await history.operator_access(db_session, actor_user_id=people["curator"])
    assert [row["role"] for row in result["grants"]] == ["curator", "publisher", "reviewer"]
    await publication.revoke_role(
        db_session,
        actor_user_id=people["admin"],
        grant_id=people["grants"]["curator"],
        reason_code="synthetic_regrant",
        dry_run=False,
    )
    new = await publication.grant_role(
        db_session,
        actor_user_id=people["admin"],
        user_id=people["curator"],
        role="curator",
        reason_code="synthetic_regrant",
        dry_run=False,
    )
    assert (await history.operator_access(db_session, actor_user_id=people["curator"]))["grants"][
        0
    ]["id"] == new["id"]


@pytest.mark.parametrize(
    "path",
    [
        "governance?x=1",
        "reviews?after=bad",
        "reviews?after=00000000-0000-0000-0000-000000000000",
        "reviews?expected_history_sha256=bad",
        "reviews?after=x&after=y",
        "reviews?limit=100",
        "reviews?expected_history_sha256=a&expected_history_sha256=b",
    ],
)
async def test_closed_history_queries_are_static(client, db_session, path):
    people = await actors(db_session)
    await db_session.commit()
    response = await client.get(
        BASE + "/" + str(uuid4()) + "/" + path, headers=auth(people["reviewer"])
    )
    assert response.status_code == 400, response.text
    protected(response)


async def test_actual_http_read_after_source_hold_is_noop_and_cannot_leak_body_or_other_request_key(
    client, db_session, tmp_path
):
    context, args, receipt = await register(db_session)
    people = context["shared"]["actors"]
    reviewed = await governance.review_projection(
        db_session, **review_args(context, receipt), dry_run=False
    )
    await db_session.execute(
        sa.text("UPDATE materials SET needs_review=true WHERE id=:id"),
        {"id": context["shared"]["source"]["material"]},
    )
    await db_session.commit()
    before = await state(db_session)
    await db_session.rollback()
    responses = {}
    for role in ("curator", "reviewer", "publisher"):
        for suffix in ("governance", "reviews"):
            response = await client.get(
                f"{BASE}/{receipt['id']}/{suffix}", headers=auth(people[role])
            )
            assert response.status_code == 200, response.text
            protected(response)
            no_bodies(response.json())
            assert args["request_key"] not in response.text
            assert response.json()["package"]["record_sha256"] == receipt["record_sha256"]
            responses[f"{role}-{suffix}"] = response.json()
    denied = await client.get(BASE + "/" + receipt["id"], headers=auth(people["reviewer"]))
    assert denied.status_code == 400
    assert before == await state(db_session)
    assert responses["publisher-reviews"]["reviews"][0]["id"] == reviewed["id"]
    (tmp_path / "historical-read-synthetic-evidence.json").write_text(
        json.dumps(responses, sort_keys=True)
    )


async def test_actual_http_history_conflict_after_separate_committed_review(client, db_session):
    context, args, receipt = await register(db_session)
    people = context["shared"]["actors"]
    await db_session.commit()
    first = await client.get(
        f"{BASE}/{receipt['id']}/governance", headers=auth(people["publisher"])
    )
    assert first.status_code == 200
    request = review_args(context, receipt, decision="reject")
    request.pop("actor_user_id")
    request.pop("package_id")
    request["dry_run"] = False
    committed = await client.post(
        f"{BASE}/{receipt['id']}/reviews", json=request, headers=auth(people["reviewer"])
    )
    assert committed.status_code == 200 and committed.json()["committed"] is True
    response = await client.get(
        f"{BASE}/{receipt['id']}/reviews",
        params={"expected_history_sha256": first.json()["history_sha256"]},
        headers=auth(people["publisher"]),
    )
    assert response.status_code == 409
    protected(response)


@pytest.mark.parametrize("path", ["governance", "reviews"])
async def test_absent_and_unadmitted_history(client, db_session, path):
    people = await actors(db_session)
    await db_session.commit()
    for role in (None, "admin", "member", "reviewer"):
        response = await client.get(
            f"{BASE}/{uuid4()}/{path}", headers={} if role is None else auth(people[role])
        )
        assert response.status_code == (
            401 if role is None else 403 if role in {"admin", "member"} else 404
        )
        protected(response)


async def test_metadata_rejects_wrong_header_digest_without_exposing_context(
    db_session, monkeypatch
):
    _, args, receipt = await register(db_session)
    monkeypatch.setattr(governance, "_HASH", lambda _value: sa.literal("0" * 64))
    with pytest.raises(ValueError, match="header_invalid"):
        await history.inspect_governance(
            db_session, actor_user_id=args["actor_user_id"], package_id=receipt["id"]
        )


async def test_router_reads_use_read_only_repeatable_snapshot(db_session, monkeypatch):
    # Exercise the actual read wrapper rather than merely inspecting its source.
    people = await actors(db_session)
    await db_session.commit()
    from models.db import User

    async with AsyncSession(get_engine()) as db:
        user = await db.get(User, people["reviewer"])

        async def inspect_settings(session, **_kwargs):
            return (
                await session.execute(
                    sa.text(
                        "SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation'), current_setting('TimeZone')"
                    )
                )
            ).one()

        result = await router._read(user, inspect_settings)
        assert tuple(result) == ("on", "repeatable read", "UTC")
