"""Record exact complete document-embedding responses without storing vectors.

Revision ID: 0061_embedding_receipts
Revises: 0060_rag_evidence
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.embedding_receipts_v1 import FUNCTION_SIGNATURES, TABLE_NAME, register

revision = "0061_embedding_receipts"
down_revision = "0060_rag_evidence"
branch_labels = None
depends_on = None


def _table():
    metadata = sa.MetaData()
    sa.Table("rag_evidence_revisions", metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    _table().create(op.get_bind())


def downgrade():
    op.execute(f"LOCK TABLE public.{TABLE_NAME} IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{TABLE_NAME} LIMIT 1)")).scalar_one():
        raise RuntimeError("Refusing destructive embedding-receipt downgrade: receipt history contains records")
    _table().drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
