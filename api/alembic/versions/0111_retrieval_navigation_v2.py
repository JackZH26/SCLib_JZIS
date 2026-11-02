"""Native lexical/formula navigation without rewriting retained source rows."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op
from models.retrieval_navigation_v2 import FUNCTION_SIGNATURES,INDEXES,PARENTS,TABLE,register

revision='0111_retrieval_navigation_v2'
down_revision='0110_retrieval_activation_v2'
branch_labels=None
depends_on=None

def _table():
    metadata=sa.MetaData()
    for name in PARENTS:sa.Table(name,metadata,sa.Column('id',UUID))
    return register(metadata)

def upgrade():_table().create(op.get_bind())

def downgrade():
    op.execute(f'LOCK TABLE public.{TABLE} IN ACCESS EXCLUSIVE MODE')
    # Navigation contains only deterministic derived tokens, never unique text
    # or scientific inputs. Inactive navigation can be rebuilt from retained
    # origins; an active native reader must keep its current navigation.
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM retrieval_active_pointer_v2 p "
        "JOIN retrieval_content_members_v2 m ON m.content_id=p.content_id AND m.origin_kind='native_v2')")).scalar_one():
        raise RuntimeError('Refusing to discard active native navigation')
    for name,table in [('aa_navigation_v2_publication','retrieval_publication_seals_v2'),
                       ('aa_navigation_v2_validation','retrieval_backend_validations_v2'),
                       ('aa_navigation_v2_activation','retrieval_activation_events_v2')]:
        op.execute(f'DROP TRIGGER {name} ON public.{table}')
    _table().drop(op.get_bind())
    for name,_,_ in reversed(INDEXES):op.execute(f'DROP INDEX public.{name}')
    for name,args in reversed(FUNCTION_SIGNATURES):op.execute(f'DROP FUNCTION public.{name}({args})')
