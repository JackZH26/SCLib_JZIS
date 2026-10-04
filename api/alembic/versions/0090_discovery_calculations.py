"""Private original QE files associated with a saved research calculation action."""
import sqlalchemy as sa
from alembic import op

revision = "0090_discovery_calculations"
down_revision = "0089_discovery_feedback"
branch_labels = None
depends_on = None


def upgrade():
    from models.db import Base
    from models.discovery_calculation_v1 import TABLE_ORDER

    for name in TABLE_ORDER:
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)


def downgrade():
    from models.discovery_calculation_v1 import FUNCTION_SIGNATURES, TABLE_ORDER

    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing downgrade: retained private calculation files")
    for name in reversed(TABLE_ORDER):
        op.execute(f"DROP TABLE public.{name}")
    for name, signature in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({signature})")
