"""Private, append-only Discovery research-design revisions."""
from alembic import op
import sqlalchemy as sa

revision = "0087_discovery_designs"
down_revision = "0086_material_literal_fields"
branch_labels = None
depends_on = None


def upgrade():
    from models.db import Base
    from models.discovery_design_v1 import TABLE_ORDER
    # Metadata owns the after-create guards; create once without replaying DDL.
    for name in TABLE_ORDER:
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)


def downgrade():
    from models.discovery_design_v1 import TABLE_ORDER, FUNCTION_SIGNATURES
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing downgrade: retained private Discovery research-design history")
    for name in reversed(TABLE_ORDER):
        op.execute(f"DROP TABLE public.{name}")
    for name, signature in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({signature})")
