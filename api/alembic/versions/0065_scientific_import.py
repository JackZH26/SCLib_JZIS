"""Retain private scientific-program import bytes, starts and pending outcomes."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.scientific_import_v1 import FUNCTION_SIGNATURES, PARENTS, TABLE_ORDER, register

revision = "0065_scientific_import"
down_revision = "0064_ml_feature_companion"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENTS:
        columns = [sa.Column("id", sa.String(100) if name == "materials" else UUID)]
        if name == "evidence_artifacts":
            columns.append(sa.Column("kind", sa.String(30)))
        sa.Table(name, metadata, *columns)
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    names = ",".join("public." + name for name in TABLE_ORDER)
    op.execute(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing scientific-import downgrade: retained source or attempt history")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
