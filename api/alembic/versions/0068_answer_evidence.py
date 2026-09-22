"""Retain bounded final Ask response evidence without backfilling past pins."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.answer_evidence_v1 import FUNCTION_SIGNATURES, PARENTS, TABLE_NAME, register

revision = "0068_answer_evidence"
down_revision = "0067_scientific_adjudication"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in PARENTS:
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    op.add_column("ask_history", sa.Column("evidence_receipt_version", sa.String(50), nullable=True))
    _tables()[TABLE_NAME].create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE public.ask_history,public.answer_evidence_receipts IN ACCESS EXCLUSIVE MODE")
    retained = op.get_bind().execute(sa.text("""SELECT EXISTS(SELECT 1 FROM public.answer_evidence_receipts LIMIT 1)
        OR EXISTS(SELECT 1 FROM public.ask_history WHERE evidence_receipt_version IS NOT NULL LIMIT 1)""")).scalar_one()
    if retained:
        raise RuntimeError("Refusing answer-evidence downgrade: retained immutable saved answers")
    op.execute("DROP TRIGGER ae68_complete ON public.ask_history")
    op.execute("DROP TRIGGER ae68_parent ON public.ask_history")
    _tables()[TABLE_NAME].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
    op.drop_column("ask_history", "evidence_receipt_version")
