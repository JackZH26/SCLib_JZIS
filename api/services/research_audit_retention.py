"""Fail closed on account erasure that would destroy research audit identity.

This is a technical integrity hold, not a legal retention determination. A
reviewed retention or de-identification workflow is deliberately not invented
by the account-deletion endpoints.
"""
from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from models.db import Base

RETENTION_MESSAGE = (
    "This account is referenced by immutable research audit history. "
    "Deletion requires a reviewed retention or de-identification workflow."
)
AUDIT_USER_REFERENCES = (
    ("ml_use_role_decisions", "user_id"),
    ("ml_use_role_decisions", "actor_user_id"),
    ("research_role_grants", "user_id"),
    ("research_role_grants", "granted_by"),
    ("research_role_revocations", "revoked_by"),
    ("research_publication_permissions", "actor_user_id"),
    ("research_publication_proposals", "actor_user_id"),
    ("research_publication_reviews", "actor_user_id"),
    ("research_publication_actions", "actor_user_id"),
    ("source_lifecycle_reviews", "reviewer_id"),
    ("source_task_requests", "requester_id"),
    ("source_task_attempts", "executor_id"),
    ("research_distribution_packages", "actor_user_id"),
    ("research_distribution_permissions", "actor_user_id"),
    ("research_distribution_reviews", "actor_user_id"),
    ("research_distribution_actions", "actor_user_id"),
    ("scientific_import_packages", "actor_user_id"),
    ("scientific_import_attempts", "actor_user_id"),
    ("scientific_import_blobs", "actor_user_id"),
    ("scientific_import_outcomes", "actor_user_id"),
    ("scientific_adjudication_requests", "actor_user_id"),
    ("scientific_result_decisions", "actor_user_id"),
    ("discovery_projection_packages", "actor_user_id"),
    ("discovery_projection_reviews", "actor_user_id"),
    ("discovery_projection_actions", "actor_user_id"),
)
# PostgreSQL's exact names for the deliberately unnamed audit identity FKs.
# Restrict this classifier to these explicitly listed constraints and SQLSTATE 23503;
# unrelated integrity failures must retain their original error behavior.
AUDIT_USER_FK_CONSTRAINTS = frozenset(f"{table}_{column}_fkey" for table, column in AUDIT_USER_REFERENCES)


async def has_research_audit_references(db, user_id) -> bool:
    """Read-only preflight before any deletion audit, cascade, or session change."""
    identifier = UUID(str(user_id))
    checks = [sa.exists(sa.select(sa.literal(1)).select_from(Base.metadata.tables[name]).where(
        Base.metadata.tables[name].c[column] == identifier)) for name, column in AUDIT_USER_REFERENCES]
    with db.no_autoflush:
        return bool(await db.scalar(sa.select(sa.or_(*checks))))


def is_research_audit_reference_violation(error: IntegrityError) -> bool:
    """Recognize the final FK race guard through psycopg/asyncpg wrappers.

Never parse or expose exception messages, SQL parameters, or account data.
The wrapper chain is bounded and cycle safe.
"""
    pending, seen = [error.orig], set()
    for _ in range(12):
        if not pending:
            return False
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        diagnostic = getattr(current, "diag", None)
        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        constraint = getattr(current, "constraint_name", None)
        if diagnostic is not None:
            state = state or getattr(diagnostic, "sqlstate", None)
            constraint = constraint or getattr(diagnostic, "constraint_name", None)
        if state == "23503" and constraint in AUDIT_USER_FK_CONSTRAINTS:
            return True
        pending.extend((getattr(current, "__cause__", None), getattr(current, "__context__", None)))
    return False
