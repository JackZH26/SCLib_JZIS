"""Retain actual input/native revisions without creating provider generations."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from migration_history.retrieval_native_v2 import FUNCTION_SIGNATURES, TABLE_ORDER, register

revision = "0107_retrieval_native_v2"
down_revision = "0106_materials_source_notation"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ("rag_evidence_revisions", "embedding_completion_receipts"):
        sa.Table(name, metadata, sa.Column("id", UUID))
    sa.Table("index_active_pointer", metadata)
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing to discard retained retrieval input or native revision history")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
