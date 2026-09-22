"""Own-account review declarations and protective withdrawals, not pilot approval."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.ml_pilot_attestations_v1 import FUNCTION, PARENTS, TABLE, register

revision = "0077_ml_pilot_attestations"
down_revision = "0076_ml_pilot_registration"
branch_labels = None
depends_on = None


def relation():
    metadata = sa.MetaData()
    for name in PARENTS:
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    relation().create(op.get_bind())


def downgrade():
    op.execute(f"LOCK TABLE public.{TABLE} IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{TABLE})")).scalar_one():
        raise RuntimeError(
            "Refusing pilot attestation downgrade: immutable review declaration history exists"
        )
    relation().drop(op.get_bind())
    op.execute(f"DROP FUNCTION public.{FUNCTION}()")
