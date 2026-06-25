"""hydride_tc_parameters: independent hydride Tc parameter NER results

Revision ID: 0040_hydride_tc_parameters
Revises: 0039_tdm_audit_log
Create date: 2026-06-25

This table stores the output of the hydride-specific NER pass. It is
deliberately separate from ``papers.materials_extracted`` and the generic
``materials.records`` aggregate so the hydride enrichment can be rerun,
audited, and rolled out without perturbing the baseline material catalogue.

APS compliance note: records here contain only derived structured facts
and metadata/provenance. Do not store APS full-text snippets or long
evidence quotes in this table.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0040_hydride_tc_parameters"
down_revision = "0039_tdm_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hydride_tc_parameters",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("record_key", sa.String(80), nullable=False),
        sa.Column("material_id", sa.String(100), nullable=True),
        sa.Column("formula", sa.String(200), nullable=False),
        sa.Column("formula_normalized", sa.String(200), nullable=False),
        sa.Column("paper_id", sa.String(100), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("doi", sa.String(200), nullable=True),
        sa.Column("arxiv_id", sa.String(20), nullable=True),
        sa.Column("year", sa.SmallInteger(), nullable=True),
        sa.Column("tc_kelvin", sa.Float(), nullable=True),
        sa.Column("pressure_gpa", sa.Float(), nullable=True),
        sa.Column("lambda_eph", sa.Float(), nullable=True),
        sa.Column("mu_star", sa.Float(), nullable=True),
        sa.Column("omega_log_k", sa.Float(), nullable=True),
        sa.Column("omega_log_source_value", sa.Float(), nullable=True),
        sa.Column("omega_log_source_unit", sa.String(20), nullable=True),
        sa.Column("method", sa.String(80), nullable=True),
        sa.Column("evidence_type", sa.String(40), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_section", sa.String(200), nullable=True),
        sa.Column("validation_flags", JSONB(), nullable=False, server_default="[]"),
        sa.Column("provenance", JSONB(), nullable=False, server_default="{}"),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint("record_key", name="uq_hydride_tc_parameters_record_key"),
    )
    op.create_index(
        "idx_hydride_params_material",
        "hydride_tc_parameters",
        ["material_id"],
    )
    op.create_index(
        "idx_hydride_params_paper",
        "hydride_tc_parameters",
        ["paper_id"],
    )
    op.create_index(
        "idx_hydride_params_formula",
        "hydride_tc_parameters",
        ["formula_normalized"],
    )
    op.create_index(
        "idx_hydride_params_source_year",
        "hydride_tc_parameters",
        ["source", "year"],
    )


def downgrade() -> None:
    op.drop_index("idx_hydride_params_source_year", table_name="hydride_tc_parameters")
    op.drop_index("idx_hydride_params_formula", table_name="hydride_tc_parameters")
    op.drop_index("idx_hydride_params_paper", table_name="hydride_tc_parameters")
    op.drop_index("idx_hydride_params_material", table_name="hydride_tc_parameters")
    op.drop_table("hydride_tc_parameters")
