"""Adopt the additive, private arXiv Materials NER proposal database."""
import sqlalchemy as sa

from alembic import op
from models.materials_ner_proposals_v1 import FINGERPRINT, TABLES, initialize_statements

revision = "0092_materials_ner_proposals"
down_revision = "0091_material_table_fields"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    op.execute("SELECT pg_advisory_xact_lock(924601)")
    exists = connection.execute(sa.text("SELECT to_regclass('materials_ner_v1.schema_version')")).scalar()
    if exists:
        observed = connection.execute(sa.text(
            "SELECT fingerprint FROM materials_ner_v1.schema_version WHERE version='materials-ner-proposals/1'"
        )).scalar()
        if observed != FINGERPRINT:
            raise RuntimeError("Materials NER proposal schema fingerprint mismatch")
        return
    for statement in initialize_statements():
        op.execute(sa.DDL(statement.replace("%", "%%")))


def downgrade():
    connection = op.get_bind()
    op.execute("SELECT pg_advisory_xact_lock(924601)")
    for name in TABLES:
        if connection.execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM materials_ner_v1.{name})")).scalar():
            raise RuntimeError("Refusing downgrade: retained Materials NER evidence")
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE materials_ner_v1.{name}")
    op.execute("DROP TABLE materials_ner_v1.schema_version")
    op.execute("DROP SCHEMA materials_ner_v1")
