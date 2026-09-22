"""Preserve raw values, version anomaly views and append correction proposals.

Revision ID: 0049_anomaly_review
Revises: 0048_pressure_projection

No raw material record is changed; historical caps/overrides are not approved.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from models.correction_ledger import CREATE_GUARD, CREATE_TRIGGER

revision = "0049_anomaly_review"
down_revision = "0048_pressure_projection"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("manual_overrides", "is_cap", comment="Legacy numeric request: True = upper review reference; False = unapplied exact proposal (SC03)")
    for name in ("anomaly_review", "anomaly_context"):
        op.add_column("materials", sa.Column(name, postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("timeline_projection_state", sa.Column("anomaly_policy_version", sa.String(80), nullable=False, server_default="legacy/unclassified"))
    op.drop_constraint("ck_timeline_projection_tc", "timeline_projection_points", type_="check")
    op.create_check_constraint("ck_timeline_projection_tc", "timeline_projection_points",
                               "tc_kelvin > 0 AND tc_kelvin < 'Infinity'::float8 AND tc_kelvin <> 'NaN'::float8")
    op.execute("UPDATE timeline_projection_state SET schema_version = 0")
    op.create_table(
        "scientific_correction_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("material_id", sa.String(100), sa.ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_result_id", sa.String(100), nullable=False),
        sa.Column("field", sa.String(50), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scientific_correction_proposals.id", ondelete="RESTRICT")),
        sa.Column("source_quantity", postgresql.JSONB(), nullable=False),
        sa.Column("proposed_quantity", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_paper_id", sa.String(100), nullable=False),
        sa.Column("evidence_locator", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("disposition", sa.String(30), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("material_id", "source_result_id", "field", "revision", name="uq_correction_revision"),
        sa.CheckConstraint("revision > 0", name="ck_correction_positive_revision"),
        sa.CheckConstraint("disposition = 'proposed'", name="ck_correction_proposed_only"),
        sa.CheckConstraint("jsonb_typeof(source_quantity) = 'object' AND jsonb_typeof(proposed_quantity) = 'object'", name="ck_correction_quantity_objects"),
        sa.CheckConstraint("jsonb_typeof(evidence_locator) = 'object' AND evidence_locator <> '{}'::jsonb", name="ck_correction_locator"),
    )
    op.execute(CREATE_GUARD)
    op.execute(CREATE_TRIGGER)


def downgrade():
    # A downgrade must never silently discard source-backed audit revisions.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM scientific_correction_proposals")).scalar_one()
    if count:
        raise RuntimeError("Refusing downgrade: preserve scientific correction proposals before an approved rollback")
    incompatible = op.get_bind().execute(sa.text("SELECT count(*) FROM timeline_projection_points WHERE tc_kelvin > 300")).scalar_one()
    if incompatible:
        raise RuntimeError("Refusing downgrade: the old projection constraint cannot represent retained points")
    op.alter_column("manual_overrides", "is_cap", comment="True = upper-bound clamp; False = exact replacement")
    op.drop_table("scientific_correction_proposals")
    op.execute("DROP FUNCTION sclib_guard_scientific_correction()")
    op.execute("UPDATE timeline_projection_state SET schema_version = 0")
    op.drop_constraint("ck_timeline_projection_tc", "timeline_projection_points", type_="check")
    op.create_check_constraint("ck_timeline_projection_tc", "timeline_projection_points", "tc_kelvin > 0 AND tc_kelvin <= 300")
    op.drop_column("timeline_projection_state", "anomaly_policy_version")
    op.drop_column("materials", "anomaly_context")
    op.drop_column("materials", "anomaly_review")
