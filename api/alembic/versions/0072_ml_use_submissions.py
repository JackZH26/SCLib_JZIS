"""Private ML submission receipts and purgeable seven-day inputs; no grants."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.ml_use_submissions_v1 import FUNCTIONS, PARENTS, TABLES, register

revision = "0072_ml_use_submissions"
down_revision = "0071_ml_use_roles"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENTS:
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    for table in _tables():
        table.create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLES) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLES:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name})")).scalar_one():
            raise RuntimeError("Refusing ML submission downgrade: retained private audit history exists")
    for table in reversed(_tables()):
        table.drop(op.get_bind())
    for name in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION public.{name}()")
