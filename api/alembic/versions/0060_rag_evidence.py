"""Persist text-free retrieval lineage independently of mutable chunks.

Revision ID: 0060_rag_evidence
Revises: 0059_background_jobs
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.rag_evidence_v1 import FUNCTION_SIGNATURES, TABLE_ORDER, register, remove_parent_guards

revision = "0060_rag_evidence"
down_revision = "0059_background_jobs"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name, kind in (("papers", sa.String(100)), ("chunks", sa.String(200)), ("source_captures", UUID)):
        sa.Table(name, metadata, sa.Column("id", kind))
    return register(metadata)


def upgrade():
    op.execute("LOCK TABLE public.chunks IN SHARE ROW EXCLUSIVE MODE")
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE public.chunks," + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive RAG-evidence downgrade: lineage history contains records")
    for statement in remove_parent_guards():
        op.execute(statement)
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
