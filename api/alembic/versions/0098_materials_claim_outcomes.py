"""Retain Tc source quantities and distinguish measured negatives from conditionals."""
import sqlalchemy as sa
from alembic import op
from models.materials_claim_outcomes_v1 import upgrade_statements, downgrade_statements

revision = "0098_materials_claim_outcomes"
down_revision = "0097_materials_conditions"
branch_labels = None
depends_on = None


def upgrade():
    for sql in upgrade_statements():op.execute(sa.DDL(sql.replace("%","%%")))


def downgrade():
    for sql in downgrade_statements():op.execute(sa.DDL(sql.replace("%","%%")))
