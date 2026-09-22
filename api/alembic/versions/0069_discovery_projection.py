"""Exact scientific Discovery projection disclosure without changing RPS bytes."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.discovery_projection_v1 import FUNCTION_SIGNATURES, PARENTS, TABLE_ORDER, register

revision = "0069_discovery_projection"
down_revision = "0068_answer_evidence"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENTS:
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
            raise RuntimeError("Refusing discovery projection downgrade: retained immutable governance")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
