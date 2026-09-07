"""Protect canonical research closures and append-only integrity capsules.

Revision ID: 0054_research_release
Revises: 0053_research_import

No data backfill, scientific promotion, or public publication. Existing cycles
fail the migration preflight; no populated release history can be downgraded.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.research_release_v1 import (
    ALLOWED_TABLES,
    FUNCTION_NAMES,
    TABLE_ORDER,
    register,
    remove_guard_statements,
)

revision = "0054_research_release"
down_revision = "0053_research_import"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ALLOWED_TABLES:
        columns = [sa.Column("id", UUID)]
        if name == "evidence_artifacts":
            columns.append(sa.Column("kind", sa.String(30)))
        sa.Table(name, metadata, *columns)
    return register(metadata)


def upgrade():
    # Locks cover the migration preflight and installation as one transaction.
    op.execute("LOCK TABLE " + ",".join("public." + name for name in ALLOWED_TABLES) + " IN SHARE ROW EXCLUSIVE MODE")
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in ALLOWED_TABLES + TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER[1:]:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive research-release downgrade: release history contains records")
    for statement in remove_guard_statements():
        op.execute(statement)
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name in reversed(FUNCTION_NAMES):
        op.execute(f"DROP FUNCTION public.{name}()")
