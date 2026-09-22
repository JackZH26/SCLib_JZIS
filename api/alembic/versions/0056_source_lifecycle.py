"""Observe negative source lifecycle and append revision-bound hold reviews.

Revision ID: 0056_source_lifecycle
Revises: 0055_research_publication

No historical inference, source reinstatement, or scientific approval.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.source_lifecycle_v1 import (
    FUNCTION_SIGNATURES,
    PARENT_TABLES,
    TABLE_ORDER,
    register,
    remove_parent_guards,
)

revision = "0056_source_lifecycle"
down_revision = "0055_research_publication"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENT_TABLES + ("research_publication_actions",):
        sa.Table(name, metadata, sa.Column("id", sa.String(100) if name == "papers" else UUID))
    return register(metadata)


def upgrade():
    # No source write can fall between installing capture and observing the
    # existing current held state; this transaction does not rewrite a field.
    op.execute("LOCK TABLE public.papers, public.works IN SHARE ROW EXCLUSIVE MODE")
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())
    op.execute("UPDATE public.papers SET status=status WHERE lower(btrim(status)) IN ('retracted','withdrawn','corrected','disputed')")
    op.execute("UPDATE public.works SET publication_status=publication_status WHERE lower(btrim(publication_status)) IN ('retracted','withdrawn','corrected','disputed')")


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in ("papers", "works", "evidence_artifacts") + TABLE_ORDER)
               + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER[1:]:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive source-lifecycle downgrade: lifecycle history contains records")
    for statement in remove_parent_guards():
        op.execute(statement)
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
