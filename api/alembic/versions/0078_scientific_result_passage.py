"""Add reviewed exact result-to-original-passage links."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.scientific_result_passage_v1 import FUNCTIONS, PARENTS, TABLE, register

revision = "0078_scientific_result_passage"
down_revision = "0077_ml_pilot_attestations"
branch_labels = None
depends_on = None


def relation():
    metadata = sa.MetaData()
    for name in PARENTS:
        kind = sa.String(100) if name == "papers" else UUID
        sa.Table(name, metadata, sa.Column("id", kind))
    return register(metadata)


def upgrade():
    relation().create(op.get_bind())


def downgrade():
    op.execute(f"LOCK TABLE public.{TABLE} IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{TABLE})")).scalar_one():
        raise RuntimeError("Refusing result-passage downgrade: immutable reviewed links exist")
    relation().drop(op.get_bind())
    for name, arguments in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
