"""Retain native publication jobs, fenced leases and exact completion receipts."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID
from migration_history.retrieval_publication_queue_v2 import TABLE_ORDER,statements,cleanup,register

revision='0116_publication_queue_v2'
down_revision='0115_retrieval_policy_v3'
branch_labels=None
depends_on=None


def upgrade():
    metadata = sa.MetaData()
    sa.Table('papers', metadata, sa.Column('id', sa.String))
    sa.Table('retrieval_publications_v2', metadata, sa.Column('id', UUID))
    sa.Table('retrieval_activation_events_v2', metadata, sa.Column('id', UUID))
    register(metadata)
    for name in TABLE_ORDER:
        metadata.tables[name].create(op.get_bind())
    for sql in statements():op.execute(sql)


def downgrade():
    for name in TABLE_ORDER:op.execute(f'LOCK TABLE public.{name} IN ACCESS EXCLUSIVE MODE')
    if any(op.get_bind().execute(sa.text(f'SELECT EXISTS(SELECT 1 FROM public.{name})')).scalar_one() for name in TABLE_ORDER):
        raise RuntimeError('Refusing to downgrade retained native publication queue history')
    for sql in cleanup():op.execute(sql)
    for name in reversed(TABLE_ORDER):op.drop_table(name)
