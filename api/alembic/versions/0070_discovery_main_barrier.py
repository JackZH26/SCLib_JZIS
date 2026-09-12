"""Explicit curator main-barrier declarations, preserving all frozen v1 data."""
import sqlalchemy as sa

from alembic import op
from models.discovery_projection_v1 import TABLE_ORDER
from models.discovery_projection_v2 import (
    FUNCTION_SIGNATURES,
    frozen_insert_statement,
    guard_statements,
)

revision = "0070_discovery_main_barrier"
down_revision = "0069_discovery_projection"
branch_labels = None
depends_on = None


def upgrade():
    for statement in guard_statements():
        op.execute(statement)


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    retained = op.get_bind().execute(sa.text("""
      SELECT EXISTS(SELECT 1 FROM public.discovery_projection_packages
        WHERE payload_json::jsonb->>'version' IS DISTINCT FROM 'discovery-scientific-projection/1.0.0'
          OR selection_json::jsonb->>'version' IS DISTINCT FROM 'discovery-scientific-selection/1.0.0')
    """)).scalar_one()
    if retained:
        raise RuntimeError("Refusing main-barrier downgrade: retained immutable v2 governance")
    op.execute(frozen_insert_statement())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
