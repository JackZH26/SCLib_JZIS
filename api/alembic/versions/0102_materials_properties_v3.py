"""Adopt pressure slopes and electrical resistivity with typed source quantities."""
from alembic import op
from models.materials_properties_v3 import upgrade_statements, downgrade_statements

revision = '0102_materials_properties_v3'
down_revision = '0101_materials_conditions_v2'
branch_labels = None
depends_on = None


def upgrade():
    for sql in upgrade_statements():
        op.execute(sql)


def downgrade():
    for sql in downgrade_statements():
        op.execute(sql)
