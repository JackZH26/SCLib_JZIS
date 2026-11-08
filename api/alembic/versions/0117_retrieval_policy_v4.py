"""Admit a distinct stored-source batch budget without relabelling old builds."""
import sqlalchemy as sa
from alembic import op
from migration_history.retrieval_policy_v4 import FUNCTION, TABLE, TRIGGER, POLICY_SHA256, statements

revision = '0117_retrieval_policy_v4'
down_revision = '0116_publication_queue_v2'
branch_labels = None
depends_on = None


def upgrade():
    for sql in statements():
        op.execute(sql)


def downgrade():
    op.execute(f'LOCK TABLE public.{TABLE} IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().execute(sa.text(f'SELECT EXISTS(SELECT 1 FROM public.{TABLE} WHERE policy_artifact_sha256=:sha)'),
                             {'sha': POLICY_SHA256}).scalar_one():
        raise RuntimeError('Refusing to downgrade retained query-policy-v4 builds')
    op.execute(f'DROP TRIGGER {TRIGGER} ON public.{TABLE}')
    op.execute(f'CREATE TRIGGER {TRIGGER} BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_policy_build_v3()')
    op.execute(f'DROP FUNCTION public.{FUNCTION}()')
