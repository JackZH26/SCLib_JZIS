"""Publish immutable corpus partitions and activate their complete root."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op
from models.index_corpus_v1 import TABLE_ORDER, register, remove_statements

revision = "0080_index_corpus"
down_revision = "0079_retained_legacy"
branch_labels = depends_on = None


def upgrade():
    metadata = sa.MetaData()
    sa.Table("index_generations", metadata, sa.Column("id", UUID))
    sa.Table(
        "index_generation_members",
        metadata,
        sa.Column("generation_id", UUID),
        sa.Column("chunk_key", sa.String(200)),
        sa.Column("vector_id", sa.String(120)),
    )
    for name in ("legacy_index_windows", "index_active_pointer"):
        sa.Table(name, metadata)
    tables = register(metadata)
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())


def downgrade():
    op.execute(
        "LOCK TABLE "
        + ",".join("public." + name for name in (*TABLE_ORDER, "index_generations"))
        + " IN ACCESS EXCLUSIVE MODE"
    )
    for name in TABLE_ORDER:
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM public.{name})"))
            .scalar_one()
        ):
            raise RuntimeError("Refusing destructive corpus history downgrade")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM index_generations WHERE expected_member_count>1000)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing incompatible corpus root downgrade")
    for statement in remove_statements():
        op.execute(statement)
    for name in reversed(TABLE_ORDER):
        op.execute(f"DROP TABLE public.{name}")
    op.execute("ALTER TABLE public.index_generations DROP CONSTRAINT ck_ig62_generation")
    op.execute(
        "ALTER TABLE public.index_generations ADD CONSTRAINT ck_ig62_generation CHECK "
        "(btrim(logical_index)<>'' AND expected_member_count BETWEEN 1 AND 1000 AND manifest_sha256 ~ '^[0-9a-f]{64}$')"
    )
