"""Read-only, exact typed subjects for Tc claims and other physical results."""
import sqlalchemy as sa
from alembic import op
from models.materials_review_subjects_v2 import upgrade_statements, downgrade_statements

revision = "0094_materials_review_subjects"
down_revision = "0093_materials_result_defs"
branch_labels = None
depends_on = None


def upgrade():
    for sql in upgrade_statements(): op.execute(sa.DDL(sql.replace("%", "%%")))


def downgrade():
    for sql in downgrade_statements(): op.execute(sa.DDL(sql))
