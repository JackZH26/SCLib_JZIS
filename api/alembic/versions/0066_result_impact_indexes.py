"""Add reverse lookup paths for bounded private result-impact inspection.

Index-only: no row rewrite, result refresh, approval or schema-contract change.
Ordinary transactional CREATE INDEX follows the serialized migration job;
production must independently measure table/index size, disk and write-lock
budget before rollout. This is not a concurrent-index deployment recipe.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.scientific_result_impact_indexes_v1 import register

revision = "0066_result_impact_indexes"
down_revision = "0065_scientific_import"
branch_labels = None
depends_on = None


def _indexes():
    metadata = sa.MetaData()
    sa.Table("ml_example_inputs", metadata, sa.Column("input_event_id", UUID))
    sa.Table("event_evidence", metadata, sa.Column("input_event_id", UUID), sa.Column("link_type", sa.String(30)))
    sa.Table("research_distribution_dependencies", metadata, sa.Column("table_name", sa.String(100)),
             sa.Column("row_id", sa.String(200)), *(sa.Column(f"capsule_release_{index}", UUID) for index in range(8)))
    return register(metadata)


def upgrade():
    for index in _indexes().values():
        index.create(op.get_bind())


def downgrade():
    # Retained rows and all independent older nonempty-history guards survive.
    for index in reversed(tuple(_indexes().values())):
        index.drop(op.get_bind())
