"""Retain exact legacy bytes/windows without inventing historical lineage."""

import sqlalchemy as sa
from alembic import op
from models.retained_legacy_v1 import TABLE_ORDER, FUNCTION_SIGNATURES, kind_constraints, register

revision = "0079_retained_legacy"
down_revision = "0078_scientific_result_passage"
branch_labels = depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in (
        "chunks",
        "papers",
        "rag_evidence_revisions",
        "index_active_pointer",
        "answer_evidence_receipts",
    ):
        sa.Table(name, metadata)
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute(
        "LOCK TABLE "
        + ",".join("public." + name for name in TABLE_ORDER)
        + " IN ACCESS EXCLUSIVE MODE"
    )
    for name in TABLE_ORDER:
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name})"))
            .scalar_one()
        ):
            raise RuntimeError("Refusing destructive retained legacy downgrade")
    op.execute("DROP TRIGGER re79_legacy ON public.rag_evidence_revisions")
    for table in TABLE_ORDER:
        for trigger in ("ls79_insert", "ls79_immutable", "ls79_truncate"):
            op.execute(f"DROP TRIGGER {trigger} ON public.{table}")
    for name, args in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({args})")
    for name in reversed(TABLE_ORDER):
        op.execute(f"DROP TABLE public.{name}")
    for statement in kind_constraints(False):
        op.execute(statement)
