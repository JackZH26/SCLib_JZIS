"""Retain explicitly assistant-authored proposal corrections beside predictions."""
from alembic import op
from models.materials_ner_amendments_v1 import upgrade as apply, downgrade as revert

revision = '0103_materials_ner_amendments'
down_revision = '0102_materials_properties_v3'
branch_labels = None
depends_on = None

def upgrade(): apply(op.get_bind())
def downgrade(): revert(op.get_bind())
