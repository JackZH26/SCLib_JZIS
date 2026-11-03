"""Admit a separately identified bounded exact-year query policy."""
import sqlalchemy as sa
from alembic import op
from models.retrieval_policy_v3 import FUNCTION,TABLE,TRIGGER,POLICY_SHA256,statements

revision='0115_retrieval_policy_v3'
down_revision='0114_bounded_validation_v3'
branch_labels=None
depends_on=None


def upgrade():
    for sql in statements():op.execute(sql)


def downgrade():
    op.execute(f'LOCK TABLE public.{TABLE} IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().execute(sa.text(f'SELECT EXISTS(SELECT 1 FROM public.{TABLE} WHERE policy_artifact_sha256=:sha)'),{'sha':POLICY_SHA256}).scalar_one():
        raise RuntimeError('Refusing to downgrade retained query-policy-v3 builds')
    op.execute(f'DROP TRIGGER {TRIGGER} ON public.{TABLE}')
    op.execute(f'CREATE TRIGGER {TRIGGER} BEFORE INSERT ON public.{TABLE} FOR EACH ROW EXECUTE FUNCTION public.sclib_retrieval_backend_insert_v2()')
    op.execute(f'DROP FUNCTION public.{FUNCTION}()')
