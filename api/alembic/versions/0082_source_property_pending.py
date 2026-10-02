"""Independent pending source properties and source-expression review notes."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.source_property_pending_v1 import FUNCTION_SIGNATURES, TABLE_ORDER, register

revision = "0082_source_property_pending"
down_revision = "0081_index_search"
branch_labels = depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ("users", "research_role_grants", "research_publication_epoch"):
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
            raise RuntimeError("Refusing downgrade: retained pending source-property audit history")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
