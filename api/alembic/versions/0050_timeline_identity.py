"""Version result identity and date provenance in the Timeline projection.

Revision ID: 0050_timeline_identity
Revises: 0049_anomaly_review

Only rebuildable derived metadata is added. No source record, result approval,
or scientific correction is created or changed by this migration.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0050_timeline_identity"
down_revision = "0049_anomaly_review"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("timeline_projection_points", sa.Column(
        "result_metadata", postgresql.JSONB(), nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ))
    # Old numerical-bucket identities must not be read as occurrence IDs.
    op.execute("UPDATE timeline_projection_state SET schema_version = 0")


def downgrade():
    # Recompute before either version reads points written by the other.
    op.execute("UPDATE timeline_projection_state SET schema_version = 0")
    op.drop_column("timeline_projection_points", "result_metadata")
