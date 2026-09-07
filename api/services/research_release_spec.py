"""Pinned JSON wire shape for research-closure/1.0.0 (schema 0054).

Generated once from reviewed metadata, never imported from live ORM at runtime.
User records are deliberately outside the scientific closure; reviewed_by is
an opaque actor reference, not an invitation to export credentials or profiles.
"""

import json

SPEC = json.loads(r'''{
  "chunks": {
    "fields": {
      "authors_short": {"nullable":true,"type":"VARCHAR(200)"},
      "chunk_index": {"nullable":true,"type":"SMALLINT"},
      "has_equation": {"nullable":false,"type":"BOOLEAN"},
      "has_table": {"nullable":false,"type":"BOOLEAN"},
      "id": {"nullable":false,"type":"VARCHAR(200)"},
      "material_family": {"nullable":true,"type":"VARCHAR(50)"},
      "materials_mentioned": {"nullable":false,"type":"JSONB"},
      "paper_id": {"nullable":false,"type":"VARCHAR(100)"},
      "section": {"nullable":true,"type":"VARCHAR(200)"},
      "text": {"nullable":false,"type":"TEXT"},
      "title": {"nullable":true,"type":"TEXT"},
      "year": {"nullable":true,"type":"SMALLINT"}
    },
    "fks": [
      [["paper_id"],"papers",["id"]]
    ]
  },
  "claim_qc": {
    "fields": {
      "automated_checks": {"nullable":false,"type":"JSONB"},
      "claim_id": {"nullable":false,"type":"UUID"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "is_gold": {"nullable":false,"type":"BOOLEAN"},
      "qc_version": {"nullable":false,"type":"VARCHAR(40)"},
      "quality_flags": {"nullable":false,"type":"JSONB"},
      "review_status": {"nullable":false,"type":"VARCHAR(20)"},
      "reviewed_at": {"nullable":true,"type":"DATETIME"},
      "reviewed_by": {"nullable":true,"type":"UUID"},
      "reviewer_notes": {"nullable":true,"type":"TEXT"},
      "updated_at": {"nullable":false,"type":"DATETIME"}
    },
    "fks": [
      [["claim_id"],"material_claims",["id"]]
    ]
  },
  "claim_source_occurrences": {
    "fields": {
      "binding_status": {"nullable":false,"type":"VARCHAR(20)"},
      "capture_id": {"nullable":false,"type":"UUID"},
      "claim_id": {"nullable":false,"type":"UUID"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "locator": {"nullable":false,"type":"JSONB"},
      "locator_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "occurrence_key": {"nullable":false,"type":"VARCHAR(160)"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "review_artifact_id": {"nullable":true,"type":"UUID"},
      "review_artifact_kind": {"nullable":true,"type":"VARCHAR(30)"},
      "review_artifact_sha256": {"nullable":true,"type":"VARCHAR(64)"},
      "source_revision_id": {"nullable":false,"type":"UUID"},
      "work_id": {"nullable":false,"type":"UUID"}
    },
    "fks": [
      [["capture_id","source_revision_id"],"source_captures",["id","source_revision_id"]],
      [["claim_id","work_id"],"material_claims",["id","work_id"]],
      [["review_artifact_id","review_artifact_kind"],"evidence_artifacts",["id","kind"]],
      [["source_revision_id","work_id"],"source_revisions",["id","work_id"]]
    ]
  },
  "event_evidence": {
    "fields": {
      "artifact_id": {"nullable":true,"type":"UUID"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "event_id": {"nullable":false,"type":"UUID"},
      "id": {"nullable":false,"type":"UUID"},
      "input_claim_id": {"nullable":true,"type":"UUID"},
      "input_event_id": {"nullable":true,"type":"UUID"},
      "input_property_id": {"nullable":true,"type":"UUID"},
      "link_type": {"nullable":false,"type":"VARCHAR(30)"},
      "locator": {"nullable":false,"type":"JSONB"}
    },
    "fks": [
      [["artifact_id"],"evidence_artifacts",["id"]],
      [["event_id"],"research_events",["id"]],
      [["input_claim_id","input_event_id"],"material_claims",["id","event_id"]],
      [["input_event_id"],"research_events",["id"]],
      [["input_property_id","input_event_id"],"event_properties",["id","event_id"]]
    ]
  },
  "event_properties": {
    "fields": {
      "assessment_event_type": {"nullable":true,"type":"VARCHAR(40)"},
      "component_key": {"nullable":false,"type":"VARCHAR(120)"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "event_id": {"nullable":false,"type":"UUID"},
      "id": {"nullable":false,"type":"UUID"},
      "lower": {"nullable":true,"type":"FLOAT"},
      "property_key": {"nullable":false,"type":"VARCHAR(50)"},
      "raw": {"nullable":false,"type":"JSONB"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "registry_version": {"nullable":false,"type":"VARCHAR(30)"},
      "relation": {"nullable":false,"type":"VARCHAR(20)"},
      "uncertainty": {"nullable":false,"type":"JSONB"},
      "unit": {"nullable":false,"type":"VARCHAR(40)"},
      "upper": {"nullable":true,"type":"FLOAT"},
      "value": {"nullable":true,"type":"FLOAT"}
    },
    "fks": [
      [["event_id"],"research_events",["id"]],
      [["event_id","assessment_event_type"],"research_events",["id","event_type"]]
    ]
  },
  "evidence_artifacts": {
    "fields": {
      "access": {"nullable":false,"type":"VARCHAR(20)"},
      "available_at": {"nullable":true,"type":"DATETIME"},
      "bytes_sha256": {"nullable":true,"type":"VARCHAR(64)"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "hash_status": {"nullable":false,"type":"VARCHAR(20)"},
      "id": {"nullable":false,"type":"UUID"},
      "kind": {"nullable":false,"type":"VARCHAR(30)"},
      "license": {"nullable":true,"type":"TEXT"},
      "metadata": {"nullable":false,"type":"JSONB"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "schema_version": {"nullable":false,"type":"VARCHAR(40)"},
      "source": {"nullable":false,"type":"TEXT"},
      "source_version": {"nullable":true,"type":"TEXT"},
      "uri": {"nullable":true,"type":"TEXT"}
    },
    "fks": [
    ]
  },
  "material_claims": {
    "fields": {
      "available_at": {"nullable":true,"type":"DATE"},
      "chunk_id": {"nullable":true,"type":"VARCHAR(200)"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "doping_raw": {"nullable":true,"type":"VARCHAR(200)"},
      "duplicate_cluster_id": {"nullable":true,"type":"VARCHAR(64)"},
      "event_id": {"nullable":true,"type":"UUID"},
      "evidence_role": {"nullable":false,"type":"VARCHAR(30)"},
      "extraction_confidence": {"nullable":true,"type":"FLOAT"},
      "extraction_metadata": {"nullable":false,"type":"JSONB"},
      "extractor_version": {"nullable":false,"type":"VARCHAR(80)"},
      "id": {"nullable":false,"type":"UUID"},
      "ingestion_run_id": {"nullable":true,"type":"VARCHAR(100)"},
      "interpretation_revision": {"nullable":true,"type":"INTEGER"},
      "magnetic_field_t": {"nullable":true,"type":"FLOAT"},
      "material_id": {"nullable":false,"type":"VARCHAR(100)"},
      "measurement_method": {"nullable":true,"type":"VARCHAR(100)"},
      "minimum_temperature_k": {"nullable":true,"type":"FLOAT"},
      "paper_id": {"nullable":true,"type":"VARCHAR(100)"},
      "pressure_gpa": {"nullable":true,"type":"FLOAT"},
      "pressure_state": {"nullable":false,"type":"VARCHAR(20)"},
      "property_type": {"nullable":false,"type":"VARCHAR(30)"},
      "raw_record": {"nullable":false,"type":"JSONB"},
      "relation_confidence": {"nullable":true,"type":"FLOAT"},
      "result_key": {"nullable":true,"type":"VARCHAR(120)"},
      "result_status": {"nullable":false,"type":"VARCHAR(20)"},
      "sample_form": {"nullable":true,"type":"VARCHAR(50)"},
      "sample_label": {"nullable":true,"type":"VARCHAR(100)"},
      "semantic_fingerprint": {"nullable":true,"type":"VARCHAR(64)"},
      "source_kind": {"nullable":false,"type":"VARCHAR(30)"},
      "source_locator": {"nullable":false,"type":"JSONB"},
      "source_record_hash": {"nullable":false,"type":"VARCHAR(64)"},
      "source_snapshot_id": {"nullable":false,"type":"UUID"},
      "structure_phase_raw": {"nullable":true,"type":"VARCHAR(200)"},
      "tc_definition": {"nullable":false,"type":"VARCHAR(30)"},
      "updated_at": {"nullable":false,"type":"DATETIME"},
      "validity_status": {"nullable":false,"type":"VARCHAR(20)"},
      "value_kelvin": {"nullable":true,"type":"FLOAT"},
      "value_lower_kelvin": {"nullable":true,"type":"FLOAT"},
      "value_relation": {"nullable":false,"type":"VARCHAR(20)"},
      "value_upper_kelvin": {"nullable":true,"type":"FLOAT"},
      "work_id": {"nullable":true,"type":"UUID"}
    },
    "fks": [
      [["chunk_id"],"chunks",["id"]],
      [["event_id","material_id"],"research_events",["id","material_id"]],
      [["material_id"],"materials",["id"]],
      [["paper_id"],"papers",["id"]],
      [["source_snapshot_id"],"source_snapshots",["id"]],
      [["work_id"],"works",["id"]]
    ]
  },
  "material_states": {
    "fields": {
      "condition_schema_version": {"nullable":false,"type":"VARCHAR(40)"},
      "conditions": {"nullable":false,"type":"JSONB"},
      "context_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "material_id": {"nullable":false,"type":"VARCHAR(100)"},
      "pressure_gpa": {"nullable":true,"type":"FLOAT"},
      "pressure_status": {"nullable":false,"type":"VARCHAR(20)"},
      "resolution": {"nullable":false,"type":"VARCHAR(20)"},
      "sample_id": {"nullable":true,"type":"UUID"},
      "source_artifact_id": {"nullable":false,"type":"UUID"},
      "temperature_k": {"nullable":true,"type":"FLOAT"},
      "temperature_role": {"nullable":false,"type":"VARCHAR(30)"}
    },
    "fks": [
      [["material_id"],"materials",["id"]],
      [["sample_id","material_id"],"research_samples",["id","material_id"]],
      [["source_artifact_id"],"evidence_artifacts",["id"]]
    ]
  },
  "materials": {
    "fields": {
      "admin_decision": {"nullable":true,"type":"JSONB"},
      "ambient_sc": {"nullable":true,"type":"BOOLEAN"},
      "anomaly_context": {"nullable":false,"type":"JSONB"},
      "anomaly_review": {"nullable":false,"type":"JSONB"},
      "arxiv_year": {"nullable":true,"type":"SMALLINT"},
      "best_credibility_tier": {"nullable":true,"type":"VARCHAR(2)"},
      "competing_order": {"nullable":true,"type":"VARCHAR(100)"},
      "composition_data": {"nullable":true,"type":"JSONB"},
      "composition_enriched_at": {"nullable":true,"type":"DATETIME"},
      "composition_status": {"nullable":true,"type":"VARCHAR(20)"},
      "crystal_structure": {"nullable":true,"type":"VARCHAR(100)"},
      "disputed": {"nullable":true,"type":"BOOLEAN"},
      "dominant_evidence": {"nullable":true,"type":"VARCHAR(20)"},
      "doping_level": {"nullable":true,"type":"FLOAT"},
      "doping_type": {"nullable":true,"type":"VARCHAR(50)"},
      "family": {"nullable":true,"type":"VARCHAR(50)"},
      "formula": {"nullable":false,"type":"VARCHAR(200)"},
      "formula_latex": {"nullable":true,"type":"VARCHAR(200)"},
      "formula_normalized": {"nullable":false,"type":"VARCHAR(200)"},
      "formula_overlayer": {"nullable":true,"type":"VARCHAR(200)"},
      "formula_substrate": {"nullable":true,"type":"VARCHAR(200)"},
      "gap_structure": {"nullable":true,"type":"VARCHAR(50)"},
      "has_competing_order": {"nullable":true,"type":"BOOLEAN"},
      "hc2_conditions": {"nullable":true,"type":"VARCHAR(200)"},
      "hc2_tesla": {"nullable":true,"type":"FLOAT"},
      "id": {"nullable":false,"type":"VARCHAR(100)"},
      "is_unconventional": {"nullable":true,"type":"BOOLEAN"},
      "lambda_eph": {"nullable":true,"type":"FLOAT"},
      "lattice_params": {"nullable":true,"type":"JSONB"},
      "layer_thickness_nm": {"nullable":true,"type":"FLOAT"},
      "material_semantics": {"nullable":false,"type":"JSONB"},
      "mp_alternate_ids": {"nullable":false,"type":"JSONB"},
      "mp_id": {"nullable":true,"type":"VARCHAR(50)"},
      "mp_synced_at": {"nullable":true,"type":"DATETIME"},
      "needs_review": {"nullable":false,"type":"BOOLEAN"},
      "omega_log_k": {"nullable":true,"type":"FLOAT"},
      "pairing_symmetry": {"nullable":true,"type":"VARCHAR(100)"},
      "parent_material_id": {"nullable":true,"type":"VARCHAR(100)"},
      "pressure_type": {"nullable":true,"type":"VARCHAR(50)"},
      "records": {"nullable":false,"type":"JSONB"},
      "retracted": {"nullable":true,"type":"BOOLEAN"},
      "review_reason": {"nullable":true,"type":"VARCHAR(200)"},
      "rho_exponent": {"nullable":true,"type":"FLOAT"},
      "rho_s_mev": {"nullable":true,"type":"FLOAT"},
      "sample_form": {"nullable":true,"type":"VARCHAR(50)"},
      "space_group": {"nullable":true,"type":"VARCHAR(50)"},
      "status": {"nullable":false,"type":"VARCHAR(50)"},
      "structure_phase": {"nullable":true,"type":"VARCHAR(50)"},
      "subfamily": {"nullable":true,"type":"VARCHAR(100)"},
      "substrate": {"nullable":true,"type":"VARCHAR(100)"},
      "t_afm_k": {"nullable":true,"type":"FLOAT"},
      "t_cdw_k": {"nullable":true,"type":"FLOAT"},
      "t_sdw_k": {"nullable":true,"type":"FLOAT"},
      "tc_ambient": {"nullable":true,"type":"FLOAT"},
      "tc_max": {"nullable":true,"type":"FLOAT"},
      "tc_max_conditions": {"nullable":true,"type":"VARCHAR(300)"},
      "tc_max_experimental": {"nullable":true,"type":"FLOAT"},
      "tc_max_theoretical": {"nullable":true,"type":"FLOAT"},
      "total_papers": {"nullable":false,"type":"INTEGER"},
      "updated_at": {"nullable":false,"type":"DATETIME"},
      "variant_count": {"nullable":false,"type":"INTEGER"}
    },
    "fks": [
      [["parent_material_id"],"materials",["id"]]
    ]
  },
  "ml_dataset_snapshots": {
    "fields": {
      "created_at": {"nullable":false,"type":"DATETIME"},
      "data_card_uri": {"nullable":true,"type":"TEXT"},
      "feature_schema_version": {"nullable":false,"type":"VARCHAR(40)"},
      "filters": {"nullable":false,"type":"JSONB"},
      "frozen_at": {"nullable":true,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "label_policy_version": {"nullable":false,"type":"VARCHAR(40)"},
      "manifest_sha256": {"nullable":true,"type":"VARCHAR(64)"},
      "name": {"nullable":false,"type":"VARCHAR(100)"},
      "row_count": {"nullable":false,"type":"BIGINT"},
      "source_snapshot_id": {"nullable":false,"type":"UUID"},
      "split_ruleset_version": {"nullable":false,"type":"VARCHAR(40)"},
      "status": {"nullable":false,"type":"VARCHAR(20)"},
      "version": {"nullable":false,"type":"VARCHAR(50)"}
    },
    "fks": [
      [["source_snapshot_id"],"source_snapshots",["id"]]
    ]
  },
  "ml_example_inputs": {
    "fields": {
      "context": {"nullable":false,"type":"JSONB"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "example_id": {"nullable":false,"type":"UUID"},
      "feature_key": {"nullable":false,"type":"VARCHAR(120)"},
      "id": {"nullable":false,"type":"UUID"},
      "input_artifact_id": {"nullable":true,"type":"UUID"},
      "input_claim_id": {"nullable":true,"type":"UUID"},
      "input_event_id": {"nullable":true,"type":"UUID"},
      "input_kind": {"nullable":false,"type":"VARCHAR(20)"},
      "input_property_id": {"nullable":true,"type":"UUID"},
      "input_structure_id": {"nullable":true,"type":"UUID"},
      "matching_policy_version": {"nullable":false,"type":"VARCHAR(40)"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"}
    },
    "fks": [
      [["example_id"],"ml_examples",["id"]],
      [["input_artifact_id"],"evidence_artifacts",["id"]],
      [["input_claim_id","input_event_id"],"material_claims",["id","event_id"]],
      [["input_event_id"],"research_events",["id"]],
      [["input_property_id","input_event_id"],"event_properties",["id","event_id"]],
      [["input_structure_id"],"structure_records",["id"]]
    ]
  },
  "ml_examples": {
    "fields": {
      "assignment_hash": {"nullable":false,"type":"VARCHAR(64)"},
      "available_at": {"nullable":true,"type":"DATE"},
      "chemical_system_group": {"nullable":true,"type":"VARCHAR(200)"},
      "claim_id": {"nullable":false,"type":"UUID"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "dataset_snapshot_id": {"nullable":false,"type":"UUID"},
      "duplicate_group": {"nullable":false,"type":"VARCHAR(100)"},
      "example_key": {"nullable":false,"type":"VARCHAR(100)"},
      "id": {"nullable":false,"type":"UUID"},
      "label_data": {"nullable":false,"type":"JSONB"},
      "material_group": {"nullable":false,"type":"VARCHAR(100)"},
      "material_id": {"nullable":false,"type":"VARCHAR(100)"},
      "parent_series_group": {"nullable":true,"type":"VARCHAR(100)"},
      "split": {"nullable":false,"type":"VARCHAR(20)"},
      "task_type": {"nullable":false,"type":"VARCHAR(40)"},
      "work_group": {"nullable":false,"type":"VARCHAR(100)"},
      "work_id": {"nullable":true,"type":"UUID"}
    },
    "fks": [
      [["claim_id"],"material_claims",["id"]],
      [["claim_id","material_id"],"material_claims",["id","material_id"]],
      [["dataset_snapshot_id"],"ml_dataset_snapshots",["id"]],
      [["material_id"],"materials",["id"]],
      [["work_id"],"works",["id"]]
    ]
  },
  "paper_work_map": {
    "fields": {
      "created_at": {"nullable":false,"type":"DATETIME"},
      "match_method": {"nullable":false,"type":"VARCHAR(30)"},
      "match_score": {"nullable":true,"type":"FLOAT"},
      "paper_id": {"nullable":false,"type":"VARCHAR(100)"},
      "relation_type": {"nullable":false,"type":"VARCHAR(30)"},
      "review_status": {"nullable":false,"type":"VARCHAR(20)"},
      "work_id": {"nullable":false,"type":"UUID"}
    },
    "fks": [
      [["paper_id"],"papers",["id"]],
      [["work_id"],"works",["id"]]
    ]
  },
  "papers": {
    "fields": {
      "abstract": {"nullable":false,"type":"TEXT"},
      "affiliations": {"nullable":true,"type":"JSONB"},
      "arxiv_id": {"nullable":true,"type":"VARCHAR(20)"},
      "authors": {"nullable":false,"type":"JSONB"},
      "categories": {"nullable":true,"type":"JSONB"},
      "chunk_count": {"nullable":false,"type":"INTEGER"},
      "citation_count": {"nullable":false,"type":"INTEGER"},
      "credibility_tier": {"nullable":true,"type":"VARCHAR(2)"},
      "date_published": {"nullable":true,"type":"DATE"},
      "date_submitted": {"nullable":true,"type":"DATE"},
      "doi": {"nullable":true,"type":"VARCHAR(200)"},
      "external_id": {"nullable":true,"type":"VARCHAR(200)"},
      "id": {"nullable":false,"type":"VARCHAR(100)"},
      "id_scheme": {"nullable":true,"type":"VARCHAR(20)"},
      "indexed_at": {"nullable":false,"type":"DATETIME"},
      "journal": {"nullable":true,"type":"VARCHAR(300)"},
      "journal_abbrev": {"nullable":true,"type":"VARCHAR(30)"},
      "material_family": {"nullable":true,"type":"VARCHAR(50)"},
      "materials_extracted": {"nullable":false,"type":"JSONB"},
      "paper_geo": {"nullable":true,"type":"JSONB"},
      "paper_type": {"nullable":true,"type":"VARCHAR(20)"},
      "publication_ref": {"nullable":true,"type":"JSONB"},
      "quality_flags": {"nullable":false,"type":"JSONB"},
      "related_paper_id": {"nullable":true,"type":"VARCHAR(100)"},
      "retraction_date": {"nullable":true,"type":"DATE"},
      "retraction_reason": {"nullable":true,"type":"TEXT"},
      "source": {"nullable":false,"type":"VARCHAR(20)"},
      "status": {"nullable":false,"type":"VARCHAR(20)"},
      "title": {"nullable":false,"type":"TEXT"},
      "updated_at": {"nullable":false,"type":"DATETIME"}
    },
    "fks": [
      [["related_paper_id"],"papers",["id"]]
    ]
  },
  "research_events": {
    "fields": {
      "assessment_run_kind": {"nullable":true,"type":"VARCHAR(40)"},
      "context": {"nullable":false,"type":"JSONB"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "decision_artifact_id": {"nullable":true,"type":"UUID"},
      "event_type": {"nullable":false,"type":"VARCHAR(40)"},
      "id": {"nullable":false,"type":"UUID"},
      "knowledge_origin": {"nullable":false,"type":"VARCHAR(20)"},
      "material_id": {"nullable":false,"type":"VARCHAR(100)"},
      "producer_run_id": {"nullable":true,"type":"UUID"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "review_status": {"nullable":false,"type":"VARCHAR(20)"},
      "revision": {"nullable":false,"type":"INTEGER"},
      "state_id": {"nullable":false,"type":"UUID"},
      "structure_id": {"nullable":true,"type":"UUID"},
      "supersedes_id": {"nullable":true,"type":"UUID"},
      "validity_status": {"nullable":false,"type":"VARCHAR(20)"}
    },
    "fks": [
      [["decision_artifact_id"],"evidence_artifacts",["id"]],
      [["material_id"],"materials",["id"]],
      [["producer_run_id"],"research_runs",["id"]],
      [["producer_run_id","assessment_run_kind"],"research_runs",["id","run_kind"]],
      [["state_id","material_id"],"material_states",["id","material_id"]],
      [["structure_id","material_id"],"structure_records",["id","material_id"]],
      [["supersedes_id","material_id"],"research_events",["id","material_id"]]
    ]
  },
  "research_import_memberships": {
    "fields": {
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "occurrence_id": {"nullable":false,"type":"UUID"},
      "raw_records": {"nullable":false,"type":"JSONB"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "revision_id": {"nullable":false,"type":"UUID"},
      "snapshot_id": {"nullable":false,"type":"UUID"},
      "source_record_sha256": {"nullable":false,"type":"VARCHAR(64)"}
    },
    "fks": [
      [["occurrence_id","source_record_sha256"],"research_import_occurrences",["id","source_record_sha256"]],
      [["revision_id","occurrence_id"],"research_import_revisions",["id","occurrence_id"]],
      [["snapshot_id"],"research_import_snapshots",["id"]]
    ]
  },
  "research_import_occurrences": {
    "fields": {
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "identity_version": {"nullable":false,"type":"VARCHAR(100)"},
      "legacy_claim_id": {"nullable":false,"type":"UUID"},
      "material_id": {"nullable":false,"type":"VARCHAR(100)"},
      "paper_id": {"nullable":false,"type":"VARCHAR(100)"},
      "raw_record": {"nullable":false,"type":"JSONB"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "source_locator": {"nullable":false,"type":"JSONB"},
      "source_record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "work_id": {"nullable":false,"type":"UUID"}
    },
    "fks": [
      [["material_id"],"materials",["id"]],
      [["paper_id"],"papers",["id"]],
      [["work_id"],"works",["id"]]
    ]
  },
  "research_import_receipts": {
    "fields": {
      "accounting": {"nullable":false,"type":"JSONB"},
      "approval_artifact_id": {"nullable":false,"type":"UUID"},
      "approval_artifact_kind": {"nullable":false,"type":"VARCHAR(30)"},
      "approval_artifact_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "completed_at": {"nullable":false,"type":"DATETIME"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "loader_version": {"nullable":false,"type":"VARCHAR(100)"},
      "plan_manifest_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "selection_manifest": {"nullable":false,"type":"JSONB"},
      "snapshot_id": {"nullable":false,"type":"UUID"}
    },
    "fks": [
      [["approval_artifact_id","approval_artifact_kind"],"evidence_artifacts",["id","kind"]],
      [["snapshot_id"],"research_import_snapshots",["id"]]
    ]
  },
  "research_import_revisions": {
    "fields": {
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "interpretation_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "mapper_version": {"nullable":false,"type":"VARCHAR(100)"},
      "occurrence_id": {"nullable":false,"type":"UUID"},
      "payload": {"nullable":false,"type":"JSONB"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "review_status": {"nullable":false,"type":"VARCHAR(20)"},
      "revision_number": {"nullable":false,"type":"INTEGER"},
      "scientific_acceptance": {"nullable":false,"type":"BOOLEAN"},
      "supersedes_id": {"nullable":true,"type":"UUID"},
      "supersedes_revision_number": {"nullable":true,"type":"INTEGER"}
    },
    "fks": [
      [["occurrence_id"],"research_import_occurrences",["id"]],
      [["supersedes_id","occurrence_id","supersedes_revision_number"],"research_import_revisions",["id","occurrence_id","revision_number"]]
    ]
  },
  "research_import_snapshots": {
    "fields": {
      "chunk_count": {"nullable":false,"type":"BIGINT"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "database_watermark": {"nullable":false,"type":"DATETIME"},
      "dataset_version": {"nullable":false,"type":"VARCHAR(50)"},
      "export_manifest": {"nullable":false,"type":"JSONB"},
      "export_manifest_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "id": {"nullable":false,"type":"UUID"},
      "input_record_count": {"nullable":false,"type":"BIGINT"},
      "license_manifest_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "material_count": {"nullable":false,"type":"BIGINT"},
      "paper_count": {"nullable":false,"type":"BIGINT"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "schema_version": {"nullable":false,"type":"VARCHAR(50)"},
      "site_git_sha": {"nullable":false,"type":"VARCHAR(40)"},
      "source_alembic_revision": {"nullable":false,"type":"VARCHAR(100)"},
      "status": {"nullable":false,"type":"VARCHAR(20)"}
    },
    "fks": [
    ]
  },
  "research_runs": {
    "fields": {
      "code_version": {"nullable":true,"type":"TEXT"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "input_manifest_id": {"nullable":true,"type":"UUID"},
      "model_version": {"nullable":true,"type":"TEXT"},
      "output_manifest_id": {"nullable":true,"type":"UUID"},
      "parent_run_id": {"nullable":true,"type":"UUID"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "run_kind": {"nullable":false,"type":"VARCHAR(40)"},
      "settings": {"nullable":false,"type":"JSONB"},
      "settings_schema_version": {"nullable":false,"type":"VARCHAR(40)"},
      "status": {"nullable":false,"type":"VARCHAR(20)"}
    },
    "fks": [
      [["input_manifest_id"],"evidence_artifacts",["id"]],
      [["output_manifest_id"],"evidence_artifacts",["id"]],
      [["parent_run_id"],"research_runs",["id"]]
    ]
  },
  "research_samples": {
    "fields": {
      "composition_context": {"nullable":false,"type":"JSONB"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "material_id": {"nullable":false,"type":"VARCHAR(100)"},
      "preparation": {"nullable":false,"type":"JSONB"},
      "sample_label": {"nullable":true,"type":"TEXT"},
      "source_artifact_id": {"nullable":false,"type":"UUID"},
      "work_id": {"nullable":true,"type":"UUID"}
    },
    "fks": [
      [["material_id"],"materials",["id"]],
      [["source_artifact_id"],"evidence_artifacts",["id"]],
      [["work_id"],"works",["id"]]
    ]
  },
  "snapshot_event_memberships": {
    "fields": {
      "created_at": {"nullable":false,"type":"DATETIME"},
      "event_id": {"nullable":false,"type":"UUID"},
      "event_revision": {"nullable":false,"type":"INTEGER"},
      "id": {"nullable":false,"type":"UUID"},
      "locator": {"nullable":false,"type":"JSONB"},
      "result_manifest_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "snapshot_id": {"nullable":false,"type":"UUID"},
      "source_occurrence_key": {"nullable":false,"type":"TEXT"},
      "source_record_sha256": {"nullable":false,"type":"VARCHAR(64)"}
    },
    "fks": [
      [["event_id","event_revision"],"research_events",["id","revision"]],
      [["snapshot_id"],"source_snapshots",["id"]]
    ]
  },
  "source_captures": {
    "fields": {
      "bytes_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "capture_key": {"nullable":false,"type":"VARCHAR(160)"},
      "captured_at": {"nullable":false,"type":"DATETIME"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "representation": {"nullable":false,"type":"VARCHAR(30)"},
      "source_revision_id": {"nullable":false,"type":"UUID"}
    },
    "fks": [
      [["source_revision_id"],"source_revisions",["id"]]
    ]
  },
  "source_revisions": {
    "fields": {
      "availability_basis": {"nullable":false,"type":"VARCHAR(100)"},
      "availability_status": {"nullable":false,"type":"VARCHAR(20)"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "metadata_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "paper_id": {"nullable":false,"type":"VARCHAR(100)"},
      "provider_revision": {"nullable":true,"type":"VARCHAR(160)"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "revision_key": {"nullable":false,"type":"VARCHAR(160)"},
      "source_version_public_at": {"nullable":true,"type":"DATETIME"},
      "version_status": {"nullable":false,"type":"VARCHAR(20)"},
      "work_id": {"nullable":true,"type":"UUID"}
    },
    "fks": [
      [["paper_id"],"papers",["id"]],
      [["work_id"],"works",["id"]]
    ]
  },
  "source_snapshots": {
    "fields": {
      "chunk_count": {"nullable":false,"type":"BIGINT"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "database_watermark": {"nullable":true,"type":"DATETIME"},
      "dataset_version": {"nullable":false,"type":"VARCHAR(50)"},
      "frozen_at": {"nullable":true,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "license_manifest_sha256": {"nullable":true,"type":"VARCHAR(64)"},
      "manifest_sha256": {"nullable":true,"type":"VARCHAR(64)"},
      "material_count": {"nullable":false,"type":"BIGINT"},
      "metadata": {"nullable":false,"type":"JSONB"},
      "paper_count": {"nullable":false,"type":"BIGINT"},
      "schema_version": {"nullable":false,"type":"VARCHAR(30)"},
      "site_git_sha": {"nullable":true,"type":"VARCHAR(40)"},
      "status": {"nullable":false,"type":"VARCHAR(20)"}
    },
    "fks": [
    ]
  },
  "structure_records": {
    "fields": {
      "artifact_id": {"nullable":true,"type":"UUID"},
      "coordinate_artifact_kind": {"nullable":true,"type":"VARCHAR(30)"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "material_id": {"nullable":false,"type":"VARCHAR(100)"},
      "occupancy_context": {"nullable":false,"type":"JSONB"},
      "parent_structure_id": {"nullable":true,"type":"UUID"},
      "record_sha256": {"nullable":false,"type":"VARCHAR(64)"},
      "source_version": {"nullable":true,"type":"TEXT"},
      "structure_kind": {"nullable":false,"type":"VARCHAR(30)"}
    },
    "fks": [
      [["artifact_id"],"evidence_artifacts",["id"]],
      [["artifact_id","coordinate_artifact_kind"],"evidence_artifacts",["id","kind"]],
      [["material_id"],"materials",["id"]],
      [["parent_structure_id","material_id"],"structure_records",["id","material_id"]]
    ]
  },
  "works": {
    "fields": {
      "available_at": {"nullable":true,"type":"DATE"},
      "canonical_arxiv_id": {"nullable":true,"type":"VARCHAR(20)"},
      "canonical_doi": {"nullable":true,"type":"VARCHAR(200)"},
      "canonical_title": {"nullable":false,"type":"TEXT"},
      "created_at": {"nullable":false,"type":"DATETIME"},
      "id": {"nullable":false,"type":"UUID"},
      "identity_metadata": {"nullable":false,"type":"JSONB"},
      "publication_status": {"nullable":false,"type":"VARCHAR(20)"},
      "updated_at": {"nullable":false,"type":"DATETIME"}
    },
    "fks": [
    ]
  }
}''')
TABLE_FIELDS = {name: frozenset(value["fields"]) for name, value in SPEC.items()}
FKS = {name: tuple((tuple(fields), target, tuple(columns)) for fields, target, columns in value["fks"])
       for name, value in SPEC.items()}
