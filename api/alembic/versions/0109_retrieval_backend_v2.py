"""Retain real pgvector build/seal/readback history, without activation."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.retrieval_backend_v2 import FUNCTION_SIGNATURES, TABLE_ORDER, register

revision = "0109_retrieval_backend_v2"
down_revision = "0108_retrieval_content_v2"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    sa.Table("retrieval_contents_v2", metadata, sa.Column("id", UUID))
    sa.Table("retrieval_content_seals_v2", metadata)
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing to discard retained retrieval build/seal/validation history")
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='retrieval_projection')")).scalar_one():
        raise RuntimeError("Refusing to discard private projection objects during downgrade")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
    op.execute("DROP SCHEMA retrieval_projection")
