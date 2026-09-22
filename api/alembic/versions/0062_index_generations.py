"""Retain bounded private index generations and append-only activation history.

Revision ID: 0062_index_generations
Revises: 0061_embedding_receipts
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.index_generations_v1 import FUNCTION_SIGNATURES, HISTORY_TABLES, TABLE_ORDER, register

revision = "0062_index_generations"
down_revision = "0061_embedding_receipts"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ("rag_evidence_revisions", "embedding_completion_receipts"):
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in (*HISTORY_TABLES, "index_active_pointer"):
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive index-generation downgrade: retained history contains records")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
