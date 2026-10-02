"""Private source-scoped Tc metadata fidelity requests and decisions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.material_field_review_v1 import FUNCTION_SIGNATURES, TABLE_ORDER, register

revision = "0085_material_field_review"
down_revision = "0084_material_field_cases"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    for name in ("users", "research_role_grants", "materials", "papers", "works", "paper_work_map",
                 "source_lifecycle_events", "material_field_targets_v1", "material_field_associations_v1",
                 "source_expression_revisions_v2", "source_expression_captures_v2", "source_expression_imports_v2"):
        sa.Table(name, metadata, sa.Column("id", sa.String(100) if name in {"materials", "papers"} else UUID))
    return register(metadata)


def upgrade():
    for table in _tables().values():
        table.create(op.get_bind())


def downgrade():
    op.execute("LOCK TABLE "+",".join("public."+n for n in TABLE_ORDER)+" IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name} LIMIT 1)")).scalar_one():
            raise RuntimeError("Refusing downgrade: retained material field review history")
    for table in reversed(list(_tables().values())):
        table.drop(op.get_bind())
    for name, arguments in reversed(FUNCTION_SIGNATURES):
        op.execute(f"DROP FUNCTION public.{name}({arguments})")
