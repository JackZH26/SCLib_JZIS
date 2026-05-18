"""Pipeline state table + R2.2 normalize-version interlock seed.

Revision ID: 0035_pipeline_state
Down revision: 0034_concat_descriptor

Creates a tiny key/value ``pipeline_state`` table and seeds
``materials_normalize_version = '1'`` (the pre-R2.1 canonicalisation
scheme the existing rows are keyed under).

nims.NORMALIZE_SCHEMA_VERSION is now 2 (R2.1 cosmetic folding).
aggregate_from_papers refuses to run while this value is < the code
version, so an aggregator sweep cannot re-key rows and multiply
duplicates before the R2.2 consolidation
(scripts/r22_consolidate.py --apply) has reconciled the table and
bumped this to '2'.
"""
from alembic import op
import sqlalchemy as sa


revision = "0035_pipeline_state"
down_revision = "0034_concat_descriptor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_state",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(256), nullable=False),
    )
    op.execute(
        "INSERT INTO pipeline_state (key, value) "
        "VALUES ('materials_normalize_version', '1') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("pipeline_state")
