"""Exact requested run plans and independent conditional approvals; no runs."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.ml_use_runs_v1 import FUNCTIONS, PARENTS, TABLES, register

revision = "0074_ml_use_runs"
down_revision = "0073_ml_use_rights"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name in PARENTS:
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    for relation in tables():
        relation.create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE public.ml_use_run_plans, public.ml_use_run_decisions IN ACCESS EXCLUSIVE MODE")
    for name in TABLES:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name})")).scalar_one():
            raise RuntimeError("Refusing ML run downgrade: retained requested plan or independent review history exists")
    for relation in reversed(tables()):
        relation.drop(op.get_bind())
    for name in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION public.{name}()")
