"""Widen tc_max and tc_ambient from REAL (float4) to DOUBLE PRECISION (float8).

Revision ID: 0027_widen_tc_float8
Down revision: 0026_float32_cleanup

These two columns were created as REAL in the initial schema (0001),
while all later numeric columns used Float (DOUBLE PRECISION). REAL
truncates Python float64 values back to 32-bit on storage, causing
persistent artifacts like ``40.04999923706055`` even after Python-side
rounding. This migration promotes both to DOUBLE PRECISION — lossless
for all existing values since float32 is a strict subset of float64.
"""
from alembic import op
from sqlalchemy import text

revision = "0027_widen_tc_float8"
down_revision = "0026_float32_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE materials "
        "ALTER COLUMN tc_max TYPE double precision, "
        "ALTER COLUMN tc_ambient TYPE double precision;"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE materials "
        "ALTER COLUMN tc_max TYPE real, "
        "ALTER COLUMN tc_ambient TYPE real;"
    ))
