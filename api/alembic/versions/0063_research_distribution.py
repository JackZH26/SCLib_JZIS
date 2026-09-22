"""Add exact RPS structured-distribution governance without publication.

Revision ID: 0063_research_distribution
Revises: 0062_index_generations
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.research_distribution_v1 import (
    FUNCTION_SIGNATURES,
    HISTORY_TABLES,
    IDENTITY_FIELDS,
    PARENT_TABLES,
    TABLE_ORDER,
    register,
)
from services.research_release_spec import SPEC

revision = "0063_research_distribution"
down_revision = "0062_index_generations"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENT_TABLES:
        key = IDENTITY_FIELDS.get(name, "id")
        kind = UUID if name not in SPEC or SPEC[name]["fields"][key]["type"] == "UUID" else sa.String(200)
        sa.Table(name, metadata, sa.Column(key, kind))
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in HISTORY_TABLES:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive research-distribution downgrade: retained governance history")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
