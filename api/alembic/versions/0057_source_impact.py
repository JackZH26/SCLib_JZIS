"""Add exact-source reverse indexes for bounded read-only impact inspection.

Revision ID: 0057_source_impact
Revises: 0056_source_lifecycle

Index-only, with no row rewrite, backfill, worker or source-event acknowledgement.
Ordinary transactional CREATE INDEX deliberately shares the serialized migration
transaction. Staging must measure table size, disk headroom and write-lock time
before deployment; this is not a concurrent-index production rollout recipe.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op
from models.source_impact_indexes_v1 import register

revision = "0057_source_impact"
down_revision = "0056_source_lifecycle"
branch_labels = None
depends_on = None


def _indexes():
    # Minimal local parents keep this migration independent of future ORM
    # columns and frozen 0052-0056 schema/hash contracts.
    metadata = sa.MetaData()
    sa.Table("materials", metadata, sa.Column("records", JSONB))
    sa.Table("timeline_projection_points", metadata,
             sa.Column("paper_id", sa.String(100)), sa.Column("material_id", sa.String(100)))
    sa.Table("ml_examples", metadata, sa.Column("claim_id", UUID),
             sa.Column("work_id", UUID), sa.Column("material_id", sa.String(100)))
    return register(metadata)


def upgrade():
    for index in _indexes().values():
        index.create(op.get_bind())


def downgrade():
    # Removing only rebuildable indexes is safe even with immutable lifecycle
    # history. Older migrations retain their independent nonempty guards.
    for index in reversed(tuple(_indexes().values())):
        index.drop(op.get_bind())
