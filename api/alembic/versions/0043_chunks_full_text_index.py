"""Add an online PostgreSQL full-text index for hybrid retrieval.

Revision ID: 0043_chunks_fts
Revises: 0042_auth_security
"""
from __future__ import annotations

from alembic import op

revision = "0043_chunks_fts"
down_revision = "0042_auth_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY keeps reads and ingestion writes available while the index
    # is built on an existing corpus. Alembic's autocommit block is required
    # because PostgreSQL forbids concurrent index builds inside a transaction.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_full_text
            ON chunks USING gin (
                to_tsvector('english', coalesce(title, '') || ' ' || text)
            )
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_chunks_full_text")
