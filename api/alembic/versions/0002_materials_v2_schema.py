"""materials v2 schema — structural, SC-parameter, competing-order fields

Rev ID: 0002_materials_v2
Parent: 0001_initial

Adds the v2 material columns defined in SCLib_Materials_Schema_v2.md:
  - Structure: crystal_structure was in v1 but we now populate more of it;
    add space_group, structure_phase, lattice_params
  - SC parameters: pairing_symmetry was in v1 but widened; add gap_structure,
    hc2_tesla, hc2_conditions, lambda_eph, omega_log_k, rho_s_mev
  - Competing orders: t_cdw_k, t_sdw_k, t_afm_k, rho_exponent, competing_order
  - Samples + pressure: ambient_sc, pressure_type, sample_form, substrate,
    doping_type, doping_level
  - Flags: is_topological, is_unconventional, has_competing_order,
    is_2d_or_interface, retracted, disputed

All column names are lowercase snake_case so Postgres never needs to
quote them (Postgres folds unquoted identifiers to lowercase, which
would break the Hc2_tesla / T_CDW_K camelCasing in the spec doc).

ambient_sc is backfilled from the existing records JSONB: a material
is flagged ambient_sc=true iff it has at least one record with
pressure_gpa=0 and a numeric tc_kelvin.

has_competing_order defaults to false server-side; the aggregator
flips it on per-material during re-ingest based on t_cdw_k / t_sdw_k /
t_afm_k / competing_order presence.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "0002_materials_v2"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


NEW_COLUMNS = [
    # Structure
    ("space_group",       sa.String(50),  None),
    ("structure_phase",   sa.String(50),  None),
    ("lattice_params",    JSONB,          None),
    # SC parameters
    ("gap_structure",     sa.String(50),  None),
    ("hc2_tesla",         sa.Float,       None),
    ("hc2_conditions",    sa.String(200), None),
    ("lambda_eph",        sa.Float,       None),
    ("omega_log_k",       sa.Float,       None),
    ("rho_s_mev",         sa.Float,       None),
    # Competing orders
    ("t_cdw_k",           sa.Float,       None),
    ("t_sdw_k",           sa.Float,       None),
    ("t_afm_k",           sa.Float,       None),
    ("rho_exponent",      sa.Float,       None),
    ("competing_order",   sa.String(100), None),
    # Samples + pressure
    ("ambient_sc",        sa.Boolean,     None),
    ("pressure_type",     sa.String(50),  None),
    ("sample_form",       sa.String(50),  None),
    ("substrate",         sa.String(100), None),
    ("doping_type",       sa.String(50),  None),
    ("doping_level",      sa.Float,       None),
    # Flags
    ("is_topological",       sa.Boolean, "false"),
    ("is_unconventional",    sa.Boolean, None),
    ("has_competing_order",  sa.Boolean, "false"),
    ("is_2d_or_interface",   sa.Boolean, "false"),
    ("retracted",            sa.Boolean, "false"),
    ("disputed",             sa.Boolean, "false"),
]


def upgrade() -> None:
    for name, typ, default in NEW_COLUMNS:
        kwargs = {}
        if default is not None:
            kwargs["server_default"] = sa.text(default)
        op.add_column("materials", sa.Column(name, typ, nullable=True, **kwargs))

    # Backfill ambient_sc from existing NIMS records. A record counts
    # as ambient if it has pressure_gpa == 0 (or pressure == 0 in the
    # older NIMS record shape) and a numeric tc_kelvin / tc value.
    op.execute("""
        UPDATE materials SET ambient_sc = sub.is_ambient
        FROM (
            SELECT m.id,
                   EXISTS (
                       SELECT 1
                       FROM jsonb_array_elements(m.records) r
                       WHERE COALESCE((r->>'pressure_gpa')::float, (r->>'pressure')::float, 0) = 0
                         AND COALESCE(r->>'tc_kelvin', r->>'tc') IS NOT NULL
                   ) AS is_ambient
            FROM materials m
        ) sub
        WHERE materials.id = sub.id
    """)

    # Indexes
    op.create_index(
        "idx_materials_pairing", "materials", ["pairing_symmetry"],
    )
    op.create_index(
        "idx_materials_phase", "materials", ["structure_phase"],
    )
    # Partial indexes on frequent boolean filters keep the index tiny
    # compared to full-table indexes and still serve the filtered query.
    op.create_index(
        "idx_materials_ambient",
        "materials",
        ["ambient_sc"],
        postgresql_where=sa.text("ambient_sc = true"),
    )
    op.create_index(
        "idx_materials_unconventional",
        "materials",
        ["is_unconventional"],
        postgresql_where=sa.text("is_unconventional = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_materials_unconventional", table_name="materials")
    op.drop_index("idx_materials_ambient", table_name="materials")
    op.drop_index("idx_materials_phase", table_name="materials")
    op.drop_index("idx_materials_pairing", table_name="materials")
    for name, _typ, _default in reversed(NEW_COLUMNS):
        op.drop_column("materials", name)
