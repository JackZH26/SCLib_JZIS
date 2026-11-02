"""Separate complete retrieval content from ANN provider resources."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.retrieval_content_v2 import FUNCTION_SIGNATURES, TABLE_ORDER, register

revision = "0108_retrieval_content_v2"
down_revision = "0107_retrieval_native_v2"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ("index_generations", "retrieval_native_revisions_v2"):
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing to discard retained retrieval publication or content history")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
