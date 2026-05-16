"""Add suggested_fix + suggested_fixes columns to audit_reports.

Revision ID: 0030_audit_suggested_fixes
Down revision: 0029_evidence_tier

P1c D1: Store per-rule fix guidance (suggested_fix text) and per-row
fix proposals (suggested_fixes JSONB array) so the admin queue can
show concrete remediation steps alongside flagged materials.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0030_audit_suggested_fixes"
down_revision = "0029_evidence_tier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_reports",
        sa.Column("suggested_fix", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_reports",
        sa.Column(
            "suggested_fixes",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("audit_reports", "suggested_fixes")
    op.drop_column("audit_reports", "suggested_fix")
