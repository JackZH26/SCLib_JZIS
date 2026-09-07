"""Add an immutable source revision/capture/claim-occurrence registry.

Revision ID: 0052_source_provenance
Revises: 0051_material_semantics

No legacy backfill, source fetching, publication-date inference or result merge.
Downgrade is allowed only while the new registry is empty.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.source_provenance_v1 import (
    CLAIM_WORK_UNIQUE,
    IMMUTABILITY_FUNCTION,
    TABLE_ORDER,
    register,
)

revision = "0052_source_provenance"
down_revision = "0051_material_semantics"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    sa.Table("papers", metadata, sa.Column("id", sa.String(100)))
    sa.Table("works", metadata, sa.Column("id", UUID))
    sa.Table("material_claims", metadata, sa.Column("id", UUID), sa.Column("work_id", UUID))
    sa.Table("evidence_artifacts", metadata, sa.Column("id", UUID), sa.Column("kind", sa.String(30)))
    return register(metadata)


def upgrade():
    # id is already a primary key: the additional composite UNIQUE cannot
    # reject historical rows, including NULL/unresolved work identifiers.
    op.create_unique_constraint(CLAIM_WORK_UNIQUE, "material_claims", ["id", "work_id"])
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    # Lock before the emptiness test so a concurrent importer cannot race the
    # guard. Fixed internal identifiers only; no dynamic user SQL.
    op.execute("LOCK TABLE claim_source_occurrences, source_captures, source_revisions IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive source-provenance downgrade: registry contains records")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    op.drop_constraint(CLAIM_WORK_UNIQUE, "material_claims", type_="unique")
    op.execute(f"DROP FUNCTION {IMMUTABILITY_FUNCTION}()")
