"""Versioned shadow schema for migration 0045 (do not mutate after release).

These SQLAlchemy Core tables deliberately have no public write API yet.
Full dependency-closure freezing and revision-aware ingestion are later gates.
Tc remains exclusively in material_claims; RPS is an inferred assessment.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

TABLE_ORDER = (
    "evidence_artifacts",
    "research_runs",
    "research_samples",
    "material_states",
    "structure_records",
    "research_events",
    "event_properties",
    "event_evidence",
    "snapshot_event_memberships",
    "ml_example_inputs",
)
PROPERTY_UNITS = {
    "formation_energy_per_atom": "eV/atom",
    "energy_above_hull": "eV/atom",
    "band_gap": "eV",
    "dos_at_fermi": "states/eV/formula_unit",
    "electron_phonon_lambda": "1",
    "omega_log": "K",
    "phonon_min_frequency": "THz",
    "superfluid_stiffness": "K",
    "rps_score": "point",
    "rps_physical": "point",
    "rps_gain": "point",
    "rps_action": "point",
}


def register(metadata: sa.MetaData) -> dict[str, sa.Table]:
    """Register all ten tables; existing core tables must share this metadata."""
    tables: dict[str, sa.Table] = {}

    def col(name, kind, *, required=False, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def uid(name, target=None, *, required=False):
        args = [sa.ForeignKey(f"{target}.id", ondelete="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=not required)

    def material():
        return sa.Column(
            "material_id",
            sa.String(100),
            sa.ForeignKey("materials.id", ondelete="RESTRICT"),
            nullable=False,
        )

    def obj(name="metadata"):
        return col(name, JSONB, required=True, default=sa.text("'{}'::jsonb"))

    def check(expression, name):
        return sa.CheckConstraint(expression, name=f"ck_rv2_{name}")

    def table(name, *items):
        checks = []
        for item in items:
            if isinstance(item, sa.Column) and isinstance(item.type, JSONB):
                checks.append(check(f"jsonb_typeof({item.name}) = 'object'", f"{name}_{item.name}"))
            if isinstance(item, sa.Column) and item.name.endswith("sha256"):
                checks.append(
                    check(
                        f"{item.name} IS NULL OR {item.name} ~ '^[0-9a-f]{{64}}$'",
                        f"{name}_{item.name}",
                    )
                )
        tables[name] = sa.Table(
            name,
            metadata,
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            *items,
            *checks,
            col("created_at", sa.DateTime(timezone=True), required=True, default=sa.func.now()),
        )

    table(
        "evidence_artifacts",
        col("kind", sa.String(30), required=True),
        col("schema_version", sa.String(40), required=True),
        col("source", sa.Text, required=True),
        col("source_version", sa.Text),
        col("record_sha256", sa.String(64), required=True),
        col("bytes_sha256", sa.String(64)),
        col("hash_status", sa.String(20), required=True),
        col("uri", sa.Text),
        col("license", sa.Text),
        col("access", sa.String(20), required=True),
        col("available_at", sa.DateTime(timezone=True)),
        obj(),
        sa.UniqueConstraint("id", "kind", name="uq_rv2_artifact_kind"),
        check(
            "kind IN ('literature_locator','structure','run_manifest','policy','review','dataset','other')",
            "artifact_kind",
        ),
        check("access IN ('public','metadata_only','restricted','unknown')", "artifact_access"),
        check(
            "(hash_status='verified' AND bytes_sha256 IS NOT NULL) OR (hash_status IN ('unavailable','not_applicable') AND bytes_sha256 IS NULL)",
            "artifact_bytes",
        ),
    )

    table(
        "research_runs",
        col("run_kind", sa.String(40), required=True),
        col("status", sa.String(20), required=True, default="planned"),
        col("code_version", sa.Text),
        col("model_version", sa.Text),
        col("settings_schema_version", sa.String(40), required=True),
        obj("settings"),
        uid("input_manifest_id", "evidence_artifacts"),
        uid("output_manifest_id", "evidence_artifacts"),
        uid("parent_run_id", "research_runs"),
        col("record_sha256", sa.String(64), required=True),
        sa.UniqueConstraint("id", "run_kind", name="uq_rv2_run_kind"),
        check(
            "run_kind IN ('extraction','composition_features','structure_matching','dft','dfpt','ml_prediction','priority_assessment','curation')",
            "run_kind",
        ),
        check("status IN ('planned','running','completed','failed','cancelled')", "run_status"),
        check("parent_run_id IS NULL OR parent_run_id <> id", "run_self"),
    )

    table(
        "research_samples",
        material(),
        uid("work_id", "works"),
        col("sample_label", sa.Text),
        obj("preparation"),
        obj("composition_context"),
        uid("source_artifact_id", "evidence_artifacts", required=True),
        sa.UniqueConstraint("id", "material_id", name="uq_rv2_samples_material"),
    )

    table(
        "material_states",
        material(),
        uid("sample_id"),
        col("resolution", sa.String(20), required=True),
        col("condition_schema_version", sa.String(40), required=True),
        col("pressure_status", sa.String(20), required=True),
        col("pressure_gpa", sa.Float),
        col("temperature_role", sa.String(30), required=True),
        col("temperature_k", sa.Float),
        obj("conditions"),
        col("context_sha256", sa.String(64), required=True),
        uid("source_artifact_id", "evidence_artifacts", required=True),
        sa.UniqueConstraint("id", "material_id", name="uq_rv2_states_material"),
        sa.ForeignKeyConstraint(
            ["sample_id", "material_id"],
            ["research_samples.id", "research_samples.material_id"],
            ondelete="RESTRICT",
            name="fk_rv2_state_sample_material",
        ),
        check("resolution IN ('resolved','source_scoped','unresolved')", "state_resolution"),
        check(
            "(pressure_status='explicit_ambient' AND pressure_gpa=0) OR (pressure_status='reported' AND pressure_gpa>=0 AND pressure_gpa<'Infinity'::float8) OR (pressure_status IN ('not_reported','ambiguous') AND pressure_gpa IS NULL)",
            "state_pressure",
        ),
        check(
            "pressure_status NOT IN ('explicit_ambient','reported') OR pressure_gpa IS NOT NULL",
            "state_pressure_required",
        ),
        check(
            "temperature_role IN ('measurement','synthesis','simulation','unknown')",
            "temperature_role",
        ),
        check(
            "temperature_k IS NULL OR (temperature_k>=0 AND temperature_k<'Infinity'::float8)",
            "temperature_finite",
        ),
        check("temperature_role <> 'unknown' OR temperature_k IS NULL", "temperature_unknown"),
    )

    table(
        "structure_records",
        material(),
        uid("artifact_id", "evidence_artifacts"),
        col("coordinate_artifact_kind", sa.String(30)),
        col("structure_kind", sa.String(30), required=True),
        col("source_version", sa.Text),
        obj("occupancy_context"),
        uid("parent_structure_id"),
        col("record_sha256", sa.String(64), required=True),
        sa.UniqueConstraint("id", "material_id", name="uq_rv2_structures_material"),
        sa.ForeignKeyConstraint(
            ["artifact_id", "coordinate_artifact_kind"],
            ["evidence_artifacts.id", "evidence_artifacts.kind"],
            ondelete="RESTRICT",
            name="fk_rv2_coordinate_artifact_kind",
        ),
        sa.ForeignKeyConstraint(
            ["parent_structure_id", "material_id"],
            ["structure_records.id", "structure_records.material_id"],
            ondelete="RESTRICT",
            name="fk_rv2_structure_parent_material",
        ),
        check(
            "structure_kind IN ('coordinates','prototype','literature_description','unresolved')",
            "structure_kind",
        ),
        check(
            "(structure_kind='coordinates' AND artifact_id IS NOT NULL AND coordinate_artifact_kind IS NOT NULL AND coordinate_artifact_kind='structure') OR (structure_kind<>'coordinates' AND coordinate_artifact_kind IS NULL)",
            "coordinates_artifact",
        ),
        check("parent_structure_id IS NULL OR parent_structure_id <> id", "structure_self"),
    )

    table(
        "research_events",
        material(),
        uid("state_id", required=True),
        uid("structure_id"),
        uid("producer_run_id", "research_runs"),
        col("event_type", sa.String(40), required=True),
        col("assessment_run_kind", sa.String(40)),
        col("knowledge_origin", sa.String(20), required=True),
        col("revision", sa.Integer, required=True, default="1"),
        uid("supersedes_id"),
        col("record_sha256", sa.String(64), required=True),
        col("review_status", sa.String(20), required=True, default="pending"),
        col("validity_status", sa.String(20), required=True, default="pending"),
        uid("decision_artifact_id", "evidence_artifacts"),
        obj("context"),
        sa.UniqueConstraint("id", "material_id", name="uq_rv2_events_material"),
        sa.UniqueConstraint("id", "revision", name="uq_rv2_events_revision"),
        sa.UniqueConstraint("id", "event_type", name="uq_rv2_events_type"),
        sa.ForeignKeyConstraint(
            ["producer_run_id", "assessment_run_kind"],
            ["research_runs.id", "research_runs.run_kind"],
            ondelete="RESTRICT",
            name="fk_rv2_assessment_run_kind",
        ),
        sa.ForeignKeyConstraint(
            ["state_id", "material_id"],
            ["material_states.id", "material_states.material_id"],
            ondelete="RESTRICT",
            name="fk_rv2_event_state_material",
        ),
        sa.ForeignKeyConstraint(
            ["structure_id", "material_id"],
            ["structure_records.id", "structure_records.material_id"],
            ondelete="RESTRICT",
            name="fk_rv2_event_structure_material",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id", "material_id"],
            ["research_events.id", "research_events.material_id"],
            ondelete="RESTRICT",
            name="fk_rv2_event_supersedes_material",
        ),
        check(
            "event_type IN ('measurement','calculation','extraction','curation','prediction','priority_assessment')",
            "event_type",
        ),
        check(
            "knowledge_origin IN ('Observed','Computed','Inferred','AI-Proposed','unknown')",
            "event_origin",
        ),
        check(
            "(event_type='priority_assessment' AND knowledge_origin='Inferred' AND producer_run_id IS NOT NULL AND assessment_run_kind IS NOT NULL AND assessment_run_kind='priority_assessment') OR (event_type<>'priority_assessment' AND assessment_run_kind IS NULL)",
            "priority_inferred",
        ),
        check(
            "knowledge_origin NOT IN ('Computed','AI-Proposed') OR producer_run_id IS NOT NULL",
            "event_producer",
        ),
        check("revision>=1 AND (supersedes_id IS NULL OR supersedes_id<>id)", "event_revision"),
        check("review_status IN ('pending','approved','rejected')", "event_review"),
        check("review_status <> 'approved' OR decision_artifact_id IS NOT NULL", "event_decision"),
        check(
            "validity_status IN ('pending','accepted','disputed','retracted','excluded')",
            "event_validity",
        ),
    )

    registered = " OR ".join(
        f"(property_key='{key}' AND unit='{unit}')" for key, unit in PROPERTY_UNITS.items()
    )
    table(
        "event_properties",
        uid("event_id", "research_events", required=True),
        col("assessment_event_type", sa.String(40)),
        col("property_key", sa.String(50), required=True),
        col("registry_version", sa.String(30), required=True, default="rv2/1"),
        col("component_key", sa.String(120), required=True, default="bulk"),
        col("relation", sa.String(20), required=True),
        col("value", sa.Float),
        col("lower", sa.Float),
        col("upper", sa.Float),
        col("unit", sa.String(40), required=True),
        obj("uncertainty"),
        obj("raw"),
        col("record_sha256", sa.String(64), required=True),
        sa.UniqueConstraint("id", "event_id", name="uq_rv2_property_event"),
        sa.ForeignKeyConstraint(
            ["event_id", "assessment_event_type"],
            ["research_events.id", "research_events.event_type"],
            ondelete="RESTRICT",
            name="fk_rv2_property_assessment_type",
        ),
        sa.UniqueConstraint(
            "event_id",
            "property_key",
            "registry_version",
            "component_key",
            name="uq_rv2_event_property_component",
        ),
        check(f"registry_version='rv2/1' AND ({registered})", "property_registry"),
        check(
            "(property_key IN ('rps_score','rps_physical','rps_gain','rps_action') AND assessment_event_type IS NOT NULL AND assessment_event_type='priority_assessment') OR (property_key NOT IN ('rps_score','rps_physical','rps_gain','rps_action') AND assessment_event_type IS NULL)",
            "property_assessment_origin",
        ),
        check("btrim(component_key) <> ''", "property_component"),
        check(
            "(relation='exact' AND value IS NOT NULL AND lower IS NULL AND upper IS NULL) OR (relation='interval' AND value IS NULL AND lower IS NOT NULL AND upper IS NOT NULL AND lower<=upper) OR (relation IN ('lt','le') AND value IS NULL AND lower IS NULL AND upper IS NOT NULL) OR (relation IN ('gt','ge') AND value IS NULL AND lower IS NOT NULL AND upper IS NULL) OR (relation='unreported' AND value IS NULL AND lower IS NULL AND upper IS NULL)",
            "property_shape",
        ),
        *[
            check(
                f"{key} IS NULL OR ({key}>'-Infinity'::float8 AND {key}<'Infinity'::float8)",
                f"property_{key}_finite",
            )
            for key in ("value", "lower", "upper")
        ],
        check(
            "property_key IN ('formation_energy_per_atom','phonon_min_frequency') OR ((value IS NULL OR value>=0) AND (lower IS NULL OR lower>=0) AND (upper IS NULL OR upper>=0))",
            "property_nonnegative",
        ),
        check(
            "property_key <> 'rps_score' OR ((value IS NULL OR value BETWEEN 1000 AND 10000) AND (lower IS NULL OR lower BETWEEN 1000 AND 10000) AND (upper IS NULL OR upper BETWEEN 1000 AND 10000))",
            "property_score_range",
        ),
        check(
            "property_key NOT IN ('rps_physical','rps_gain','rps_action') OR ((value IS NULL OR value<=100) AND (lower IS NULL OR lower<=100) AND (upper IS NULL OR upper<=100))",
            "property_pga_range",
        ),
    )

    def input_fks(prefix):
        return (
            sa.ForeignKeyConstraint(
                ["input_property_id", "input_event_id"],
                ["event_properties.id", "event_properties.event_id"],
                ondelete="RESTRICT",
                name=f"fk_rv2_{prefix}_property_event",
            ),
            sa.ForeignKeyConstraint(
                ["input_claim_id", "input_event_id"],
                ["material_claims.id", "material_claims.event_id"],
                ondelete="RESTRICT",
                name=f"fk_rv2_{prefix}_claim_event",
            ),
        )

    table(
        "event_evidence",
        uid("event_id", "research_events", required=True),
        col("link_type", sa.String(30), required=True),
        uid("artifact_id", "evidence_artifacts"),
        uid("input_event_id", "research_events"),
        uid("input_property_id"),
        uid("input_claim_id"),
        obj("locator"),
        *input_fks("evidence"),
        check(
            "link_type IN ('source','derives_from','context','supports','refutes')", "evidence_type"
        ),
        check(
            "(artifact_id IS NOT NULL AND input_event_id IS NULL AND input_property_id IS NULL AND input_claim_id IS NULL AND link_type='source' AND locator<>'{}'::jsonb) OR (artifact_id IS NULL AND input_event_id IS NOT NULL AND link_type<>'source' AND NOT (input_property_id IS NOT NULL AND input_claim_id IS NOT NULL))",
            "evidence_shape",
        ),
        check(
            "link_type <> 'derives_from' OR num_nonnulls(input_property_id,input_claim_id)=1",
            "evidence_exact_dependency",
        ),
        check("input_event_id IS NULL OR input_event_id<>event_id", "evidence_self"),
    )

    table(
        "snapshot_event_memberships",
        uid("snapshot_id", "source_snapshots", required=True),
        uid("event_id", required=True),
        col("event_revision", sa.Integer, required=True),
        col("source_occurrence_key", sa.Text, required=True),
        obj("locator"),
        col("source_record_sha256", sa.String(64), required=True),
        col("result_manifest_sha256", sa.String(64), required=True),
        sa.ForeignKeyConstraint(
            ["event_id", "event_revision"],
            ["research_events.id", "research_events.revision"],
            ondelete="RESTRICT",
            name="fk_rv2_membership_revision",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "event_id", "source_occurrence_key", name="uq_rv2_membership_occurrence"
        ),
        check("btrim(source_occurrence_key)<>''", "membership_occurrence"),
    )

    shape = []
    leaves = {
        "claim": "input_claim_id",
        "property": "input_property_id",
        "structure": "input_structure_id",
        "artifact": "input_artifact_id",
    }
    for kind, leaf in leaves.items():
        clauses = [f"input_kind='{kind}'", f"{leaf} IS NOT NULL"]
        clauses.extend(f"{other} IS NULL" for other in leaves.values() if other != leaf)
        clauses.append(
            "input_event_id IS NOT NULL"
            if kind in {"claim", "property"}
            else "input_event_id IS NULL"
        )
        shape.append("(" + " AND ".join(clauses) + ")")
    shape.append(
        "(input_kind='event_context' AND input_event_id IS NOT NULL AND num_nonnulls(input_claim_id,input_property_id,input_structure_id,input_artifact_id)=0)"
    )
    table(
        "ml_example_inputs",
        uid("example_id", "ml_examples", required=True),
        col("input_kind", sa.String(20), required=True),
        uid("input_event_id", "research_events"),
        uid("input_claim_id"),
        uid("input_property_id"),
        uid("input_structure_id", "structure_records"),
        uid("input_artifact_id", "evidence_artifacts"),
        col("feature_key", sa.String(120), required=True),
        col("matching_policy_version", sa.String(40), required=True),
        col("record_sha256", sa.String(64), required=True),
        obj("context"),
        *input_fks("ml_input"),
        check(" OR ".join(shape), "ml_input_shape"),
        check("btrim(feature_key)<>''", "ml_feature_key"),
        sa.UniqueConstraint("example_id", "feature_key", name="uq_rv2_ml_feature"),
    )
    for name in ("research_samples", "material_states", "structure_records", "research_events"):
        sa.Index(f"idx_rv2_{name}_material", tables[name].c.material_id)
    for name in ("event_properties", "event_evidence", "snapshot_event_memberships"):
        sa.Index(f"idx_rv2_{name}_event", tables[name].c.event_id)
    return tables
