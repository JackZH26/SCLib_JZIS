"""Add exact claim targets to the existing immutable scientific review ledger."""
import sqlalchemy as sa
from alembic import op
from models.materials_adjudication_v2 import upgrade_statements, downgrade_statements

revision = "0095_materials_adjudication"
down_revision = "0094_materials_review_subjects"
branch_labels = None
depends_on = None


def upgrade():
    for sql in upgrade_statements(): op.execute(sa.DDL(sql.replace("%", "%%")))


def downgrade():
    for sql in downgrade_statements(): op.execute(sa.DDL(sql.replace("%", "%%")))
