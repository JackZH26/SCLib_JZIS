"""Add exact-result subjects, atomic reviewer requests and immutable decisions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.scientific_adjudication_v1 import (
    ASSEMBLY_WRITER_TABLES,
    CATALOGUE_TABLES,
    FUNCTION_SIGNATURES,
    PARENTS,
    TABLE_ORDER,
    register,
)

revision = "0067_scientific_adjudication"
down_revision = "0066_result_impact_indexes"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENTS:
        columns = [sa.Column("id", sa.String(100) if name == "materials" else UUID)]
        if name == "event_properties": columns.append(sa.Column("event_id", UUID))
        if name == "research_events": columns.append(sa.Column("revision", sa.Integer))
        sa.Table(name, metadata, *columns)
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing scientific-adjudication downgrade: retained exact review history")
    for name in CATALOGUE_TABLES:
        op.execute(f"DROP TRIGGER sa67_catalogue_writer ON public.{name}")
    for name in ASSEMBLY_WRITER_TABLES:
        op.execute(f"DROP TRIGGER sa67_assembly_writer ON public.{name}")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
