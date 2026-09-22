"""Bounded private review text for new approvals; preserve old approval history."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.ml_run_evidence_v1 import FUNCTIONS, PARENTS, TABLES, register

revision = "0075_ml_run_evidence"
down_revision = "0074_ml_use_runs"
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
    op.execute("LOCK TABLE public.ml_use_run_decisions, public.ml_run_review_evidence, public.ml_run_review_evidence_purges IN ACCESS EXCLUSIVE MODE")
    for name in TABLES:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name})")).scalar_one():
            raise RuntimeError("Refusing review-evidence downgrade: retained private bytes or purge history exists")
    op.execute("DROP TRIGGER mu75_complete ON public.ml_use_run_decisions")
    for relation in reversed(tables()):
        relation.drop(op.get_bind())
    for name in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION public.{name}()")
