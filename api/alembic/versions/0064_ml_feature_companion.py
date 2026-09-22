"""Retain exact input-scoped ML source bindings without changing frozen capsules."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.ml_feature_companion_v1 import FUNCTION_SIGNATURES, TABLE_NAME, register

revision = "0064_ml_feature_companion"
down_revision = "0063_research_distribution"
branch_labels = None
depends_on = None


def _table():
    metadata = sa.MetaData()
    for name in ("research_releases", "ml_example_inputs"):
        sa.Table(name, metadata, sa.Column("id", UUID))
    sa.Table("source_revisions", metadata, sa.Column("id", UUID), sa.Column("work_id", UUID))
    sa.Table("source_captures", metadata, sa.Column("id", UUID), sa.Column("source_revision_id", UUID))
    sa.Table("evidence_artifacts", metadata, sa.Column("id", UUID), sa.Column("kind", sa.String(30)))
    return register(metadata)


def upgrade():
    _table().create(op.get_bind())


def downgrade():
    op.execute(f"LOCK TABLE public.{TABLE_NAME} IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{TABLE_NAME})")).scalar_one():
        raise RuntimeError("Refusing ML feature companion downgrade: retained source binding history")
    _table().drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
