"""Guarded ML07 live-read budgets, minimal identity reads and sanitized failures.

All catalogue expansions are disposable synthetic rows. Query spies reject an
unsafe body request before execution rather than measuring driver memory after
the sensitive/oversized field has already arrived.
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from models.db import Base
from routers import research_publications as router
from services import research_access as access
from services import research_publication as publication
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_research_publication import actors, prepared, proposed, published

db_session = _serializable_db_session
_MIB = 1024 * 1024
_SECRET = "postgresql://private-user:DO-NOT-EMIT@private-host/private-db"


def spy_queries(monkeypatch, db, *, material_preflight_only=False, no_full_material=False):
    execute = db.execute
    queries = []

    async def capture(statement, *args, **kwargs):
        sql = str(statement)
        queries.append(sql)
        if "FROM materials" in sql:
            if material_preflight_only and "octet_length" not in sql:
                pytest.fail("A material body was requested before the live expanded-byte limit failed")
            if no_full_material and "octet_length" not in sql and "SELECT materials.records" not in sql:
                pytest.fail("A full material was requested before the record inventory limit failed")
        return await execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", capture)
    return queries


async def test_active_user_reads_only_four_flags_even_with_large_private_profile(db_session, monkeypatch):
    people = await actors(db_session)
    users = Base.metadata.tables["users"]
    await db_session.execute(users.update().where(users.c.id == people["reviewer"]).values(
        profile={"private": "x" * (4 * _MIB)}, bio=_SECRET, purpose=_SECRET, scopes=[_SECRET]))
    with monkeypatch.context() as patch:
        queries = spy_queries(patch, db_session)
        user = await access.active_user(db_session, people["reviewer"])
    assert set(user) == {"id", "is_active", "email_verified", "is_admin"}
    assert len(queries) == 1
    for forbidden in ("users.profile", "users.scopes", "users.bio", "users.purpose", "users.password_hash"):
        assert forbidden not in queries[0]


async def test_thousand_exact_grant_requests_are_validated_in_one_minimal_query(db_session, monkeypatch):
    people = await actors(db_session)
    requested = [(people[role], people["grants"][role], role) for role in ("curator", "reviewer", "publisher")]
    requested = requested * 333 + requested[:1]
    assert len(requested) == 1000
    with monkeypatch.context() as patch:
        queries = spy_queries(patch, db_session)
        await access.check_grant_inventory(db_session, requested)
    assert len(queries) == 1
    assert "JOIN users" in queries[0] and "research_role_revocations" in queries[0]
    assert "users.profile" not in queries[0] and "users.password_hash" not in queries[0]


async def test_oversized_distinct_grant_inventory_fails_before_query(db_session, monkeypatch):
    requested = [(uuid4(), uuid4(), "reviewer") for _ in range(1001)]
    with monkeypatch.context() as patch:
        queries = spy_queries(patch, db_session)
        with pytest.raises(access.ResearchAccessDenied, match="inventory limit"):
            await access.check_grant_inventory(db_session, requested)
    assert queries == []


async def test_whole_capsule_permission_recheck_has_constant_two_query_cost(db_session, monkeypatch):
    context = await prepared(db_session)
    release = {**context["release"], "id": UUID(context["release"]["release_id"])}
    with monkeypatch.context() as patch:
        queries = spy_queries(patch, db_session)
        receipts = await publication._permissions(db_session, release)
    assert len(receipts) == len(context["release"]["manifest"]["rows"]) > 10
    assert len(queries) == 2
    assert all("users.profile" not in sql and "users.password_hash" not in sql for sql in queries)


@pytest.mark.parametrize("change", ["revoked", "inactive", "unverified", "wrong_actor", "wrong_role"])
async def test_batched_grants_still_check_live_exact_authority(db_session, change):
    people = await actors(db_session)
    requested = [(people["reviewer"], people["grants"]["reviewer"], "reviewer")]
    if change == "revoked":
        await publication.revoke_role(db_session, actor_user_id=people["admin"],
            grant_id=people["grants"]["reviewer"], reason_code="synthetic_revocation", dry_run=False)
    elif change in {"inactive", "unverified"}:
        users = Base.metadata.tables["users"]
        await db_session.execute(users.update().where(users.c.id == people["reviewer"]).values(
            **{"is_active" if change == "inactive" else "email_verified": False}))
    elif change == "wrong_actor":
        requested = [(people["member"], people["grants"]["reviewer"], "reviewer")]
    else:
        requested = [(people["reviewer"], people["grants"]["reviewer"], "publisher")]
    with pytest.raises(access.ResearchAccessDenied, match="unavailable"):
        await access.check_grant_inventory(db_session, requested)


@pytest.mark.parametrize("target", ["self", "ancestor", "aggregate"])
async def test_expanded_live_catalogue_bytes_rejected_before_any_body(db_session, monkeypatch, target):
    context = await prepared(db_session)
    material_id = context["fixture"]["material"]
    materials = Base.metadata.tables["materials"]
    if target == "self":
        await db_session.execute(materials.update().where(materials.c.id == material_id).values(
            anomaly_context={"private_padding": "x" * (4 * _MIB)}))
    else:
        parent = f"publication-parent:{uuid4().hex}"
        await add(db_session, "materials", id=parent, formula="MgB2", formula_normalized="MgB2",
            records=[], total_papers=1, needs_review=False,
            anomaly_context={"private_padding": "x" * ((4 if target == "ancestor" else 2) * _MIB)})
        await db_session.execute(materials.update().where(materials.c.id == material_id).values(
            parent_material_id=parent,
            **({"anomaly_context": {"private_padding": "y" * (2 * _MIB)}} if target == "aggregate" else {})))
    with monkeypatch.context() as patch:
        queries = spy_queries(patch, db_session, material_preflight_only=True)
        with pytest.raises(publication.PublicationUnavailable, match="governance byte budget"):
            await publication._current_catalogue(db_session, context["release"])
    assert queries and all("octet_length" in sql for sql in queries)
    if target in {"ancestor", "aggregate"}:
        assert len(queries) == 2


async def test_live_record_inventory_is_bounded_before_adapter_or_full_row(db_session, monkeypatch):
    context = await prepared(db_session)
    materials = Base.metadata.tables["materials"]
    await db_session.execute(materials.update().where(materials.c.id == context["fixture"]["material"]).values(
        records=[{}] * 5001))
    with monkeypatch.context() as patch:
        queries = spy_queries(patch, db_session, no_full_material=True)
        with pytest.raises(publication.PublicationUnavailable, match="record inventory"):
            await publication._current_catalogue(db_session, context["release"])
    assert len(queries) == 2 and "octet_length" in queries[0] and "SELECT materials.records" in queries[1]


async def test_live_ancestry_row_inventory_rejects_before_material_body(db_session, monkeypatch):
    materials = Base.metadata.tables["materials"]
    prefix = f"publication-inventory:{uuid4().hex}:"
    values = [{"id": prefix + str(index), "formula": "MgB2", "formula_normalized": "MgB2", "records": []}
              for index in range(1001)]
    await db_session.execute(materials.insert(), values)
    # This helper adversary exceeds valid capsule size deliberately. It never
    # creates an actual release or bypasses a release trigger.
    release = {"manifest": {"rows": [{"table": "materials", "row_id": item["id"]} for item in values]}}
    with monkeypatch.context() as patch:
        queries = spy_queries(patch, db_session, material_preflight_only=True)
        with pytest.raises(publication.PublicationUnavailable, match="ancestry inventory"):
            await publication._current_catalogue(db_session, release)
    assert len(queries) == 1


async def test_deep_live_ancestors_rejected_before_body_read(db_session, monkeypatch):
    materials = Base.metadata.tables["materials"]
    prefix = f"publication-depth:{uuid4().hex}:"
    values = [{"id": prefix + str(index), "formula": "MgB2", "formula_normalized": "MgB2", "records": [],
               "parent_material_id": prefix + str(index + 1) if index < 33 else None}
              for index in range(34)]
    # executemany enforces each parent FK immediately, so seed parent-first.
    await db_session.execute(materials.insert(), list(reversed(values)))
    release = {"manifest": {"rows": [{"table": "materials", "row_id": values[0]["id"]}]}}
    with monkeypatch.context() as patch:
        queries = spy_queries(patch, db_session, material_preflight_only=True)
        with pytest.raises(publication.PublicationUnavailable, match="ancestry depth"):
            await publication._current_catalogue(db_session, release)
    assert len(queries) == 33


async def test_unpublished_direct_id_rejects_before_costly_proposal_reads(db_session, monkeypatch):
    context = await proposed(db_session)

    async def forbidden(*_args, **_kwargs):
        pytest.fail("Unpublished ID reached expensive capsule admission")

    monkeypatch.setattr(publication, "_proposal", forbidden)
    with pytest.raises(publication.PublicationUnavailable, match="unavailable"):
        await publication.admitted_publication(db_session, context["proposal"]["id"])


async def test_more_than_scan_limit_drafts_do_not_disable_published_inventory(db_session, monkeypatch):
    context = await published(db_session)
    proposal = await publication._get(db_session, "research_publication_proposals", context["proposal"]["id"])
    values = {key: value for key, value in proposal.items() if key not in {"id", "created_at", "record_sha256"}}
    original = publication.admitted_publication
    read = []

    async def tracked(db, identifier):
        read.append(identifier)
        return await original(db, identifier)

    monkeypatch.setattr(publication, "admitted_publication", tracked)
    baseline = await publication.public_inventory(db_session)
    prior_candidates = list(read)
    draft_ids = set()
    for _ in range(publication.MAX_PROPOSAL_SCAN + 1):
        draft = await publication._insert(db_session, "research_publication_proposals", values)
        draft_ids.add(draft["id"])
    read.clear()
    inventory = await publication.public_inventory(db_session)
    # Other HTTP tests legitimately commit immutable publication history.
    # Draft insertion must not change either inventory or admission work.
    assert inventory == baseline and read == prior_candidates
    assert draft_ids.isdisjoint(read)
    assert context["proposal"]["id"] in {item["id"] for item in inventory["items"]}


async def test_public_read_session_has_its_own_repeatable_read_readonly_snapshot():
    generator = router.publication_read_session()
    db = await anext(generator)
    try:
        assert (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() == "repeatable read"
        assert (await db.execute(sa.text("SHOW transaction_read_only"))).scalar_one() == "on"
        assert (await db.execute(sa.text("SHOW statement_timeout"))).scalar_one() == "5s"
    finally:
        await generator.aclose()


@pytest.mark.parametrize("failure", ["database", "timeout"])
async def test_read_dependency_failures_are_sanitized_and_no_store(monkeypatch, failure):
    if failure == "database":
        def broken_engine():
            raise SQLAlchemyError(_SECRET)
        monkeypatch.setattr(router, "get_engine", broken_engine)
    else:
        class Deadline:
            async def __aenter__(self):
                raise TimeoutError(_SECRET)

            async def __aexit__(self, *_args):
                return False

        def expired(seconds):
            assert seconds == 10
            return Deadline()
        monkeypatch.setattr(router.asyncio, "timeout", expired)
    with pytest.raises(HTTPException) as captured:
        await anext(router.publication_read_session())
    assert captured.value.status_code == 503
    assert captured.value.detail == "Publication registry unavailable"
    assert captured.value.headers["Cache-Control"] == "private, no-store"
    assert _SECRET not in str(captured.value)


async def test_public_http_session_connection_error_is_sanitized(client, monkeypatch):
    def broken_engine():
        raise SQLAlchemyError(_SECRET)
    monkeypatch.setattr(router, "get_engine", broken_engine)
    response = await client.get("/v1/ml/releases")
    assert response.status_code == 503
    assert response.json()["detail"] == "Publication registry unavailable"
    assert response.json()["error_code"] == "service_unavailable"
    assert set(response.json()) == {"detail", "error_code", "request_id"}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert _SECRET not in response.text


async def test_request_deadline_covers_work_after_dependency_yield(client, monkeypatch):
    original_timeout = asyncio.timeout
    started = False
    deadlines = []

    def short_deadline(seconds):
        assert seconds == 10
        # Arm the test deadline at the target body, not during a variable-cost
        # native connection/schema read. This specifically proves cancellation
        # remains covered after dependency yield, even on a busy test host.
        deadline = original_timeout(None)
        deadlines.append(deadline)
        return deadline

    async def never_finishes(_db):
        nonlocal started
        started = True
        assert len(deadlines) == 1
        deadlines[0].reschedule(asyncio.get_running_loop().time() + 0.05)
        await asyncio.Event().wait()

    monkeypatch.setattr(router.asyncio, "timeout", short_deadline)
    monkeypatch.setattr(router, "public_inventory", never_finishes)
    response = await asyncio.wait_for(client.get("/v1/ml/releases"), timeout=5)
    assert started and response.status_code == 503
    assert response.json()["detail"] == "Publication registry unavailable"
    assert response.json()["error_code"] == "service_unavailable"
    assert set(response.json()) == {"detail", "error_code", "request_id"}
    assert response.headers["Cache-Control"] == "private, no-store"
