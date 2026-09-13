"""Private ML08 commitments and own-account participation; no pilot acceptance."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from models.ml_pilot_registration_v1 import FUNCTIONS, PARENTS, TABLES, register

revision = "0076_ml_pilot_registration"
down_revision = "0075_ml_run_evidence"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name in PARENTS:
        sa.Table(name, metadata, sa.Column("id", UUID))
    return register(metadata)


def upgrade():
    for relation in tables():
        relation.create(op.get_bind())


def downgrade():
    op.execute(
        "LOCK TABLE public.ml_pilot_registrations, public.ml_pilot_participants, public.ml_pilot_participation_decisions IN ACCESS EXCLUSIVE MODE"
    )
    for name in TABLES:
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name})"))
            .scalar_one()
        ):
            raise RuntimeError(
                "Refusing pilot registry downgrade: immutable registration or participant history exists"
            )
    for relation in reversed(tables()):
        relation.drop(op.get_bind())
    for name in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION public.{name}()")
