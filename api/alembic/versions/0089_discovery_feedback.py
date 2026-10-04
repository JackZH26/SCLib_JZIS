"""Private archival evidence returns and exact follow-up design associations."""
from alembic import op
import sqlalchemy as sa

revision = "0089_discovery_feedback"
down_revision = "0088_discovery_condition_batches"
branch_labels = None
depends_on = None


def upgrade():
    from models.db import Base
    from models.discovery_feedback_v1 import TABLE_ORDER

    for name in TABLE_ORDER:
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)


def downgrade():
    from models.discovery_feedback_v1 import TABLE_ORDER, FUNCTION_SIGNATURES

    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing downgrade: retained private Discovery evidence return history")
    for name in reversed(TABLE_ORDER):
        op.execute(f"DROP TABLE public.{name}")
    for name, signature in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({signature})")
