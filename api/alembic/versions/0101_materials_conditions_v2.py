"""Adopt source-reported field conditions across canonical write guards."""
from alembic import op
from models.materials_conditions_adoption_v2 import upgrade_statements, downgrade_statements

revision = "0101_materials_conditions_v2"
down_revision = "0100_materials_ner_relations"
branch_labels = None
depends_on = None


def upgrade():
    for sql in upgrade_statements():
        op.execute(sql)


def downgrade():
    for sql in downgrade_statements():
        op.execute(sql)
