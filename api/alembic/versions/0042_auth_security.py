"""Add authentication audit, password reset, and JWT session revocation.

Revision ID: 0042_auth_security
Revises: 0041_timeline_projection
Create date: 2026-07-13

This migration is additive. Existing JWTs remain valid because their missing
session-version claim is treated as zero, matching the new column default.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0042_auth_security"
down_revision = "0041_timeline_projection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_password_reset_user_created",
        "password_reset_tokens",
        ["user_id", "created_at"],
    )
    op.create_index("idx_password_reset_expires", "password_reset_tokens", ["expires_at"])

    op.create_table(
        "auth_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_hash", sa.String(64), nullable=True),
        sa.Column("client_ip_hash", sa.String(64), nullable=False),
        sa.Column("user_agent_hash", sa.String(64), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_auth_audit_created", "auth_audit_events", ["created_at"])
    op.create_index(
        "idx_auth_audit_user_created",
        "auth_audit_events",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_auth_audit_account_created",
        "auth_audit_events",
        ["account_hash", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_auth_audit_account_created", table_name="auth_audit_events")
    op.drop_index("idx_auth_audit_user_created", table_name="auth_audit_events")
    op.drop_index("idx_auth_audit_created", table_name="auth_audit_events")
    op.drop_table("auth_audit_events")
    op.drop_index("idx_password_reset_expires", table_name="password_reset_tokens")
    op.drop_index("idx_password_reset_user_created", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "session_version")
