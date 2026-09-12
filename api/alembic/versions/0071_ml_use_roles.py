"""Separate append-only ML workflow role governance; provision no authority."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.ml_use_roles_v1 import FUNCTION_SIGNATURES, PARENT_TABLES, TABLE, register

revision = "0071_ml_use_roles"
down_revision = "0070_discovery_main_barrier"
branch_labels = None
depends_on = None


def _table():
    metadata = sa.MetaData()
    for parent in PARENT_TABLES:
        sa.Table(parent, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    _table().create(op.get_bind())


def downgrade():
    op.execute(f"LOCK TABLE public.{TABLE} IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{TABLE} LIMIT 1)")).scalar_one():
        raise RuntimeError("Refusing ML-use role downgrade: immutable authorization history exists")
    _table().drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
