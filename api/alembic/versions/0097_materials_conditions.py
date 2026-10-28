"""Typed state conditions, pressure projections and measured geometry support."""
import sqlalchemy as sa
from alembic import op
from models.materials_conditions_v1 import upgrade_statements,downgrade_statements

revision="0097_materials_conditions"
down_revision="0096_materials_context"
branch_labels=None
depends_on=None


def upgrade():
    for sql in upgrade_statements():op.execute(sa.DDL(sql.replace("%","%%")))


def downgrade():
    for sql in downgrade_statements():op.execute(sa.DDL(sql.replace("%","%%")))
