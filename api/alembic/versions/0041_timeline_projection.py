"""Add an incremental, read-optimized Timeline projection.

Revision ID: 0041_timeline_projection
Revises: 0040_hydride_tc_parameters
Create date: 2026-07-13

The projection is additive: ``materials.records`` remains authoritative and
is never deleted or rewritten by this migration. The tables start empty so
the API can deploy safely and continue using its legacy query until the
background refresher atomically marks the projection ready.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0041_timeline_projection"
down_revision = "0040_hydride_tc_parameters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "timeline_projection_points",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("material_id", sa.String(100), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("tc_kelvin", sa.Float(), nullable=False),
        sa.Column("pressure_gpa", sa.Float(), nullable=True),
        sa.Column("paper_id", sa.String(100), nullable=True),
        sa.Column(
            "is_theoretical", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("is_aps", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "year >= 1900 AND year <= 2200",
            name="ck_timeline_projection_year",
        ),
        sa.CheckConstraint(
            "tc_kelvin > 0 AND tc_kelvin <= 300",
            name="ck_timeline_projection_tc",
        ),
    )
    op.create_index(
        "idx_timeline_projection_active_year",
        "timeline_projection_points",
        ["year"],
        postgresql_where=sa.text("active IS TRUE"),
    )
    op.create_index(
        "idx_timeline_projection_material_active",
        "timeline_projection_points",
        ["material_id"],
        postgresql_where=sa.text("active IS TRUE"),
    )
    op.create_index(
        "idx_timeline_projection_aps_active",
        "timeline_projection_points",
        ["is_aps"],
        postgresql_where=sa.text("active IS TRUE"),
    )
    op.create_index(
        "idx_timeline_projection_theory_active",
        "timeline_projection_points",
        ["is_theoretical"],
        postgresql_where=sa.text("active IS TRUE"),
    )

    op.create_table(
        "timeline_projection_state",
        sa.Column(
            "id", sa.SmallInteger(), primary_key=True, autoincrement=False
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("source_year", sa.SmallInteger(), nullable=False),
        sa.Column("source_watermark", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("material_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "active_point_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.CheckConstraint(
            "id = 1", name="ck_timeline_projection_state_singleton"
        ),
    )

    # SQLAlchemy's Python-side ``onupdate`` does not cover the ingestion
    # package's Core upserts. A small trigger makes ``materials.updated_at``
    # a reliable incremental watermark for every writer.
    op.execute("""
        CREATE FUNCTION sclib_touch_material_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_materials_touch_updated_at
        BEFORE UPDATE ON materials
        FOR EACH ROW
        EXECUTE FUNCTION sclib_touch_material_updated_at()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_materials_touch_updated_at ON materials"
    )
    op.execute("DROP FUNCTION IF EXISTS sclib_touch_material_updated_at()")
    op.drop_table("timeline_projection_state")
    op.drop_index(
        "idx_timeline_projection_theory_active",
        table_name="timeline_projection_points",
    )
    op.drop_index(
        "idx_timeline_projection_aps_active",
        table_name="timeline_projection_points",
    )
    op.drop_index(
        "idx_timeline_projection_material_active",
        table_name="timeline_projection_points",
    )
    op.drop_index(
        "idx_timeline_projection_active_year",
        table_name="timeline_projection_points",
    )
    op.drop_table("timeline_projection_points")
