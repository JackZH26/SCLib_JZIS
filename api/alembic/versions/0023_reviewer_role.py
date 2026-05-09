"""Add is_reviewer column to users.

Revision ID: 0023_reviewer_role
Revises: 0022_audit_infra
Create Date: 2026-05-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0023_reviewer_role"
down_revision = "0022_audit_infra"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_reviewer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_reviewer")
