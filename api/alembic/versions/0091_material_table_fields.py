"""Private source-table cell bindings and opt-in pending field cases."""
import sqlalchemy as sa

from alembic import op
from models.material_table_fields_v1 import downgrade_statements, upgrade_statements

revision = "0091_material_table_fields"
down_revision = "0090_discovery_calculations"
branch_labels = None
depends_on = None


def upgrade():
    for sql in upgrade_statements():
        op.execute(sa.DDL(sql.replace("%", "%%")))


def downgrade():
    op.execute("LOCK TABLE public.source_expression_imports_v2,public.source_expression_revisions_v2,public.material_field_targets_v1,public.material_field_associations_v1,public.material_field_attempts_v1 IN ACCESS EXCLUSIVE MODE")
    for sql in downgrade_statements():
        op.execute(sa.DDL(sql.replace("%", "%%")))
