"""Private, append-only condition-batch retention and initial-child links."""
from alembic import op
import sqlalchemy as sa

revision = "0088_discovery_condition_batches"
down_revision = "0087_discovery_designs"
branch_labels = None
depends_on = None


def upgrade():
    from models.db import Base
    from models.discovery_condition_batch_v1 import TABLE_ORDER

    # The final table's after-create event installs both tables' guarded writes.
    for name in TABLE_ORDER:
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=False)


def downgrade():
    from models.discovery_condition_batch_v1 import TABLE_ORDER, FUNCTION_SIGNATURES

    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing downgrade: retained private Discovery condition-batch history")
    for name in reversed(TABLE_ORDER):
        op.execute(f"DROP TABLE public.{name}")
    for name, signature in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({signature})")
