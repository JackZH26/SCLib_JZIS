"""Round all numeric columns to 3 decimal places to fix float32 artifacts.

Revision ID: 0026_float32_cleanup
Down revision: 0025_refuted_overrides

About 38% of materials had values like ``20.299999237060547`` — artifacts
from a float32 path (likely NIMS CSV → pandas → float64 widening). This
migration rounds all numeric columns in-place. The aggregator's
``_derive_summary`` now also applies ``round(x, 3)`` going forward.
"""
from alembic import op
from sqlalchemy import text

revision = "0026_float32_cleanup"
down_revision = "0025_refuted_overrides"
branch_labels = None
depends_on = None

# All Float / REAL columns on the materials table.
_FLOAT_COLUMNS = [
    "tc_max",
    "tc_ambient",
    "hc2_tesla",
    "lambda_eph",
    "omega_log_k",
    "rho_s_mev",
    "t_cdw_k",
    "t_sdw_k",
    "t_afm_k",
    "rho_exponent",
    "doping_level",
]


def upgrade() -> None:
    bind = op.get_bind()
    for col in _FLOAT_COLUMNS:
        bind.execute(text(f"""
            UPDATE materials
            SET {col} = ROUND({col}::numeric, 3)
            WHERE {col} IS NOT NULL;
        """))


def downgrade() -> None:
    # Rounding is lossy; no meaningful downgrade.
    pass
