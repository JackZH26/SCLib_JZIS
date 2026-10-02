"""Private append-only material field targets, proposals and attempts."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op
from models.material_field_cases_v1 import FUNCTION_SIGNATURES, TABLE_ORDER, register

revision = "0084_material_field_cases"
down_revision = "0083_source_expression_intake"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    parents = ("users", "research_role_grants", "materials", "material_claims", "research_events",
        "material_states", "research_samples", "event_properties", "papers", "works", "research_publication_epoch",
        "source_lifecycle_epoch", "research_integrity_epoch", "source_expression_captures_v2",
        "source_expression_imports_v2", "source_expression_revisions_v2")
    for name in parents:
        sa.Table(name, metadata, sa.Column("id", sa.String(100) if name in {"materials", "papers"} else UUID))
    return register(metadata)


def upgrade():
    for table in _tables().values():
        table.create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE " + ",".join("public." + n for n in TABLE_ORDER) + " IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing downgrade: retained material field-case audit history")
    for table in reversed(list(_tables().values())):
        table.drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
