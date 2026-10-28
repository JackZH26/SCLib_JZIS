"""Adopt complete private source-scoped NER proposal relations."""
from alembic import op
from models.materials_ner_proposals_v2 import upgrade as upgrade_schema, downgrade as downgrade_schema

revision = "0100_materials_ner_relations"
down_revision = "0099_materials_observations"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_schema(op.get_bind())


def downgrade():
    downgrade_schema(op.get_bind())
