"""Source-tested device descriptors and fit-intersection criteria."""
from alembic import op
from models.materials_device_descriptors_v3 import upgrade_statements, downgrade_statements

revision = '0104_materials_device_context'
down_revision = '0103_materials_ner_amendments'
branch_labels = None
depends_on = None


def upgrade():
    for statement in upgrade_statements(): op.execute(statement)


def downgrade():
    for statement in downgrade_statements(): op.execute(statement)
