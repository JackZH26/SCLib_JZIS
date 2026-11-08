"""Store content-bound saved answers separately from immutable v1 receipts."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op
from migration_history.content_answer_storage_v2 import TABLE,PARENTS,FUNCTIONS,register

revision='0113_content_answer_receipts_v2'
down_revision='0112_retrieval_keysets_v2'
branch_labels=None
depends_on=None


def _table():
    metadata=sa.MetaData()
    for name in PARENTS:sa.Table(name,metadata,sa.Column('id',UUID))
    return register(metadata)


def upgrade():
    op.add_column('ask_history',sa.Column('content_evidence_receipt_version',sa.String(50),nullable=True))
    _table().create(op.get_bind())


def downgrade():
    op.execute(f'LOCK TABLE public.ask_history,public.{TABLE} IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().execute(sa.text(f'SELECT EXISTS(SELECT 1 FROM public.{TABLE}) OR '
        'EXISTS(SELECT 1 FROM public.ask_history WHERE content_evidence_receipt_version IS NOT NULL)')).scalar_one():
        raise RuntimeError('Refusing to discard retained content answer history')
    for name in ('cae113_complete','cae113_parent'):op.execute(f'DROP TRIGGER {name} ON public.ask_history')
    _table().drop(op.get_bind())
    for name,args in reversed(FUNCTIONS):op.execute(f'DROP FUNCTION public.{name}({args})')
    op.drop_column('ask_history','content_evidence_receipt_version')
