"""Frozen additive shadow-import specification for migration 0053.

Import snapshots are verified database exports, not source-publication versions
or approved ML releases. Interpretation JSON is a pending shadow proposal, never
a second canonical Tc target. No legacy schema or result identity is rewritten.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = (
    "research_import_snapshots", "research_import_occurrences", "research_import_revisions",
    "research_import_memberships", "research_import_receipts",
)
IMMUTABILITY_FUNCTION = "sclib_research_import_immutable_v1"


def register(metadata: sa.MetaData) -> dict[str, sa.Table]:
    """Register new tables only; existing declarations must share metadata."""
    tables = {}

    def col(name, kind, *, required=False, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def uid(name, target=None, *, required=False):
        args = [sa.ForeignKey(f"{target}.id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=not required)

    def obj(name):
        return col(name, JSONB, required=True)

    def check(expression, name):
        return sa.CheckConstraint(expression, name=f"ck_ri53_{name}")

    def table(name, *items):
        checks = []
        for item in items:
            if not isinstance(item, sa.Column):
                continue
            if item.name.endswith("sha256"):
                checks.append(check(
                    f"{item.name} IS NULL OR {item.name} ~ '^[0-9a-f]{{64}}$'", f"{name}_{item.name}",
                ))
            if isinstance(item.type, JSONB) and item.name != "raw_records":
                checks.append(check(f"jsonb_typeof({item.name})='object'", f"{name}_{item.name}"))
        value = sa.Table(
            name, metadata, uid("id", required=True), *items,
            col("record_sha256", sa.String(64), required=True),
            check("record_sha256 ~ '^[0-9a-f]{64}$'", f"{name}_record_sha256"),
            *checks, col("created_at", sa.DateTime(timezone=True), required=True, default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        sa.event.listen(value, "after_create", sa.DDL(f"""
            CREATE OR REPLACE FUNCTION {IMMUTABILITY_FUNCTION}() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              RAISE EXCEPTION 'research import history is append-only: %%', TG_TABLE_NAME
                USING ERRCODE = '55000';
            END $$
        """).execute_if(dialect="postgresql"))
        sa.event.listen(value, "after_create", sa.DDL(f"""
            CREATE TRIGGER {name}_immutable_row
            BEFORE UPDATE OR DELETE ON {name}
            FOR EACH ROW EXECUTE FUNCTION {IMMUTABILITY_FUNCTION}()
        """).execute_if(dialect="postgresql"))
        sa.event.listen(value, "after_create", sa.DDL(f"""
            CREATE TRIGGER {name}_immutable_truncate
            BEFORE TRUNCATE ON {name}
            FOR EACH STATEMENT EXECUTE FUNCTION {IMMUTABILITY_FUNCTION}()
        """).execute_if(dialect="postgresql"))
        tables[name] = value

    table(
        "research_import_snapshots",
        col("export_manifest_sha256", sa.String(64), required=True), obj("export_manifest"),
        col("dataset_version", sa.String(50), required=True),
        col("site_git_sha", sa.String(40), required=True),
        col("database_watermark", sa.DateTime(timezone=True), required=True),
        col("source_alembic_revision", sa.String(100), required=True),
        col("schema_version", sa.String(50), required=True),
        *[col(name, sa.BigInteger, required=True) for name in (
            "paper_count", "material_count", "chunk_count", "input_record_count",
        )],
        col("license_manifest_sha256", sa.String(64), required=True),
        col("status", sa.String(20), required=True, default="captured"),
        sa.UniqueConstraint("export_manifest_sha256", name="uq_ri53_export_manifest"),
        check("site_git_sha ~ '^[0-9a-f]{40}$'", "snapshot_git_sha"),
        check("isfinite(database_watermark)", "snapshot_watermark"),
        check("btrim(dataset_version)<>'' AND btrim(source_alembic_revision)<>'' AND btrim(schema_version)<>''", "snapshot_labels"),
        check("paper_count>=0 AND material_count>=0 AND chunk_count>=0 AND input_record_count>=0", "snapshot_counts"),
        check("status='captured'", "snapshot_status"),
    )
    table(
        "research_import_occurrences",
        # Stable historical claim identity reference, even before a v1 claim
        # exists. Deliberately no material_claims FK or insertion requirement.
        uid("legacy_claim_id", required=True),
        sa.Column("material_id", sa.String(100), sa.ForeignKey(
            "materials.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
        sa.Column("paper_id", sa.String(100), sa.ForeignKey(
            "papers.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
        uid("work_id", "works", required=True),
        col("source_record_sha256", sa.String(64), required=True),
        obj("raw_record"), obj("source_locator"),
        col("identity_version", sa.String(100), required=True),
        sa.UniqueConstraint("legacy_claim_id", name="uq_ri53_legacy_claim"),
        sa.UniqueConstraint("id", "source_record_sha256", name="uq_ri53_occurrence_source"),
        check("id=legacy_claim_id", "occurrence_legacy_identity"),
        check("btrim(identity_version)<>''", "occurrence_identity_version"),
        sa.Index("idx_ri53_occurrence_material", "material_id"),
    )
    table(
        "research_import_revisions",
        uid("occurrence_id", "research_import_occurrences", required=True),
        col("revision_number", sa.Integer, required=True),
        uid("supersedes_id"), col("supersedes_revision_number", sa.Integer),
        col("mapper_version", sa.String(100), required=True),
        col("interpretation_sha256", sa.String(64), required=True), obj("payload"),
        col("review_status", sa.String(20), required=True, default="pending"),
        col("scientific_acceptance", sa.Boolean, required=True, default=sa.false()),
        sa.UniqueConstraint("occurrence_id", "revision_number", name="uq_ri53_occurrence_revision"),
        sa.UniqueConstraint("id", "occurrence_id", name="uq_ri53_revision_occurrence"),
        sa.UniqueConstraint("id", "occurrence_id", "revision_number", name="uq_ri53_exact_revision"),
        sa.UniqueConstraint("supersedes_id", name="uq_ri53_revision_successor"),
        sa.UniqueConstraint("occurrence_id", "mapper_version", "interpretation_sha256", name="uq_ri53_interpretation_content"),
        sa.ForeignKeyConstraint(
            ["supersedes_id", "occurrence_id", "supersedes_revision_number"],
            ["research_import_revisions.id", "research_import_revisions.occurrence_id", "research_import_revisions.revision_number"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_ri53_exact_predecessor",
        ),
        check("revision_number>=1 AND ((revision_number=1 AND supersedes_id IS NULL AND supersedes_revision_number IS NULL) "
              "OR (revision_number>1 AND supersedes_id IS NOT NULL AND supersedes_revision_number IS NOT NULL "
              "AND supersedes_id<>id AND supersedes_revision_number=revision_number-1))", "revision_chain"),
        check("btrim(mapper_version)<>''", "revision_mapper"),
        check("review_status='pending' AND scientific_acceptance=false", "revision_pending"),
        check("NOT (payload ? 'validity_status') OR payload->>'validity_status' IN ('pending','disputed','retracted','excluded')", "revision_payload_validity"),
        sa.Index("idx_ri53_revision_occurrence", "occurrence_id"),
    )
    table(
        "research_import_memberships",
        uid("snapshot_id", "research_import_snapshots", required=True),
        uid("occurrence_id", required=True), uid("revision_id", required=True),
        col("source_record_sha256", sa.String(64), required=True),
        col("raw_records", JSONB, required=True),
        sa.ForeignKeyConstraint(["occurrence_id", "source_record_sha256"],
                                ["research_import_occurrences.id", "research_import_occurrences.source_record_sha256"],
                                ondelete="RESTRICT", onupdate="RESTRICT", name="fk_ri53_membership_source"),
        sa.ForeignKeyConstraint(["revision_id", "occurrence_id"],
                                ["research_import_revisions.id", "research_import_revisions.occurrence_id"],
                                ondelete="RESTRICT", onupdate="RESTRICT", name="fk_ri53_membership_revision"),
        sa.UniqueConstraint("snapshot_id", "occurrence_id", "revision_id", name="uq_ri53_membership"),
        check("jsonb_typeof(raw_records)='array' AND jsonb_array_length(raw_records)>0", "membership_raw_records"),
        check("NOT jsonb_path_exists(raw_records, '$[*] ? (@.type() != \"object\" || "
              "!exists(@.record_ordinal) || !exists(@.raw_record) || "
              "@.record_ordinal.type() != \"number\" || @.raw_record.type() != \"object\" || "
              "@.record_ordinal < 0 || @.record_ordinal.floor() != @.record_ordinal)')", "membership_raw_record_items"),
        sa.Index("idx_ri53_membership_snapshot", "snapshot_id"),
    )
    table(
        "research_import_receipts",
        uid("snapshot_id", "research_import_snapshots", required=True),
        col("plan_manifest_sha256", sa.String(64), required=True),
        col("loader_version", sa.String(100), required=True),
        uid("approval_artifact_id", required=True),
        col("approval_artifact_kind", sa.String(30), required=True, default="review"),
        col("approval_artifact_sha256", sa.String(64), required=True),
        obj("selection_manifest"), obj("accounting"),
        col("completed_at", sa.DateTime(timezone=True), required=True),
        sa.ForeignKeyConstraint(["approval_artifact_id", "approval_artifact_kind"],
                                ["evidence_artifacts.id", "evidence_artifacts.kind"],
                                ondelete="RESTRICT", onupdate="RESTRICT", name="fk_ri53_receipt_review_kind"),
        sa.UniqueConstraint("plan_manifest_sha256", name="uq_ri53_receipt_plan"),
        check("approval_artifact_kind='review'", "receipt_review_kind"),
        check("btrim(loader_version)<>'' AND isfinite(completed_at)", "receipt_labels"),
        sa.Index("idx_ri53_receipt_snapshot", "snapshot_id"),
    )
    return tables
