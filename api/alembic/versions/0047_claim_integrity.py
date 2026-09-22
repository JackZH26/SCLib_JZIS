"""Fail closed on inconsistent accepted claims and cross-material ML targets.

Revision ID: 0047_claim_integrity
Revises: 0046_result_origin

No scientific values are rewritten. Incompatible rows block the transaction;
operators must review the preflight report before attempting a later migration.
"""
from __future__ import annotations

import json
import logging

import sqlalchemy as sa

from alembic import op
from models.claim_integrity import (
    NEW_CHECKS,
    TARGET_FOREIGN_KEY,
    TARGET_UNIQUE,
    audit_incompatible_rows,
)

revision = "0047_claim_integrity"
down_revision = "0046_result_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # All writers to these tables are excluded during audit + constraint install.
    # A bounded lock wait fails the whole migration instead of silently racing.
    connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(sa.text(
        "LOCK TABLE event_properties, material_claims, material_states, ml_examples "
        "IN SHARE ROW EXCLUSIVE MODE"
    ))
    report = audit_incompatible_rows(connection)
    logging.getLogger("alembic.runtime.migration").info(
        "0047 integrity preflight: %s", json.dumps(report, sort_keys=True),
    )
    if not report["compatible"]:
        raise RuntimeError(
            "0047 integrity preflight failed; no values were repaired. "
            "Review reason-coded row IDs and resolve through provenance-backed curation."
        )
    for name, expression in NEW_CHECKS.items():
        op.create_check_constraint(name, "material_claims", expression)
    op.create_unique_constraint(TARGET_UNIQUE, "material_claims", ["id", "material_id"])
    op.create_foreign_key(
        TARGET_FOREIGN_KEY, "ml_examples", "material_claims",
        ["claim_id", "material_id"], ["id", "material_id"],
        ondelete="RESTRICT", onupdate="RESTRICT", match="FULL",
    )


def downgrade() -> None:
    # Compatibility rollback removes only new constraints; never repairs/deletes data.
    op.drop_constraint(TARGET_FOREIGN_KEY, "ml_examples", type_="foreignkey")
    op.drop_constraint(TARGET_UNIQUE, "material_claims", type_="unique")
    for name in reversed(NEW_CHECKS):
        op.drop_constraint(name, "material_claims", type_="check")
