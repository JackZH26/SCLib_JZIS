"""Index canonical source pagination on databases with a non-C default locale."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op
from models.retrieval_keysets_v2 import INDEXES,register

revision='0112_retrieval_keysets_v2'
down_revision='0111_retrieval_navigation_v2'
branch_labels=None
depends_on=None


def _indexes():
    metadata=sa.MetaData()
    for _,relation,parent in INDEXES:
        sa.Table(relation,metadata,sa.Column(parent,UUID),sa.Column('vector_id',sa.Text))
    return register(metadata)


def upgrade():
    for index in _indexes().values():index.create(op.get_bind())


def downgrade():
    for index in reversed(list(_indexes().values())):index.drop(op.get_bind())
