"""Add the ML Foundation v1 lineage and typed-claim schema.

Revision ID: 0044_ml_foundation
Revises: 0043_chunks_fts
Create date: 2026-08-20

The migration is additive.  Existing ``materials.records`` data and every
legacy API column remain untouched while the typed claim pipeline is brought
up in shadow mode.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0044_ml_foundation"
down_revision = "0043_chunks_fts"
branch_labels = None
depends_on = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def upgrade() -> None:
    # Composition enrichment is nullable so all 11k+ existing materials stay
    # valid until the versioned enrichment job processes them.
    op.add_column("materials", sa.Column("composition_status", sa.String(20)))
    op.add_column(
        "materials",
        sa.Column("composition_data", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column(
        "materials",
        sa.Column("composition_enriched_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint(
        "ck_materials_composition_status",
        "materials",
        "composition_status IS NULL OR composition_status IN "
        "('exact', 'variable', 'interface', 'mixture', 'invalid')",
    )
    op.create_check_constraint(
        "ck_materials_composition_data_object",
        "materials",
        "composition_data IS NULL OR jsonb_typeof(composition_data) = 'object'",
    )
    op.create_check_constraint(
        "ck_materials_composition_enriched_status",
        "materials",
        "composition_enriched_at IS NULL OR composition_status IS NOT NULL",
    )
    op.create_index(
        "idx_materials_composition_status",
        "materials",
        ["composition_status"],
    )

    op.create_table(
        "source_snapshots",
        _uuid_pk(),
        sa.Column("dataset_version", sa.String(50), nullable=False),
        sa.Column("site_git_sha", sa.String(40)),
        sa.Column("database_watermark", sa.DateTime(timezone=True)),
        sa.Column("paper_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("material_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("license_manifest_sha256", sa.String(64)),
        sa.Column("status", sa.String(20), nullable=False, server_default="building"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('building', 'validated', 'frozen', 'failed')",
            name="ck_source_snapshots_status",
        ),
        sa.CheckConstraint(
            "paper_count >= 0 AND material_count >= 0 AND chunk_count >= 0",
            name="ck_source_snapshots_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "manifest_sha256 IS NULL OR length(manifest_sha256) = 64",
            name="ck_source_snapshots_manifest_hash",
        ),
        sa.CheckConstraint(
            "license_manifest_sha256 IS NULL OR length(license_manifest_sha256) = 64",
            name="ck_source_snapshots_license_hash",
        ),
        sa.CheckConstraint(
            "status <> 'frozen' OR (manifest_sha256 IS NOT NULL AND frozen_at IS NOT NULL)",
            name="ck_source_snapshots_frozen_manifest",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_source_snapshots_metadata_object",
        ),
        sa.UniqueConstraint("manifest_sha256", name="uq_source_snapshots_manifest"),
    )
    op.create_index(
        "idx_source_snapshots_version",
        "source_snapshots",
        ["dataset_version"],
    )
    op.create_index(
        "idx_source_snapshots_status_created",
        "source_snapshots",
        ["status", "created_at"],
    )

    op.create_table(
        "works",
        _uuid_pk(),
        sa.Column("canonical_title", sa.Text(), nullable=False),
        sa.Column("canonical_doi", sa.String(200)),
        sa.Column("canonical_arxiv_id", sa.String(20)),
        sa.Column(
            "publication_status",
            sa.String(20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("available_at", sa.Date()),
        sa.Column(
            "identity_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "publication_status IN ('active', 'retracted', 'withdrawn', 'corrected', 'unknown')",
            name="ck_works_publication_status",
        ),
        sa.CheckConstraint(
            "btrim(canonical_title) <> ''",
            name="ck_works_canonical_title_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(identity_metadata) = 'object'",
            name="ck_works_identity_metadata_object",
        ),
    )
    op.create_index(
        "uq_works_canonical_doi",
        "works",
        ["canonical_doi"],
        unique=True,
        postgresql_where=sa.text("canonical_doi IS NOT NULL"),
    )
    op.create_index(
        "uq_works_canonical_arxiv",
        "works",
        ["canonical_arxiv_id"],
        unique=True,
        postgresql_where=sa.text("canonical_arxiv_id IS NOT NULL"),
    )
    op.create_index("idx_works_available_at", "works", ["available_at"])

    op.create_table(
        "paper_work_map",
        sa.Column("paper_id", sa.String(100), primary_key=True),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "relation_type",
            sa.String(30),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("match_method", sa.String(30), nullable=False),
        sa.Column("match_score", sa.Float()),
        sa.Column(
            "review_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "relation_type IN "
            "('canonical_version', 'preprint', 'published_version', "
            "'supplement', 'correction', 'unknown')",
            name="ck_paper_work_map_relation_type",
        ),
        sa.CheckConstraint(
            "match_method IN "
            "('exact_doi', 'related_paper', 'exact_arxiv', 'metadata', 'manual', 'singleton')",
            name="ck_paper_work_map_match_method",
        ),
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="ck_paper_work_map_match_score",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_paper_work_map_review_status",
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_paper_work_map_work", "paper_work_map", ["work_id"])
    op.create_index("idx_paper_work_map_review", "paper_work_map", ["review_status"])

    op.create_table(
        "material_claims",
        _uuid_pk(),
        sa.Column("material_id", sa.String(100), nullable=False),
        sa.Column("paper_id", sa.String(100)),
        sa.Column("work_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_type", sa.String(30), nullable=False, server_default="tc"),
        sa.Column("evidence_role", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("result_status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column(
            "value_relation",
            sa.String(20),
            nullable=False,
            server_default="unreported",
        ),
        sa.Column("value_kelvin", sa.Float()),
        sa.Column("value_lower_kelvin", sa.Float()),
        sa.Column("value_upper_kelvin", sa.Float()),
        sa.Column("tc_definition", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column(
            "pressure_state",
            sa.String(20),
            nullable=False,
            server_default="not_reported",
        ),
        sa.Column("pressure_gpa", sa.Float()),
        sa.Column("minimum_temperature_k", sa.Float()),
        sa.Column("magnetic_field_t", sa.Float()),
        sa.Column("measurement_method", sa.String(100)),
        sa.Column("sample_form", sa.String(50)),
        sa.Column("structure_phase_raw", sa.String(200)),
        sa.Column("doping_raw", sa.String(200)),
        sa.Column("sample_label", sa.String(100)),
        sa.Column("source_kind", sa.String(30), nullable=False, server_default="legacy"),
        sa.Column("chunk_id", sa.String(200)),
        sa.Column(
            "source_locator",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("extraction_confidence", sa.Float()),
        sa.Column("relation_confidence", sa.Float()),
        sa.Column(
            "validity_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "raw_record",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "extraction_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_record_hash", sa.String(64), nullable=False),
        sa.Column("semantic_fingerprint", sa.String(64)),
        sa.Column("duplicate_cluster_id", sa.String(64)),
        sa.Column("available_at", sa.Date()),
        sa.Column("extractor_version", sa.String(80), nullable=False),
        sa.Column("ingestion_run_id", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "property_type IN ('tc', 'non_transition')",
            name="ck_material_claims_property_type",
        ),
        sa.CheckConstraint(
            "evidence_role IN ('primary_experimental', 'primary_theoretical', 'cited', 'unknown')",
            name="ck_material_claims_evidence_role",
        ),
        sa.CheckConstraint(
            "result_status IN ('observed', 'not_detected', 'inconclusive', 'unknown')",
            name="ck_material_claims_result_status",
        ),
        sa.CheckConstraint(
            "value_relation IN ('exact', 'interval', 'lt', 'le', 'gt', 'ge', 'unreported')",
            name="ck_material_claims_value_relation",
        ),
        sa.CheckConstraint(
            "tc_definition IN "
            "('onset', 'zero_resistance', 'midpoint', 'diamagnetic', "
            "'heat_capacity', 'unknown')",
            name="ck_material_claims_tc_definition",
        ),
        sa.CheckConstraint(
            "pressure_state IN ('explicit_ambient', 'reported', 'not_reported', 'ambiguous')",
            name="ck_material_claims_pressure_state",
        ),
        sa.CheckConstraint(
            "source_kind IN ('prose', 'abstract', 'table', 'synthetic_fact', 'legacy')",
            name="ck_material_claims_source_kind",
        ),
        sa.CheckConstraint(
            "validity_status IN ('accepted', 'pending', 'disputed', 'retracted', 'excluded')",
            name="ck_material_claims_validity_status",
        ),
        sa.CheckConstraint(
            "(value_kelvin IS NULL OR (value_kelvin >= 0 "
            "AND value_kelvin < 'Infinity'::float8)) AND "
            "(value_lower_kelvin IS NULL OR (value_lower_kelvin >= 0 "
            "AND value_lower_kelvin < 'Infinity'::float8)) AND "
            "(value_upper_kelvin IS NULL OR (value_upper_kelvin >= 0 "
            "AND value_upper_kelvin < 'Infinity'::float8)) AND "
            "(value_lower_kelvin IS NULL OR value_upper_kelvin IS NULL "
            "OR value_lower_kelvin <= value_upper_kelvin)",
            name="ck_material_claims_value_bounds",
        ),
        sa.CheckConstraint(
            "((value_relation = 'exact' AND value_kelvin IS NOT NULL "
            "AND value_lower_kelvin IS NULL AND value_upper_kelvin IS NULL) OR "
            "(value_relation = 'interval' AND value_kelvin IS NULL "
            "AND value_lower_kelvin IS NOT NULL AND value_upper_kelvin IS NOT NULL) OR "
            "(value_relation IN ('lt', 'le') AND value_kelvin IS NULL "
            "AND value_lower_kelvin IS NULL AND value_upper_kelvin IS NOT NULL) OR "
            "(value_relation IN ('gt', 'ge') AND value_kelvin IS NULL "
            "AND value_lower_kelvin IS NOT NULL AND value_upper_kelvin IS NULL) OR "
            "(value_relation = 'unreported' AND value_kelvin IS NULL "
            "AND value_lower_kelvin IS NULL AND value_upper_kelvin IS NULL))",
            name="ck_material_claims_value_shape",
        ),
        sa.CheckConstraint(
            "((pressure_state = 'explicit_ambient' AND pressure_gpa = 0) OR "
            "(pressure_state = 'reported' AND pressure_gpa IS NOT NULL) OR "
            "(pressure_state = 'not_reported' AND pressure_gpa IS NULL) OR "
            "pressure_state = 'ambiguous')",
            name="ck_material_claims_pressure_semantics",
        ),
        sa.CheckConstraint(
            "pressure_gpa IS NULL OR (pressure_gpa >= 0 AND pressure_gpa < 'Infinity'::float8)",
            name="ck_material_claims_pressure_nonnegative",
        ),
        sa.CheckConstraint(
            "minimum_temperature_k IS NULL OR (minimum_temperature_k >= 0 "
            "AND minimum_temperature_k < 'Infinity'::float8)",
            name="ck_material_claims_minimum_temperature",
        ),
        sa.CheckConstraint(
            "magnetic_field_t IS NULL OR (magnetic_field_t >= 0 "
            "AND magnetic_field_t < 'Infinity'::float8)",
            name="ck_material_claims_magnetic_field",
        ),
        sa.CheckConstraint(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="ck_material_claims_extraction_confidence",
        ),
        sa.CheckConstraint(
            "relation_confidence IS NULL OR "
            "(relation_confidence >= 0 AND relation_confidence <= 1)",
            name="ck_material_claims_relation_confidence",
        ),
        sa.CheckConstraint(
            "validity_status <> 'accepted' OR result_status <> 'observed' "
            "OR value_relation <> 'unreported'",
            name="ck_material_claims_accepted_observed_value",
        ),
        sa.CheckConstraint(
            "validity_status <> 'accepted' OR result_status <> 'not_detected' "
            "OR minimum_temperature_k IS NOT NULL",
            name="ck_material_claims_accepted_negative_tmin",
        ),
        sa.CheckConstraint(
            "length(source_record_hash) = 64",
            name="ck_material_claims_source_hash",
        ),
        sa.CheckConstraint(
            "semantic_fingerprint IS NULL OR length(semantic_fingerprint) = 64",
            name="ck_material_claims_semantic_hash",
        ),
        sa.CheckConstraint(
            "duplicate_cluster_id IS NULL OR length(duplicate_cluster_id) = 64",
            name="ck_material_claims_duplicate_cluster_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_locator) = 'object' "
            "AND jsonb_typeof(raw_record) = 'object' "
            "AND jsonb_typeof(extraction_metadata) = 'object'",
            name="ck_material_claims_json_objects",
        ),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["source_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "material_id",
            "source_record_hash",
            name="uq_material_claims_material_source_hash",
        ),
    )
    op.create_index(
        "idx_material_claims_material_validity",
        "material_claims",
        ["material_id", "validity_status"],
    )
    op.create_index("idx_material_claims_paper", "material_claims", ["paper_id"])
    op.create_index("idx_material_claims_work", "material_claims", ["work_id"])
    op.create_index(
        "idx_material_claims_source_snapshot",
        "material_claims",
        ["source_snapshot_id"],
    )
    op.create_index(
        "idx_material_claims_semantic_fingerprint",
        "material_claims",
        ["semantic_fingerprint"],
        postgresql_where=sa.text("semantic_fingerprint IS NOT NULL"),
    )
    op.create_index(
        "idx_material_claims_duplicate_cluster",
        "material_claims",
        ["duplicate_cluster_id"],
        postgresql_where=sa.text("duplicate_cluster_id IS NOT NULL"),
    )
    op.create_index(
        "idx_material_claims_available_at",
        "material_claims",
        ["available_at"],
    )

    op.create_table(
        "claim_qc",
        _uuid_pk(),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "automated_checks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "quality_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "review_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewer_notes", sa.Text()),
        sa.Column("is_gold", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("qc_version", sa.String(40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'needs_review', 'approved', 'rejected')",
            name="ck_claim_qc_review_status",
        ),
        sa.CheckConstraint(
            "NOT is_gold OR (review_status = 'approved' AND reviewed_at IS NOT NULL)",
            name="ck_claim_qc_gold_reviewed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(automated_checks) = 'object' AND jsonb_typeof(quality_flags) = 'array'",
            name="ck_claim_qc_json_shapes",
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["material_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("claim_id", name="uq_claim_qc_claim_id"),
    )
    op.create_index("idx_claim_qc_review_status", "claim_qc", ["review_status"])
    op.create_index(
        "idx_claim_qc_gold",
        "claim_qc",
        ["is_gold"],
        postgresql_where=sa.text("is_gold IS TRUE"),
    )

    op.create_table(
        "ml_dataset_snapshots",
        _uuid_pk(),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="building"),
        sa.Column("label_policy_version", sa.String(40), nullable=False),
        sa.Column("feature_schema_version", sa.String(40), nullable=False),
        sa.Column("split_ruleset_version", sa.String(40), nullable=False),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("row_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("data_card_uri", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('building', 'validated', 'frozen', 'failed')",
            name="ck_ml_dataset_snapshots_status",
        ),
        sa.CheckConstraint(
            "row_count >= 0",
            name="ck_ml_dataset_snapshots_row_count",
        ),
        sa.CheckConstraint(
            "manifest_sha256 IS NULL OR length(manifest_sha256) = 64",
            name="ck_ml_dataset_snapshots_manifest_hash",
        ),
        sa.CheckConstraint(
            "status <> 'frozen' OR (manifest_sha256 IS NOT NULL AND frozen_at IS NOT NULL)",
            name="ck_ml_dataset_snapshots_frozen_manifest",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(filters) = 'object'",
            name="ck_ml_dataset_snapshots_filters_object",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["source_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "name",
            "version",
            name="uq_ml_dataset_snapshots_name_version",
        ),
        sa.UniqueConstraint(
            "manifest_sha256",
            name="uq_ml_dataset_snapshots_manifest",
        ),
    )
    op.create_index(
        "idx_ml_dataset_snapshots_source",
        "ml_dataset_snapshots",
        ["source_snapshot_id"],
    )
    op.create_index(
        "idx_ml_dataset_snapshots_status_created",
        "ml_dataset_snapshots",
        ["status", "created_at"],
    )

    op.create_table(
        "ml_examples",
        _uuid_pk(),
        sa.Column("dataset_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("example_key", sa.String(100), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_id", sa.String(100), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True)),
        sa.Column("split", sa.String(20), nullable=False),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column(
            "label_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("work_group", sa.String(100), nullable=False),
        sa.Column("material_group", sa.String(100), nullable=False),
        sa.Column("parent_series_group", sa.String(100)),
        sa.Column("chemical_system_group", sa.String(200)),
        sa.Column("duplicate_group", sa.String(100), nullable=False),
        sa.Column("available_at", sa.Date()),
        sa.Column("assignment_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name="ck_ml_examples_split",
        ),
        sa.CheckConstraint(
            "task_type IN ('tc_regression', 'superconductivity_classification')",
            name="ck_ml_examples_task_type",
        ),
        sa.CheckConstraint(
            "length(assignment_hash) = 64",
            name="ck_ml_examples_assignment_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(label_data) = 'object'",
            name="ck_ml_examples_label_data_object",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_snapshot_id"],
            ["ml_dataset_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["material_claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "dataset_snapshot_id",
            "example_key",
            name="uq_ml_examples_dataset_example",
        ),
        sa.UniqueConstraint(
            "dataset_snapshot_id",
            "claim_id",
            "task_type",
            name="uq_ml_examples_dataset_claim_task",
        ),
    )
    op.create_index(
        "idx_ml_examples_dataset_split",
        "ml_examples",
        ["dataset_snapshot_id", "split"],
    )
    op.create_index(
        "idx_ml_examples_dataset_work_group",
        "ml_examples",
        ["dataset_snapshot_id", "work_group"],
    )
    op.create_index(
        "idx_ml_examples_dataset_material_group",
        "ml_examples",
        ["dataset_snapshot_id", "material_group"],
    )
    op.create_index(
        "idx_ml_examples_dataset_parent_group",
        "ml_examples",
        ["dataset_snapshot_id", "parent_series_group"],
    )
    op.create_index(
        "idx_ml_examples_dataset_duplicate_group",
        "ml_examples",
        ["dataset_snapshot_id", "duplicate_group"],
    )


def downgrade() -> None:
    # Child-first order preserves every FK dependency and makes rollback
    # deterministic.  Dropping a table also drops its local indexes/checks.
    op.drop_table("ml_examples")
    op.drop_table("ml_dataset_snapshots")
    op.drop_table("claim_qc")
    op.drop_table("material_claims")
    op.drop_table("paper_work_map")
    op.drop_table("works")
    op.drop_table("source_snapshots")

    op.drop_index("idx_materials_composition_status", table_name="materials")
    op.drop_constraint(
        "ck_materials_composition_enriched_status",
        "materials",
        type_="check",
    )
    op.drop_constraint(
        "ck_materials_composition_data_object",
        "materials",
        type_="check",
    )
    op.drop_constraint(
        "ck_materials_composition_status",
        "materials",
        type_="check",
    )
    op.drop_column("materials", "composition_enriched_at")
    op.drop_column("materials", "composition_data")
    op.drop_column("materials", "composition_status")
