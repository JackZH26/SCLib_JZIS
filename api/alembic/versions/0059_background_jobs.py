"""Coordinate complete background cycles without rewriting scientific data.

Revision ID: 0059_background_jobs
Revises: 0058_source_tasks
"""
import sqlalchemy as sa

from alembic import op
from models.background_jobs_v1 import FUNCTION_SIGNATURES, TABLE_NAME, register

revision = "0059_background_jobs"
down_revision = "0058_source_tasks"
branch_labels = None
depends_on = None


def upgrade():
    register(sa.MetaData()).create(op.get_bind())


def downgrade():
    op.execute(f"LOCK TABLE public.{TABLE_NAME} IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{TABLE_NAME} LIMIT 1)")).scalar_one():
        raise RuntimeError("Refusing destructive background-job downgrade: cycle history contains records")
    register(sa.MetaData()).drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
