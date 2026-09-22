"""Carry explicit result origin on the rebuildable Timeline read projection.

Revision ID: 0046_result_origin
Revises: 0045_research_shadow

No original scientific records are changed. Old Boolean-only projections are
invalidated; the versioned JSONB fallback serves until a new refresh completes.
"""
import sqlalchemy as sa

from alembic import op

revision = "0046_result_origin"
down_revision = "0045_research_shadow"
branch_labels = None
depends_on = None


def upgrade():
    for name, length, default in (
        ("knowledge_origin", 20, "Unknown"),
        ("classification_status", 20, "unknown"),
        ("source_role", 20, "unknown"),
        ("classifier_version", 80, "legacy/unclassified"),
    ):
        op.add_column("timeline_projection_points", sa.Column(
            name, sa.String(length), nullable=False, server_default=default,
        ))
    op.add_column("timeline_projection_state", sa.Column(
        "classifier_version", sa.String(80), nullable=False, server_default="legacy/unclassified",
    ))
    op.execute("UPDATE timeline_projection_state SET schema_version = 0")


def downgrade():
    # Only disposable/read-model rollback: no source result is removed.
    op.execute("UPDATE timeline_projection_state SET schema_version = 0")
    op.drop_column("timeline_projection_state", "classifier_version")
    for name in ("classifier_version", "source_role", "classification_status", "knowledge_origin"):
        op.drop_column("timeline_projection_points", name)
