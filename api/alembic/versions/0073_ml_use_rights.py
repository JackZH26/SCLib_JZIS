"""Independent, purpose-specific ML rights decisions; no real grants or runs."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.ml_use_rights_v1 import FUNCTIONS, PARENTS, TABLE, register

revision = "0073_ml_use_rights"
down_revision = "0072_ml_use_submissions"
branch_labels = None
depends_on = None


def _table():
    metadata = sa.MetaData()
    for name in PARENTS:
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    _table().create(op.get_bind())


def downgrade():
    op.execute(f"LOCK TABLE public.{TABLE} IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{TABLE})")).scalar_one():
        raise RuntimeError("Refusing ML rights downgrade: retained independent review history exists")
    _table().drop(op.get_bind())
    for name in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION public.{name}()")
