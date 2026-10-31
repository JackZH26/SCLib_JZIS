"""Add source-scoped immutable compositions, protocols and component relations."""
import sqlalchemy as sa
from alembic import op
from models.materials_context_v1 import register_tables, preflight, guard_statements, downgrade_statements
from models.materials_context_subject_v3 import statements, FUNCTION

revision = "0096_materials_context"
down_revision = "0095_materials_adjudication"
branch_labels = None
depends_on = None


def upgrade():
    for sql in preflight():
        op.execute(sa.DDL(sql.replace("%", "%%")))
    metadata = sa.MetaData()
    # FK targets are existing canonical objects, not tables owned by this revision.
    for name in ("research_samples", "works", "evidence_artifacts"):
        sa.Table(name, metadata, sa.Column("id", sa.UUID, primary_key=True))
    for table in register_tables(metadata).values():
        table.create(op.get_bind())
    for sql in guard_statements() + statements():
        op.execute(sa.DDL(sql.replace("%", "%%")))


def downgrade():
    # Refuse retained context before removing even the read-only function.
    for sql in downgrade_statements()[:2]:
        op.execute(sa.DDL(sql.replace("%", "%%")))
    op.execute(sa.DDL(f"DROP FUNCTION public.{FUNCTION}(text,uuid)"))
    for sql in downgrade_statements()[2:]:
        op.execute(sa.DDL(sql.replace("%", "%%")))
