"""Add ingest_runs table for scheduled ingestion observability.

Revision ID: 0004_ingest_runs
Down revision: 0003_unified_auth

The hourly systemd-triggered ingest (scripts/sclib-hourly-ingest.sh)
writes one row per run. The ingestion pipeline itself inserts the row
(status='running') at startup and updates it at finish — this way a
crashed process leaves behind a row we can see, rather than a silent gap.
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_ingest_runs"
down_revision = "0003_unified_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("papers_processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("papers_succeeded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("papers_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("host", sa.String(100), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name="ingest_runs_status_chk",
        ),
    )
    op.create_index(
        "idx_ingest_runs_started_at",
        "ingest_runs",
        [sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_ingest_runs_started_at", table_name="ingest_runs")
    op.drop_table("ingest_runs")
