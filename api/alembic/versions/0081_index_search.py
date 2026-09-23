"""Precompute exact full-text documents for immutable generation retrieval."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op
from models.index_search_v1 import register

revision = "0081_index_search"
down_revision = "0080_index_corpus"
branch_labels = depends_on = None


def _table():
    metadata = sa.MetaData()
    sa.Table("index_generation_members", metadata,
        sa.Column("generation_id", UUID), sa.Column("vector_id", sa.String(120)))
    sa.Table("index_corpus_observations", metadata)
    return register(metadata)


def upgrade():
    # Serialize backfill with member insertion so no committed member can be
    # absent from the search projection when this revision becomes visible.
    op.execute("LOCK TABLE public.index_generation_members IN SHARE MODE")
    _table().create(op.get_bind())


def downgrade():
    # Only derived search data is removed. Member/evidence records, vectors,
    # manifests and activation events are never updated or deleted.
    op.execute("LOCK TABLE public.index_generation_members IN SHARE MODE")
    _table().drop(op.get_bind())
