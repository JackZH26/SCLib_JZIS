"""Add metadata-only publication governance with explicit actor grants.

Revision ID: 0055_research_publication
Revises: 0054_research_release

No role grants, scientific approvals, public publication, or legacy data rewrite.
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.research_publication_v1 import FUNCTION_NAMES, PARENT_TABLES, TABLE_ORDER, register

revision = "0055_research_publication"
down_revision = "0054_research_release"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENT_TABLES:
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + name for name in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER[1:]:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing destructive research-publication downgrade: governance history contains records")
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name in reversed(FUNCTION_NAMES):
        arguments = {"sclib_research_publication_role_v1": "uuid, uuid, text",
                     "sclib_research_publication_actor_v1": "uuid, boolean",
                     "sclib_research_publication_object_v1": "text, text, text, text",
                     "sclib_research_publication_payload_v1": "jsonb, uuid, text, text"}.get(name, "")
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
