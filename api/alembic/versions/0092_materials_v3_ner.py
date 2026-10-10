"""Materials V3 source-bound NER pilot; additive, no production backfill."""

import sqlalchemy as sa

from alembic import op
from models.materials_v3 import TABLE_ORDER, register, registry_check

revision = "0092_materials_v3"
down_revision = "0091_material_table_fields"
branch_labels = depends_on = None


def _tables():
    metadata = sa.MetaData()
    # Referenced columns only; no changes to existing scientific table definitions.
    from sqlalchemy.dialects.postgresql import UUID

    for name in ("works", "evidence_artifacts"):
        sa.Table(name, metadata, sa.Column("id", UUID))
    for name in ("materials", "papers"):
        sa.Table(name, metadata, sa.Column("id", sa.String(100)))
    for name in ("research_samples", "research_events"):
        sa.Table(name, metadata, sa.Column("id", UUID), sa.Column("material_id", sa.String(100)))
    for name in ("event_properties", "material_claims"):
        sa.Table(name, metadata, sa.Column("id", UUID), sa.Column("event_id", UUID))
    return register(metadata)


def upgrade():
    op.drop_constraint("ck_rv2_property_registry", "event_properties", type_="check")
    op.create_check_constraint("ck_rv2_property_registry", "event_properties", registry_check())
    op.drop_constraint("ck_rv2_property_nonnegative", "event_properties", type_="check")
    op.create_check_constraint(
        "ck_rv2_property_nonnegative",
        "event_properties",
        "property_key IN ('formation_energy_per_atom','phonon_min_frequency') OR (registry_version='materials-properties/3.0' AND property_key='strain') OR ((value IS NULL OR value>=0) AND (lower IS NULL OR lower>=0) AND (upper IS NULL OR upper>=0))",
    )
    tables = _tables()
    for name in TABLE_ORDER:
        tables[name].create(op.get_bind())
    # Source/candidate/selection history cannot be rewritten by a retry or a model.
    op.execute("""CREATE FUNCTION mv3_immutable_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Materials V3 history is append-only'; END $$""")
    for name in TABLE_ORDER:
        op.execute(
            f"CREATE TRIGGER mv3_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION mv3_immutable_history()"
        )
        op.execute(
            f"CREATE TRIGGER mv3_no_truncate BEFORE TRUNCATE ON {name} FOR EACH STATEMENT EXECUTE FUNCTION mv3_immutable_history()"
        )


def downgrade():
    # Rollback is a read-path flag/snapshot switch. Do not erase populated history.
    # Lock before the empty checks so an importer cannot insert retained rows
    # between those checks and the eventual table drops.
    op.execute(f"LOCK TABLE {', '.join(TABLE_ORDER)}, event_properties IN ACCESS EXCLUSIVE MODE")
    for name in TABLE_ORDER:
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM {name})")).scalar():
            raise RuntimeError("Materials V3 downgrade refused: retained history exists")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM event_properties WHERE registry_version='materials-properties/3.0')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Materials V3 downgrade refused: V3 scientific properties exist")
    for name in reversed(TABLE_ORDER):
        _tables()[name].drop(op.get_bind())
    # Metadata-only owned rehearsals may omit the migration-created function.
    # All V3 relations and properties have already been locked and checked empty.
    op.execute("DROP FUNCTION IF EXISTS public.mv3_immutable_history()")
    from models.research_schema_v2 import PROPERTY_UNITS

    old = " OR ".join(f"(property_key='{k}' AND unit='{v}')" for k, v in PROPERTY_UNITS.items())
    op.drop_constraint("ck_rv2_property_registry", "event_properties", type_="check")
    op.create_check_constraint(
        "ck_rv2_property_registry", "event_properties", f"registry_version='rv2/1' AND ({old})"
    )
    op.drop_constraint("ck_rv2_property_nonnegative", "event_properties", type_="check")
    op.create_check_constraint(
        "ck_rv2_property_nonnegative",
        "event_properties",
        "property_key IN ('formation_energy_per_atom','phonon_min_frequency') OR ((value IS NULL OR value>=0) AND (lower IS NULL OR lower>=0) AND (upper IS NULL OR upper>=0))",
    )
