"""Explicit research-operator fixtures; never an application-wide auth override.

Only suites that explicitly alias ``research_operator_client`` opt into a real
verified user, administrator-issued research grant and signed JWT. The default
client remains anonymous so access-control regressions cannot be hidden.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from main import app
from models.db import Base, User, get_engine, get_session_factory
from services import auth_service
from services.research_release_manifest import digest


async def research_user(**changes) -> dict:
    """Create a synthetic account without registration or role side effects."""
    user_id = uuid4()
    values = {
        "id": user_id,
        "email": f"research-access-{user_id.hex}@example.test",
        "name": "Synthetic Research Operator",
        "is_active": True,
        "email_verified": True,
        **changes,
    }
    async with get_session_factory()() as db:
        db.add(User(**values))
        await db.commit()
    token, _ = auth_service.create_access_token(user_id)
    return {"id": user_id, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


async def research_grant(*, user_id: UUID, granted_by: UUID, role: str = "curator") -> UUID:
    payload = {
        "user_id": str(user_id),
        "role": role,
        "granted_by": str(granted_by),
        "reason_code": "synthetic_access_test",
    }
    grant_id = uuid4()
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine) as db:
            table = Base.metadata.tables["research_role_grants"]
            await db.execute(table.insert().values(
                id=grant_id, user_id=user_id, role=role, granted_by=granted_by,
                reason_code=payload["reason_code"], record_sha256=digest(payload),
            ))
            await db.commit()
    finally:
        await engine.dispose()
    return grant_id


async def revoke_research_grant(*, grant_id: UUID, revoked_by: UUID) -> UUID:
    payload = {
        "grant_id": str(grant_id),
        "revoked_by": str(revoked_by),
        "reason_code": "synthetic_access_revocation",
    }
    revocation_id = uuid4()
    engine = get_engine().execution_options(isolation_level="SERIALIZABLE")
    try:
        async with AsyncSession(engine) as db:
            table = Base.metadata.tables["research_role_revocations"]
            await db.execute(table.insert().values(
                id=revocation_id, grant_id=grant_id, revoked_by=revoked_by,
                reason_code=payload["reason_code"], record_sha256=digest(payload),
            ))
            await db.commit()
    finally:
        await engine.dispose()
    return revocation_id


async def research_operator(*, role: str = "curator") -> dict:
    grantor = await research_user(is_admin=True)
    operator = await research_user()
    grant_id = await research_grant(user_id=operator["id"], granted_by=grantor["id"], role=role)
    return {**operator, "grantor_id": grantor["id"], "grant_id": grant_id}


@pytest_asyncio.fixture
async def research_operator_client():
    operator = await research_operator()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=operator["headers"]) as client:
        yield client
