"""Live research-role admission; legacy admin/reviewer flags are not grants.

Actor IDs passed to internal services must come from an authenticated trusted
caller. No role, permission or publication is inferred from request JSON.
"""
from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa

from models.db import Base
from services.research_release_manifest import digest


class ResearchAccessDenied(ValueError):
    """The current user lacks an explicit active research capability."""


def table(name):
    return Base.metadata.tables[name]


async def active_user(db, user_id):
    users = table("users")
    user = (await db.execute(sa.select(users.c.id, users.c.is_active, users.c.email_verified,
        users.c.is_admin).where(users.c.id == UUID(str(user_id))))).mappings().one_or_none()
    if user is None or not user["is_active"] or not user["email_verified"]:
        raise ResearchAccessDenied("An active verified research operator is required")
    return user


async def require_research_admin(db, user_id):
    user = await active_user(db, user_id)
    if not user["is_admin"]:
        raise ResearchAccessDenied("Research role administration requires an administrator")
    return user


async def active_grant(db, user_id, *, role=None, grant_id=None):
    await active_user(db, user_id)
    grants, revoked = table("research_role_grants"), table("research_role_revocations")
    query = sa.select(grants).where(grants.c.user_id == UUID(str(user_id)),
        ~sa.exists(sa.select(revoked.c.id).where(revoked.c.grant_id == grants.c.id)))
    if role is not None:
        query = query.where(grants.c.role == role)
    if grant_id is not None:
        query = query.where(grants.c.id == UUID(str(grant_id)))
    grant = (await db.execute(query.order_by(grants.c.id).limit(1))).mappings().one_or_none()
    if grant is None:
        raise ResearchAccessDenied("An explicit active research role grant is required")
    body = {str(key): str(value) if isinstance(value, UUID) else value for key, value in grant.items()
            if key not in {"id", "created_at", "record_sha256"}}
    if digest(body) != grant["record_sha256"]:
        raise ResearchAccessDenied("Research role audit binding is invalid")
    return grant


async def require_research_operator(db, user_id):
    await active_grant(db, user_id)


async def check_grant_inventory(db, requested):
    """Check a bounded set of exact (user, grant, role) bindings in one query."""
    expected = {(UUID(str(user)), UUID(str(grant)), role) for user, grant, role in requested}
    if len(expected) > 1000:
        raise ResearchAccessDenied("Research grant inventory limit exceeded")
    if not expected:
        return
    grants, users, revoked = table("research_role_grants"), table("users"), table("research_role_revocations")
    rows = (await db.execute(sa.select(grants).join(users, users.c.id == grants.c.user_id).where(
        grants.c.id.in_({grant for _, grant, _ in expected}), users.c.is_active.is_(True),
        users.c.email_verified.is_(True),
        ~sa.exists(sa.select(revoked.c.id).where(revoked.c.grant_id == grants.c.id))))).mappings().all()
    found = set()
    for row in rows:
        body = {str(key): str(value) if isinstance(value, UUID) else value for key, value in row.items()
                if key not in {"id", "created_at", "record_sha256"}}
        if digest(body) != row["record_sha256"]:
            raise ResearchAccessDenied("Research grant audit binding is invalid")
        found.add((row["user_id"], row["id"], row["role"]))
    if found != expected:
        raise ResearchAccessDenied("A current explicit research grant is unavailable")
