"""Research audit identity holds preserve accounts and private rows atomically."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import allowed_browser_origins, get_settings
from models.db import (
    ApiKey,
    AskHistory,
    AuthAuditEvent,
    Base,
    Bookmark,
    User,
    get_engine,
    get_session_factory,
)
from services.research_audit_retention import (
    AUDIT_USER_FK_CONSTRAINTS,
    AUDIT_USER_REFERENCES,
    RETENTION_MESSAGE,
    has_research_audit_references,
    is_research_audit_reference_violation,
)
from services.session_config import build_browser_session_config
from tests.research_access_helpers import research_grant, research_user, revoke_research_grant


async def private_rows(user_id):
    async with get_session_factory()() as db:
        db.add_all([
            ApiKey(user_id=user_id, key_hash=uuid4().hex, key_prefix="scl_retained", name="Synthetic retained key"),
            AskHistory(user_id=user_id, question="Synthetic private question", answer="Synthetic private answer",
                       sources=[], latency_ms=1),
            Bookmark(user_id=user_id, target_type="material", target_id="synthetic-retention"),
            AuthAuditEvent(event_type="login", outcome="success", user_id=user_id, account_hash=uuid4().hex,
                           client_ip_hash=uuid4().hex, details={"flow": "synthetic-retention"}),
        ])
        await db.commit()


async def snapshot(user_id):
    async with get_session_factory()() as db:
        rows = {}
        for model in (User, ApiKey, AskHistory, Bookmark, AuthAuditEvent):
            table = model.__table__
            field = table.c.id if model is User else table.c.user_id
            rows[table.name] = (await db.execute(sa.select(sa.func.to_jsonb(table.table_valued()))
                .where(field == user_id).order_by(table.c.id))).scalars().all()
        return rows


async def reference_account(user_id, mode):
    administrator = await research_user(is_admin=True)
    if mode in ("grantee", "revoked_grantee"):
        grant_id = await research_grant(user_id=user_id, granted_by=administrator["id"])
        if mode == "revoked_grantee":
            await revoke_research_grant(grant_id=grant_id, revoked_by=administrator["id"])
    else:
        other = await research_user()
        async with get_session_factory()() as db:
            await db.execute(sa.update(User).where(User.id == user_id).values(is_admin=True))
            await db.commit()
        grant_id = await research_grant(user_id=other["id"],
                                        granted_by=user_id if mode == "grantor" else administrator["id"])
        if mode == "revoker":
            await revoke_research_grant(grant_id=grant_id, revoked_by=user_id)
        async with get_session_factory()() as db:
            await db.execute(sa.update(User).where(User.id == user_id).values(is_admin=False))
            await db.commit()


async def delete_account(client, user, token, *, via):
    if via == "self":
        return await client.request("DELETE", "/v1/auth/me", headers={"Authorization": f"Bearer {token}"},
            json={"confirmation": "DELETE", "email": user.email, "current_password": "correcthorsebatterystaple"})
    administrator = await research_user(is_admin=True)
    return await client.delete(f"/v1/admin/users/{user.id}", headers=administrator["headers"])


@pytest.mark.parametrize("mode", ["grantee", "revoked_grantee", "grantor", "revoker"])
@pytest.mark.parametrize("via", ["self", "admin"])
async def test_audit_identity_deletion_returns_409_without_side_effects(client, registered_user, mode, via):
    user, token = registered_user
    await private_rows(user.id)
    await reference_account(user.id, mode)
    before = await snapshot(user.id)
    response = await delete_account(client, user, token, via=via)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == RETENTION_MESSAGE
    assert response.json()["error_code"] == "conflict"
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert await snapshot(user.id) == before
    assert (await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 200


async def test_cookie_session_is_not_cleared_or_invalidated_by_audit_hold(client, registered_user):
    user, token = registered_user
    await private_rows(user.id)
    await reference_account(user.id, "grantee")
    before = await snapshot(user.id)
    settings = get_settings()
    cookie = build_browser_session_config(settings.environment, settings.jwt_expiry_hours * 3600)
    client.cookies.set(cookie.cookie_name, token)
    response = await client.request("DELETE", "/v1/auth/me", headers={"Origin": allowed_browser_origins(settings)[0]},
        json={"confirmation": "DELETE", "email": user.email, "current_password": "correcthorsebatterystaple"})
    assert response.status_code == 409, response.text
    assert "set-cookie" not in response.headers
    assert await snapshot(user.id) == before
    assert (await client.get("/v1/auth/me")).status_code == 200


async def test_lifecycle_review_identity_remains_after_reviewer_grant_revocation(client):
    from services.source_lifecycle import record_source_review
    from tests.test_source_lifecycle_service import prepared_review

    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            fixture = await prepared_review(db)
            await record_source_review(db, **fixture["review_args"], dry_run=False)
            await db.commit()
    finally:
        await engine.dispose()
    reviewer_id = fixture["actors"]["reviewer"]
    await revoke_research_grant(grant_id=fixture["actors"]["grants"]["reviewer"],
                               revoked_by=fixture["actors"]["admin"])
    await private_rows(reviewer_id)
    before = await snapshot(reviewer_id)
    reviews = Base.metadata.tables["source_lifecycle_reviews"]
    query = sa.select(sa.func.to_jsonb(reviews.table_valued())).where(reviews.c.reviewer_id == reviewer_id)
    async with get_session_factory()() as db:
        saved_reviews = (await db.execute(query)).scalars().all()
        assert len(saved_reviews) == 1
        assert await has_research_audit_references(db, reviewer_id) is True
    administrator = await research_user(is_admin=True)
    response = await client.delete(f"/v1/admin/users/{reviewer_id}", headers=administrator["headers"])
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == RETENTION_MESSAGE
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert await snapshot(reviewer_id) == before
    async with get_session_factory()() as db:
        assert (await db.execute(query)).scalars().all() == saved_reviews


@pytest.mark.parametrize("actor_kind", ["requester", "executor"])
async def test_source_task_actor_identity_is_retained_after_grant_revocation(client, actor_kind):
    from services.research_publication import grant_role
    from services.source_impact import inspect_source_impact
    from services.source_tasks import enqueue_source_task, execute_source_task
    from tests.test_research_publication import actors
    from tests.test_source_impact import observation

    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            people = await actors(db)
            executor_grant = await grant_role(db, actor_user_id=people["admin"], user_id=people["reviewer"],
                role="curator", reason_code="synthetic_task_executor", dry_run=False)
            _, event_args = await observation(db)
            inventory = await inspect_source_impact(db, **event_args)
            request = (await enqueue_source_task(db, actor_user_id=people["curator"], **event_args,
                expected_inventory_sha256=inventory["inventory_sha256"],
                request_key="synthetic-retained-task", dry_run=False))["request"]
            await execute_source_task(db, actor_user_id=people["reviewer"], request_id=request["id"],
                expected_request_sha256=request["record_sha256"], execution_key="synthetic-retained-attempt", dry_run=False)
            await db.commit()
    finally:
        await engine.dispose()
    identifier, grant_id = (people["curator"], people["grants"]["curator"]) if actor_kind == "requester" else (
        people["reviewer"], executor_grant["id"])
    await revoke_research_grant(grant_id=grant_id, revoked_by=people["admin"])
    await private_rows(identifier)
    before = await snapshot(identifier)
    table = Base.metadata.tables["source_task_requests" if actor_kind == "requester" else "source_task_attempts"]
    query = sa.select(sa.func.to_jsonb(table.table_valued())).where(table.c[f"{actor_kind}_id"] == identifier)
    async with get_session_factory()() as db:
        history = (await db.execute(query)).scalars().all()
        assert len(history) == 1
        assert await has_research_audit_references(db, identifier) is True
    administrator = await research_user(is_admin=True)
    response = await client.delete(f"/v1/admin/users/{identifier}", headers=administrator["headers"])
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == RETENTION_MESSAGE
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert await snapshot(identifier) == before
    async with get_session_factory()() as db:
        assert (await db.execute(query)).scalars().all() == history


@pytest.mark.parametrize("via", ["self", "admin"])
async def test_concurrent_grant_after_preflight_rolls_back_private_deletion(client, registered_user, monkeypatch, via):
    import routers.admin as admin_router
    import routers.auth as auth_router

    user, token = registered_user
    await private_rows(user.id)
    administrator = await research_user(is_admin=True)
    before = await snapshot(user.id)
    observed = []

    async def grant_after_preflight(db, identifier):
        assert identifier == user.id
        assert await has_research_audit_references(db, identifier) is False
        observed.append(await research_grant(user_id=user.id, granted_by=administrator["id"]))
        return False

    monkeypatch.setattr(auth_router if via == "self" else admin_router,
                        "has_research_audit_references", grant_after_preflight)
    response = await delete_account(client, user, token, via=via)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == RETENTION_MESSAGE
    assert len(observed) == 1
    assert "set-cookie" not in response.headers
    assert await snapshot(user.id) == before
    assert (await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    async with get_session_factory()() as db:
        assert await has_research_audit_references(db, user.id) is True


@pytest.mark.parametrize("via", ["self", "admin"])
async def test_unreferenced_account_deletion_still_cascades_private_rows(client, registered_user, via):
    user, token = registered_user
    await private_rows(user.id)
    response = await delete_account(client, user, token, via=via)
    assert response.status_code == 200, response.text
    assert all(not rows for rows in (await snapshot(user.id)).values())
    assert (await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


@pytest.mark.parametrize("via", ["self", "admin"])
async def test_unrelated_integrity_error_is_not_misreported_as_research_hold(client, registered_user, monkeypatch, via):
    user, token = registered_user
    await private_rows(user.id)
    administrator = await research_user(is_admin=True)
    before = await snapshot(user.id)
    original_commit = AsyncSession.commit
    failure = IntegrityError("synthetic unrelated constraint", {},
                             SimpleNamespace(sqlstate="23503", constraint_name="unrelated_fixture_fkey"))

    async def fail_on_account_delete(db):
        if any(isinstance(row, User) and row.id == user.id for row in db.deleted):
            raise failure
        return await original_commit(db)

    monkeypatch.setattr(AsyncSession, "commit", fail_on_account_delete)
    with pytest.raises(IntegrityError) as received:
        if via == "self":
            await delete_account(client, user, token, via="self")
        else:
            await client.delete(f"/v1/admin/users/{user.id}", headers=administrator["headers"])
    assert received.value is failure
    assert await snapshot(user.id) == before


async def test_preflight_is_read_only_and_covers_actual_user_foreign_keys(registered_user):
    user, _ = registered_user
    await reference_account(user.id, "grantee")
    engine = get_engine()
    statements = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        async with AsyncSession(engine) as db:
            await db.execute(sa.text("SET TRANSACTION READ ONLY"))
            assert await has_research_audit_references(db, user.id) is True
            assert await has_research_audit_references(db, uuid4()) is False
            actual = set((await db.execute(sa.text("""SELECT c.conname FROM pg_constraint c
                JOIN pg_class parent ON parent.oid=c.confrelid
                JOIN pg_class child ON child.oid=c.conrelid
                WHERE parent.relname='users' AND c.contype='f'
                  AND child.relname=ANY(:names)"""), {"names": list({name for name, _ in AUDIT_USER_REFERENCES})})).scalars())
            assert actual == AUDIT_USER_FK_CONSTRAINTS
        assert all(statement.lstrip().upper().startswith(("SELECT", "SET")) for statement in statements)
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)
        await engine.dispose()


@pytest.mark.parametrize("state,constraint,expected", [
    ("23503", "research_role_grants_user_id_fkey", True),
    ("23503", "source_lifecycle_reviews_reviewer_id_fkey", True),
    ("23503", "source_task_requests_requester_id_fkey", True),
    ("23503", "source_task_attempts_executor_id_fkey", True),
    ("23505", "source_task_requests_requester_id_fkey", False),
    ("23503", "source_task_requests_requester_grant_id_fkey", False),
    ("23503", "source_task_attempts_executor_grant_id_fkey", False),
    ("23505", "source_lifecycle_reviews_reviewer_id_fkey", False),
    ("23503", "source_lifecycle_reviews_reviewer_grant_id_fkey", False),
    ("23505", "research_role_grants_user_id_fkey", False),
    ("23503", "unrelated_private_fkey", False),
    (None, "research_role_grants_user_id_fkey", False),
])
def test_race_classifier_uses_exact_sqlstate_and_constraint_not_error_text(state, constraint, expected):
    original = Exception("research_role_grants_user_id_fkey SQLSTATE 23503 synthetic private data")
    original.sqlstate = state
    original.constraint_name = constraint
    wrapped = Exception("driver wrapper")
    wrapped.__cause__ = original
    error = IntegrityError("statement", {"private": "not inspected"}, wrapped)
    assert is_research_audit_reference_violation(error) is expected


def test_race_classifier_supports_psycopg_diagnostics_and_wrapper_cycles():
    original = Exception("synthetic psycopg")
    original.diag = SimpleNamespace(sqlstate="23503", constraint_name="research_publication_actions_actor_user_id_fkey")
    assert is_research_audit_reference_violation(IntegrityError("", {}, original)) is True
    cyclic = Exception("synthetic cycle without trusted diagnostics")
    cyclic.__cause__ = cyclic
    assert is_research_audit_reference_violation(IntegrityError("", {}, cyclic)) is False
