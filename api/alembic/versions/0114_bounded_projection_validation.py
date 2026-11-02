"""Validate complete projections in bounded source partitions."""
from alembic import op
from models.retrieval_bounded_validation_v3 import FUNCTION,TABLE,TRIGGER,statements

revision='0114_bounded_validation_v3'
down_revision='0113_content_answer_receipts_v2'
branch_labels=None
depends_on=None


def upgrade():
    for sql in statements():op.execute(sql)


def downgrade():
    op.execute(f'DROP TRIGGER {TRIGGER} ON public.{TABLE}')
    op.execute(f'CREATE TRIGGER {TRIGGER} BEFORE INSERT ON public.{TABLE} FOR EACH ROW '
        'EXECUTE FUNCTION public.sclib_retrieval_backend_insert_v2()')
    op.execute(f'DROP FUNCTION public.{FUNCTION}()')
