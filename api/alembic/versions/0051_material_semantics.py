"""Separate reported material properties from inferred priors and missingness.

Revision ID: 0051_material_semantics
Revises: 0050_timeline_identity

Adds rebuildable metadata and enforces an unknown future INSERT default.
Migration 0004 already removed the database default; this also protects drifted
schemas. Historical false flags, inferred summaries, disputed holds and raw
records are untouched.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0051_material_semantics"
down_revision = "0050_timeline_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("materials", sa.Column(
        "material_semantics", postgresql.JSONB(), nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ))
    op.alter_column("materials", "has_competing_order", existing_type=sa.Boolean(),
                    existing_nullable=True, server_default=None)


def downgrade():
    # Only this rebuildable projection is dropped. Existing unknown NULLs must
    # remain NULL. Migration 0004 already removed the database default; only
    # the hand-maintained ORM/writer schemas had drifted back to false.
    op.drop_column("materials", "material_semantics")
    op.alter_column("materials", "has_competing_order", existing_type=sa.Boolean(),
                    existing_nullable=True, server_default=None)
