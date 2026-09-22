"""Frozen additive specification for migration 0052; do not edit after release.

These are source-version witnesses, not DB-export snapshots or scientific
approval. Old papers, works, claims and dates are neither rewritten nor merged.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = ("source_revisions", "source_captures", "claim_source_occurrences")
CLAIM_WORK_UNIQUE = "uq_sp52_claim_work"
IMMUTABILITY_FUNCTION = "sclib_source_provenance_immutable_v1"


def register(metadata: sa.MetaData) -> dict[str, sa.Table]:
    claims = metadata.tables["material_claims"]
    if CLAIM_WORK_UNIQUE not in {item.name for item in claims.constraints}:
        claims.append_constraint(sa.UniqueConstraint("id", "work_id", name=CLAIM_WORK_UNIQUE))
    tables = {}

    def col(name, kind, *, required=False, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def uid(name, target=None, *, required=False):
        args = [sa.ForeignKey(f"{target}.id", ondelete="RESTRICT", onupdate="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=not required)

    def check(expression, name):
        return sa.CheckConstraint(expression, name=f"ck_sp52_{name}")

    def table(name, *items):
        checks = []
        for item in items:
            if isinstance(item, sa.Column) and item.name.endswith("sha256"):
                checks.append(check(
                    f"{item.name} IS NULL OR {item.name} ~ '^[0-9a-f]{{64}}$'", f"{name}_{item.name}",
                ))
        value = sa.Table(
            name, metadata, uid("id", required=True), *items, *checks,
            col("created_at", sa.DateTime(timezone=True), required=True, default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        # Same triggers in metadata-created disposable schemas and migrations.
        sa.event.listen(value, "after_create", sa.DDL(f"""
            CREATE OR REPLACE FUNCTION {IMMUTABILITY_FUNCTION}() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
              RAISE EXCEPTION 'source provenance is append-only: %%', TG_TABLE_NAME
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
        "source_revisions",
        sa.Column("paper_id", sa.String(100), sa.ForeignKey(
            "papers.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False),
        uid("work_id", "works"),
        col("revision_key", sa.String(160), required=True),
        col("provider_revision", sa.String(160)),
        col("version_status", sa.String(20), required=True, default="unresolved"),
        col("source_version_public_at", sa.DateTime(timezone=True)),
        col("availability_status", sa.String(20), required=True, default="unknown"),
        col("availability_basis", sa.String(100), required=True, default="unknown"),
        col("metadata_sha256", sa.String(64), required=True),
        col("record_sha256", sa.String(64), required=True),
        sa.UniqueConstraint("paper_id", "revision_key", name="uq_sp52_paper_revision"),
        sa.UniqueConstraint("paper_id", "provider_revision", name="uq_sp52_paper_provider_revision"),
        sa.UniqueConstraint("id", "work_id", name="uq_sp52_revision_work"),
        check("btrim(revision_key)<>''", "revision_key"),
        check("version_status IN ('pinned','unresolved')", "version_status"),
        check("version_status<>'pinned' OR (provider_revision IS NOT NULL AND btrim(provider_revision)<>'')", "pinned_version"),
        check("availability_status IN ('known_by','unknown','uncertain')", "availability_status"),
        check("source_version_public_at IS NULL OR isfinite(source_version_public_at)", "public_time_finite"),
        check("(availability_status='known_by' AND source_version_public_at IS NOT NULL "
              "AND version_status='pinned' AND availability_basis<>'unknown') OR "
              "(availability_status IN ('unknown','uncertain') AND source_version_public_at IS NULL)", "public_time"),
    )
    table(
        "source_captures",
        uid("source_revision_id", "source_revisions", required=True),
        col("capture_key", sa.String(160), required=True),
        col("captured_at", sa.DateTime(timezone=True), required=True),
        col("bytes_sha256", sa.String(64), required=True),
        col("representation", sa.String(30), required=True),
        col("record_sha256", sa.String(64), required=True),
        sa.UniqueConstraint("source_revision_id", "capture_key", name="uq_sp52_revision_capture"),
        sa.UniqueConstraint("id", "source_revision_id", name="uq_sp52_capture_revision"),
        check("btrim(capture_key)<>''", "capture_key"),
        check("isfinite(captured_at)", "capture_time_finite"),
        check("representation IN ('arxiv_source','pdf','xml','html','source_text','abstract')", "representation"),
    )
    table(
        "claim_source_occurrences",
        uid("claim_id", required=True), uid("work_id", required=True),
        uid("source_revision_id", required=True), uid("capture_id", required=True),
        col("occurrence_key", sa.String(160), required=True),
        col("locator", JSONB, required=True),
        col("locator_sha256", sa.String(64), required=True),
        col("binding_status", sa.String(20), required=True, default="pending"),
        uid("review_artifact_id"),
        col("review_artifact_kind", sa.String(30)),
        col("review_artifact_sha256", sa.String(64)),
        col("record_sha256", sa.String(64), required=True),
        sa.ForeignKeyConstraint(["claim_id", "work_id"], ["material_claims.id", "material_claims.work_id"],
                                name="fk_sp52_occurrence_claim_work", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["source_revision_id", "work_id"], ["source_revisions.id", "source_revisions.work_id"],
                                name="fk_sp52_occurrence_revision_work", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["capture_id", "source_revision_id"], ["source_captures.id", "source_captures.source_revision_id"],
                                name="fk_sp52_occurrence_capture_revision", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["review_artifact_id", "review_artifact_kind"], ["evidence_artifacts.id", "evidence_artifacts.kind"],
                                name="fk_sp52_occurrence_review_kind", ondelete="RESTRICT", onupdate="RESTRICT", match="FULL"),
        sa.UniqueConstraint("claim_id", "capture_id", "occurrence_key", name="uq_sp52_claim_capture_occurrence"),
        check("btrim(occurrence_key)<>''", "occurrence_key"),
        check("jsonb_typeof(locator)='object' AND locator<>'{}'::jsonb", "locator"),
        check("binding_status IN ('pending','reviewed')", "binding_status"),
        check("(binding_status='pending' AND review_artifact_id IS NULL AND review_artifact_kind IS NULL "
              "AND review_artifact_sha256 IS NULL) OR (binding_status='reviewed' AND review_artifact_id IS NOT NULL "
              "AND review_artifact_kind='review' AND review_artifact_sha256 IS NOT NULL)", "review_binding"),
        sa.Index("idx_sp52_occurrence_claim", "claim_id"),
    )
    return tables
