"""Add ten research shadow tables; keep existing science rows untouched.

Revision ID: 0045_research_shadow
Revises: 0044_ml_foundation

No backfill, feature enablement, general ML targets or closure freeze writer.
The versioned table specification is immutable once this migration ships.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.research_schema_v2 import TABLE_ORDER, register

revision = "0045_research_shadow"
down_revision = "0044_ml_foundation"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ("materials", "works", "source_snapshots", "ml_examples"):
        sa.Table(name, metadata, sa.Column("id", sa.String(100) if name == "materials" else UUID))
    sa.Table("material_claims", metadata, sa.Column("id", UUID), sa.Column("event_id", UUID))
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER[:7]:
        tables[name].create(op.get_bind())
    op.add_column("material_claims", sa.Column("event_id", UUID(as_uuid=True)))
    op.add_column("material_claims", sa.Column("result_key", sa.String(120)))
    op.add_column("material_claims", sa.Column("interpretation_revision", sa.Integer))
    op.create_foreign_key(
        "fk_rv2_claim_event_material",
        "material_claims",
        "research_events",
        ["event_id", "material_id"],
        ["id", "material_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_rv2_claim_event", "material_claims", ["id", "event_id"])
    op.create_check_constraint(
        "ck_rv2_claim_binding",
        "material_claims",
        "(event_id IS NULL AND result_key IS NULL AND interpretation_revision IS NULL) OR "
        "(event_id IS NOT NULL AND result_key IS NOT NULL AND btrim(result_key)<>'' "
        "AND interpretation_revision IS NOT NULL AND interpretation_revision>=1)",
    )
    op.create_index(
        "uq_rv2_claim_result",
        "material_claims",
        ["event_id", "result_key"],
        unique=True,
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )
    for name in TABLE_ORDER[7:]:
        tables[name].create(op.get_bind())


def downgrade():
    tables = _tables()
    for name in reversed(TABLE_ORDER[7:]):
        tables[name].drop(op.get_bind())
    op.drop_index("uq_rv2_claim_result", "material_claims")
    op.drop_constraint("ck_rv2_claim_binding", "material_claims", type_="check")
    op.drop_constraint("uq_rv2_claim_event", "material_claims", type_="unique")
    op.drop_constraint("fk_rv2_claim_event_material", "material_claims", type_="foreignkey")
    for name in ("interpretation_revision", "result_key", "event_id"):
        op.drop_column("material_claims", name)
    for name in reversed(TABLE_ORDER[:7]):
        tables[name].drop(op.get_bind())
