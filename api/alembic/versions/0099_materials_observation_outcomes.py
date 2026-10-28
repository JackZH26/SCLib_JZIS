"""Store target-specific non-detections without manufacturing a Tc claim."""
import sqlalchemy as sa
from alembic import op
from models.materials_observation_outcomes_v1 import upgrade_statements, downgrade_statements

revision='0099_materials_observations'
down_revision='0098_materials_claim_outcomes'
branch_labels=None
depends_on=None


def upgrade():
    for sql in upgrade_statements():op.execute(sa.DDL(sql.replace('%','%%')))


def downgrade():
    for sql in downgrade_statements():op.execute(sa.DDL(sql.replace('%','%%')))
