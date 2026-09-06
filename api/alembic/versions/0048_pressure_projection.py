"""Version pressure semantics on the rebuildable Timeline projection.

Revision ID: 0048_pressure_projection
Revises: 0047_claim_integrity

Adds derived read fields only. No source scientific record is rewritten.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0048_pressure_projection"
down_revision = "0047_claim_integrity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("timeline_projection_points", sa.Column(
        "pressure_semantics", postgresql.JSONB(), nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ))
    op.add_column("timeline_projection_state", sa.Column(
        "pressure_policy_version", sa.String(80), nullable=False,
        server_default="legacy/unclassified",
    ))
    op.execute("UPDATE timeline_projection_state SET schema_version = 0")


def downgrade():
    op.execute("UPDATE timeline_projection_state SET schema_version = 0")
    op.drop_column("timeline_projection_state", "pressure_policy_version")
    op.drop_column("timeline_projection_points", "pressure_semantics")
