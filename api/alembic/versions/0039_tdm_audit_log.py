"""tdm_audit_log: APS TDM compliance / deletion audit trail

Revision ID: 0039_tdm_audit_log
Revises: 0038_aps_source_identity
Create date: 2026-05-31

Phase 1 of the APS ingestion build (see docs/APS_INGESTION_PLAN.md).

The APS agreement requires a processing audit log recording the DOI,
timestamps, and confirmation that the raw Licensed Materials (BagIt ZIP,
full-text XML, PDF, OCR) were deleted after TDM extraction. This table
is that record. One row per APS paper processed.

It is the ONLY place APS full-text processing leaves a permanent trace:
the licensed content itself is never persisted (no GCS upload, never
written to ``chunks.text``) — only authorized metadata/abstract and the
extracted structured data are kept, plus this audit row proving the raw
content was purged.

``deletion_confirmed`` is set True only after the pipeline re-checks the
temp path is gone (os.path.exists == False). ``status`` tracks the
lifecycle: 'pending' -> 'processed' -> 'deleted' (or 'error').
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0039_tdm_audit_log"
down_revision = "0038_aps_source_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tdm_audit_log",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.String(20), nullable=False, server_default="aps"),
        sa.Column("doi", sa.String(200), nullable=False),
        # Nullable + SET NULL: the audit row must survive even if the
        # paper row is later removed — the deletion proof is the point.
        sa.Column("paper_id", sa.String(100), nullable=True),
        sa.Column("harvested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bagit_bytes", sa.BigInteger(), nullable=True),
        # List of licensed files that passed through the temp dir
        # (full-text XML, PDF, OCR) — names/sizes only, never content.
        sa.Column(
            "files_processed", JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "ner_record_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deletion_confirmed", sa.Boolean(), nullable=False,
            server_default="false",
        ),
        sa.Column("temp_path", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="SET NULL",
        ),
    )
    op.create_index("idx_tdm_audit_doi", "tdm_audit_log", ["doi"])
    op.create_index("idx_tdm_audit_status", "tdm_audit_log", ["status"])
    op.create_index("idx_tdm_audit_created", "tdm_audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_tdm_audit_created", table_name="tdm_audit_log")
    op.drop_index("idx_tdm_audit_status", table_name="tdm_audit_log")
    op.drop_index("idx_tdm_audit_doi", table_name="tdm_audit_log")
    op.drop_table("tdm_audit_log")
