"""Add immutable shadow occurrence/revision/membership import history.

Revision ID: 0053_research_import
Revises: 0052_source_provenance

No legacy writes, scientific promotion, public route changes or source-version
inference. A populated shadow ledger cannot be destructively downgraded.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.research_import_v1 import IMMUTABILITY_FUNCTION, TABLE_ORDER, register

revision = "0053_research_import"
down_revision = "0052_source_provenance"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ("materials", "papers"):
        sa.Table(name, metadata, sa.Column("id", sa.String(100)))
    sa.Table("works", metadata, sa.Column("id", UUID))
    sa.Table("evidence_artifacts", metadata, sa.Column("id", UUID), sa.Column("kind", sa.String(30)))
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE research_import_receipts, research_import_memberships, "
               "research_import_revisions, research_import_occurrences, research_import_snapshots "
               "IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive research-import downgrade: shadow history contains records")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    op.execute(f"DROP FUNCTION {IMMUTABILITY_FUNCTION}()")
