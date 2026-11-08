"""Retain operator evidence and short exact backend activation/local rollback."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from migration_history.retrieval_activation_v2 import FUNCTION_SIGNATURES, TABLE_ORDER, register

revision = '0110_retrieval_activation_v2'
down_revision = '0109_retrieval_backend_v2'
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ('retrieval_backend_builds_v2', 'retrieval_backend_validations_v2',
                 'retrieval_contents_v2', 'index_generations', 'index_activation_events'):
        sa.Table(name, metadata, sa.Column('id', UUID))
    return register(metadata)


def upgrade():
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute('LOCK TABLE ' + ','.join('public.' + name for name in TABLE_ORDER) + ' IN ACCESS EXCLUSIVE MODE')
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f'SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)')).scalar_one():
            raise RuntimeError('Refusing to discard retained retrieval acceptance/activation authority')
    op.execute('DROP TRIGGER aa_retrieval_v2_blocks_v1 ON public.index_activation_events')
    tables = _tables()
    for name in reversed(TABLE_ORDER):
        tables[name].drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f'DROP FUNCTION public.{name}({arguments})')
