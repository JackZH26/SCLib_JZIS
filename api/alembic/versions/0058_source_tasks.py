"""Persist negative Timeline cache-invalidation requests and receipts.

Revision ID: 0058_source_tasks
Revises: 0057_source_impact

No source backfill, request creation, queue execution, or projection mutation.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.source_tasks_v1 import (
    FUNCTION_SIGNATURES,
    PARENT_TABLES,
    TABLE_ORDER,
    register,
    remove_parent_guards,
)

revision = "0058_source_tasks"
down_revision = "0057_source_impact"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENT_TABLES + ("source_lifecycle_reviews",):
        sa.Table(name, metadata, sa.Column("id", sa.SmallInteger if name == "timeline_projection_state" else UUID))
    return register(metadata)


def upgrade():
    op.execute("LOCK TABLE public.timeline_projection_state, public.timeline_projection_points IN SHARE ROW EXCLUSIVE MODE")
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in (
        "timeline_projection_state", "timeline_projection_points") + TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER[1:]:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive source-task downgrade: task history contains records")
    for statement in remove_parent_guards():
        op.execute(statement)
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
