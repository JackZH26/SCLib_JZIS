"""Audit infrastructure — reports table, admin_decision col, jack→admin.

Revision ID: 0022_audit_infra
Down revision: 0021_gemini_audit_flags

Three independent additions, packaged together because they're the
day-1 scaffold for the nightly data-audit + admin review workflow:

* ``audit_reports`` — one row per (rule, run). Lets the nightly job
  record how many materials a rule flagged today, sample ids, and
  the delta vs yesterday so admins can spot regressions.
* ``materials.admin_decision`` JSONB — when an admin overrides a flag
  (decides the row is fine after review), the nightly job sees this
  and skips re-flagging. Without it, a re-run would just keep
  flipping the same rows and admin work would never persist.
* ``users.is_admin = TRUE`` for ``jack@jzis.org`` — bootstraps the
  first admin so the new ``/admin/*`` routes have a caller.
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_audit_infra"
down_revision = "0021_gemini_audit_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_reports",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_name", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("rows_flagged", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delta_vs_previous", sa.Integer, nullable=True),
        sa.Column("sample_ids", sa.dialects.postgresql.JSONB,
                  server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.create_index(
        "idx_audit_reports_started", "audit_reports", ["started_at"],
    )
    op.create_index(
        "idx_audit_reports_rule_started",
        "audit_reports", ["rule_name", "started_at"],
    )

    # Admin-decision channel: when an admin reviews a flagged material
    # and decides "actually this is fine", we store the decision here
    # so subsequent nightly runs know to skip re-flagging the row.
    op.add_column(
        "materials",
        sa.Column(
            "admin_decision", sa.dialects.postgresql.JSONB,
            nullable=True,
        ),
    )

    # Bootstrap the first admin. The user must have already registered
    # via /auth/register or Google OAuth — we just flip the flag. If
    # the user doesn't exist yet, the UPDATE is a 0-row no-op and the
    # admin can be set later by a manual SQL or by re-running this
    # migration's downgrade+upgrade after the user signs up.
    op.execute("""
        UPDATE users SET is_admin = TRUE
        WHERE email = 'jack@jzis.org';
    """)


def downgrade() -> None:
    op.execute("UPDATE users SET is_admin = FALSE WHERE email = 'jack@jzis.org';")
    op.drop_column("materials", "admin_decision")
    op.drop_index("idx_audit_reports_rule_started", table_name="audit_reports")
    op.drop_index("idx_audit_reports_started", table_name="audit_reports")
    op.drop_table("audit_reports")
