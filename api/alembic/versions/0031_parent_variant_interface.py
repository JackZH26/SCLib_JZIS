"""Add parent-variant model + interface material columns.

Revision ID: 0031_parent_variant_interface
Down revision: 0030_audit_suggested_fixes

P2 A4+A5:
- parent_material_id: self-referencing FK for doping-variant → parent
  linking. Variants (YBa2Cu3O6.95) point at their parent (YBa2Cu3O7-δ)
  so the API can group them and render phase diagrams.
- variant_count: denormalized count of children, for cheap list queries.
- formula_substrate / formula_overlayer / layer_thickness_nm: interface
  material decomposition (FeSe/STO → substrate=SrTiO3, overlayer=FeSe).
"""
import sqlalchemy as sa
from alembic import op

revision = "0031_parent_variant_interface"
down_revision = "0030_audit_suggested_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Parent-variant linking
    op.add_column(
        "materials",
        sa.Column(
            "parent_material_id",
            sa.String(100),
            sa.ForeignKey("materials.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "materials",
        sa.Column("variant_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "idx_materials_parent_id",
        "materials",
        ["parent_material_id"],
        postgresql_where=sa.text("parent_material_id IS NOT NULL"),
    )

    # Interface material decomposition
    op.add_column(
        "materials",
        sa.Column("formula_substrate", sa.String(200), nullable=True),
    )
    op.add_column(
        "materials",
        sa.Column("formula_overlayer", sa.String(200), nullable=True),
    )
    op.add_column(
        "materials",
        sa.Column("layer_thickness_nm", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("materials", "layer_thickness_nm")
    op.drop_column("materials", "formula_overlayer")
    op.drop_column("materials", "formula_substrate")
    op.drop_index("idx_materials_parent_id", table_name="materials")
    op.drop_column("materials", "variant_count")
    op.drop_column("materials", "parent_material_id")
