"""Private retained primary fragments and pending expression successors."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.source_expression_intake_v2 import FUNCTION_SIGNATURES, TABLE_ORDER, register

revision = "0083_source_expression_intake"
down_revision = "0082_source_property_pending"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ("users", "research_role_grants", "research_publication_epoch"):
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    for table in _tables().values():
        table.create(op.get_bind())


def downgrade():
    op.execute(
        "LOCK TABLE " + ",".join("public." + n for n in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE"
    )
    for name in TABLE_ORDER:
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)"))
            .scalar_one()
        ):
            raise RuntimeError("Refusing downgrade: retained source-expression audit history")
    for table in reversed(list(_tables().values())):
        table.drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
