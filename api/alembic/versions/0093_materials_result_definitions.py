"""Versioned result definitions and source-result identity on canonical tables."""
import sqlalchemy as sa
from alembic import op
from models.materials_result_definitions_v1 import upgrade_statements, downgrade_statements

revision = "0093_materials_result_defs"
down_revision = "0092_materials_ner_proposals"
branch_labels = None
depends_on = None


def upgrade():
    for sql in upgrade_statements():
        op.execute(sa.DDL(sql.replace("%", "%%")))


def downgrade():
    for sql in downgrade_statements():
        op.execute(sa.DDL(sql.replace("%", "%%")))
