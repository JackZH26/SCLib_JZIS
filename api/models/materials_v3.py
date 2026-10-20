"""Forward extension of the frozen 0045 research schema; no automatic approval."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

VERSION = "materials-properties/3.0"
NUMERIC_UNITS = {
    "upper_critical_field": "T",
    "lower_critical_field": "T",
    "critical_current_density": "A/cm2",
    "gap_energy": "meV",
    "electron_phonon_lambda": "1",
    "omega_log": "K",
    "coulomb_mu_star": "1",
    "penetration_depth": "nm",
    "coherence_length": "nm",
    "resistivity": "ohm*m",
    "carrier_density": "1/cm3",
    "superfluid_density": "1/cm3",
    "superfluid_stiffness": "meV",
    "transition_temperature_structural": "K",
    "transition_temperature_magnetic": "K",
    "lattice_a": "angstrom",
    "lattice_b": "angstrom",
    "lattice_c": "angstrom",
    "lattice_alpha": "degree",
    "lattice_beta": "degree",
    "lattice_gamma": "degree",
    "unit_cell_volume": "angstrom3",
    "band_gap": "eV",
    "dos_at_fermi": "states/eV/formula_unit",
    "formation_energy_per_atom": "eV/atom",
    "energy_above_hull": "eV/atom",
    "phonon_min_frequency": "THz",
    "film_thickness": "nm",
    "strain": "1",
}
TEXT_KEYS = (
    "pairing_symmetry",
    "composition_family",
    "structure_motif",
    "electronic_class",
    "mechanism_report",
    "space_group",
    "phase_label",
    "sample_form",
    "substrate",
    "preparation_method",
    "pressure_medium",
    "competing_order",
    "unconventional_report",
    "ambient_sc_report",
)
TABLE_ORDER = (
    "ner_source_captures",
    "ner_source_occurrences",
    "ner_extraction_runs",
    "ner_candidates",
    "ner_block_coverage",
    "research_series",
    "research_series_points",
    "research_condition_quantities",
    "research_point_events",
    "event_qualitative_claims",
    "event_field_evidence",
    "ner_interpretation_selections",
    "material_projection_snapshots",
    "material_projection_members",
)


def registry_check() -> str:
    from models.research_schema_v2 import PROPERTY_UNITS

    old = " OR ".join(f"(property_key='{k}' AND unit='{v}')" for k, v in PROPERTY_UNITS.items())
    new = " OR ".join(f"(property_key='{k}' AND unit='{v}')" for k, v in NUMERIC_UNITS.items())
    return f"(registry_version='rv2/1' AND ({old})) OR (registry_version='{VERSION}' AND ({new}))"


def pressure_check(status, value, lower, upper, relation, *, legacy_ambiguous=False):
    ambiguous = (
        f"({status}='ambiguous' AND {lower} IS NULL AND {upper} IS NULL)"
        if legacy_ambiguous
        else f"({status}='ambiguous' AND {value} IS NULL AND {lower} IS NULL AND {upper} IS NULL)"
    )
    return (
        f"({status}='explicit_ambient' AND {value} IS NOT NULL AND {value}=0 AND {relation}='point' AND {lower} IS NULL AND {upper} IS NULL) OR "
        f"({status}='reported' AND (({relation}='point' AND {value} IS NOT NULL AND {lower} IS NULL AND {upper} IS NULL) OR "
        f"({relation}='interval' AND {value} IS NULL AND {lower} IS NOT NULL AND {upper} IS NOT NULL AND {lower}<={upper}) OR "
        f"({relation} IN ('lt','le') AND {value} IS NULL AND {lower} IS NULL AND {upper} IS NOT NULL) OR "
        f"({relation} IN ('gt','ge') AND {value} IS NULL AND {lower} IS NOT NULL AND {upper} IS NULL))) OR "
        f"({status}='not_reported' AND {value} IS NULL AND {lower} IS NULL AND {upper} IS NULL) OR {ambiguous}"
    )


def extend_current_metadata(metadata):
    """Only current metadata changes; historical registrars stay byte-for-byte intact."""
    table = metadata.tables["event_properties"]
    for constraint in list(table.constraints):
        if constraint.name == "ck_rv2_property_registry":
            table.constraints.remove(constraint)
    table.append_constraint(sa.CheckConstraint(registry_check(), name="ck_rv2_property_registry"))
    for constraint in list(table.constraints):
        if constraint.name == "ck_rv2_property_nonnegative":
            table.constraints.remove(constraint)
    table.append_constraint(
        sa.CheckConstraint(
            "property_key IN ('formation_energy_per_atom','phonon_min_frequency') OR "
            "(registry_version='materials-properties/3.0' AND property_key='strain') OR "
            "((value IS NULL OR value>=0) AND (lower IS NULL OR lower>=0) AND (upper IS NULL OR upper>=0))",
            name="ck_rv2_property_nonnegative",
        )
    )


def register(metadata):
    tables = {}

    def uid(name, target=None, required=False):
        args = [sa.ForeignKey(f"{target}.id", ondelete="RESTRICT")] if target else []
        return sa.Column(name, UUID(as_uuid=True), *args, nullable=not required)

    def obj(name):
        return sa.Column(name, JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"))

    def col(name, kind=sa.Text, required=True, default=None):
        return sa.Column(name, kind, nullable=not required, server_default=default)

    def sha(name):
        return col(name, sa.String(64))

    def ck(sql, name):
        return sa.CheckConstraint(sql, name="ck_mv3_" + name)

    def material():
        return sa.Column(
            "material_id",
            sa.String(100),
            sa.ForeignKey("materials.id", ondelete="RESTRICT"),
            nullable=False,
        )

    def table(name, *items):
        checks = [
            ck(f"jsonb_typeof({c.name})='object'", f"{name}_{c.name}")
            for c in items
            if isinstance(c, sa.Column) and isinstance(c.type, JSONB)
        ]
        checks += [
            ck(f"{c.name} ~ '^[0-9a-f]{{64}}$'", f"{name}_{c.name}")
            for c in items
            if isinstance(c, sa.Column) and c.name.endswith("sha256")
        ]
        tables[name] = sa.Table(
            name,
            metadata,
            uid("id", required=True),
            *items,
            *checks,
            col("created_at", sa.DateTime(timezone=True), default=sa.func.now()),
        )
        tables[name].c.id.primary_key = True
        tables[name].c.id.server_default = sa.DefaultClause(sa.text("gen_random_uuid()"))
        # Setting primary_key after Table construction does not rebuild its PK.
        tables[name].append_constraint(sa.PrimaryKeyConstraint("id"))
        return tables[name]

    table(
        "ner_source_captures",
        col("paper_id", sa.String(100), required=False),
        uid("work_id", "works"),
        uid("artifact_id", "evidence_artifacts"),
        sha("source_sha256"),
        sha("manifest_sha256"),
        col("parser_version"),
        col("source_version"),
        col("source_license"),
        col("transfer_allowed", sa.Boolean, default="false"),
        obj("manifest"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("manifest_sha256", name="uq_mv3_capture_manifest"),
    )
    table(
        "ner_source_occurrences",
        uid("capture_id", "ner_source_captures", True),
        sha("position_sha256"),
        obj("positions"),
        sa.UniqueConstraint("capture_id", "position_sha256", name="uq_mv3_occurrence_position"),
        sa.UniqueConstraint("id", "capture_id", name="uq_mv3_occurrence_capture"),
    )
    table(
        "ner_extraction_runs",
        uid("capture_id", "ner_source_captures", True),
        col("provider"),
        col("model"),
        col("model_revision", required=False),
        sha("config_sha256"),
        col("schema_version"),
        col("prompt_version"),
        col("status", sa.String(20), default="planned"),
        obj("config"),
        obj("usage"),
        ck("provider IN ('local_mlx','gemini','openai','fixture')", "provider"),
        ck("status IN ('planned','running','completed','failed','cancelled')", "run_status"),
        sa.UniqueConstraint("id", "capture_id", name="uq_mv3_run_capture"),
    )
    table(
        "ner_candidates",
        uid("run_id", required=True),
        uid("capture_id", required=True),
        uid("occurrence_id", required=True),
        col("local_id"),
        sha("interpretation_sha256"),
        obj("payload"),
        obj("validation"),
        sa.ForeignKeyConstraint(
            ["run_id", "capture_id"],
            ["ner_extraction_runs.id", "ner_extraction_runs.capture_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id", "capture_id"],
            ["ner_source_occurrences.id", "ner_source_occurrences.capture_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "run_id",
            "occurrence_id",
            "interpretation_sha256",
            name="uq_mv3_candidate_interpretation",
        ),
        sa.UniqueConstraint("id", "occurrence_id", name="uq_mv3_candidate_occurrence"),
    )
    table(
        "ner_block_coverage",
        uid("run_id", "ner_extraction_runs", True),
        col("block_id"),
        sha("input_sha256"),
        col("status"),
        obj("receipt"),
        sa.UniqueConstraint("run_id", "block_id", name="uq_mv3_coverage_block"),
        ck(
            "status IN ('validated','empty','split','provider_failed','validation_failed','output_limit','budget_exhausted','parse_failed','resource_exhausted','cancelled')",
            "coverage_status",
        ),
    )
    table(
        "research_series",
        material(),
        uid("work_id", "works"),
        uid("sample_id", "research_samples"),
        uid("source_artifact_id", "evidence_artifacts", True),
        col("label_raw", required=False),
        sha("context_sha256"),
        obj("context"),
        sa.ForeignKeyConstraint(
            ["sample_id", "material_id"],
            ["research_samples.id", "research_samples.material_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "material_id", name="uq_mv3_series_material"),
        sa.UniqueConstraint("source_artifact_id", "context_sha256", name="uq_mv3_series_context"),
    )
    table(
        "research_series_points",
        uid("series_id", required=True),
        material(),
        col("ordinal", sa.Integer),
        col("path_direction"),
        col("label_raw", required=False),
        col("replicate_raw", required=False),
        obj("conditions"),
        sha("position_sha256"),
        sa.ForeignKeyConstraint(
            ["series_id", "material_id"],
            ["research_series.id", "research_series.material_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "material_id", name="uq_mv3_point_material"),
        sa.UniqueConstraint("series_id", "position_sha256", name="uq_mv3_point_position"),
        ck("ordinal>=0", "point_ordinal"),
        ck(
            "path_direction IN ('loading','unloading','warming','cooling','increasing','decreasing','unknown')",
            "point_direction",
        ),
    )
    table(
        "research_condition_quantities",
        uid("point_id", required=True),
        material(),
        col("condition_key"),
        col("status"),
        col("relation", sa.String(20)),
        col("value_gpa", sa.Float, required=False),
        col("lower_gpa", sa.Float, required=False),
        col("upper_gpa", sa.Float, required=False),
        col("unit", sa.String(12), default="GPa"),
        uid("source_artifact_id", "evidence_artifacts", True),
        obj("raw"),
        obj("locator"),
        sha("record_sha256"),
        sa.ForeignKeyConstraint(
            ["point_id", "material_id"],
            ["research_series_points.id", "research_series_points.material_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("point_id", "condition_key", name="uq_mv3_point_pressure_role"),
        ck(
            "condition_key IN ('measurement_pressure','synthesis_pressure','calculation_pressure','structural_pressure') AND unit='GPa'",
            "condition_pressure_role",
        ),
        ck(
            "status IN ('reported','explicit_ambient','not_reported','ambiguous') AND relation IN ('point','interval','lt','le','gt','ge')",
            "condition_pressure_status",
        ),
        ck(
            pressure_check("status", "value_gpa", "lower_gpa", "upper_gpa", "relation"),
            "condition_pressure_shape",
        ),
        ck("locator<>'{}'::jsonb", "condition_pressure_locator"),
        *[
            ck(f"{k} IS NULL OR ({k}>=0 AND {k}<'Infinity'::float8)", "condition_" + k + "_finite")
            for k in ("value_gpa", "lower_gpa", "upper_gpa")
        ],
    )
    table(
        "research_point_events",
        uid("point_id", required=True),
        uid("event_id", required=True),
        material(),
        sa.ForeignKeyConstraint(
            ["point_id", "material_id"],
            ["research_series_points.id", "research_series_points.material_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "material_id"],
            ["research_events.id", "research_events.material_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("point_id", "event_id", name="uq_mv3_point_event"),
    )
    text_registered = ",".join(f"'{k}'" for k in TEXT_KEYS)
    table(
        "event_qualitative_claims",
        uid("event_id", "research_events", True),
        col("property_key"),
        col("value_raw"),
        col("knowledge_origin"),
        col("source_role"),
        obj("qualifiers"),
        obj("raw"),
        sha("record_sha256"),
        ck(f"property_key IN ({text_registered})", "qualitative_registry"),
        ck(
            "knowledge_origin IN ('Observed','Computed','Inferred','AI-Proposed','Unknown')",
            "qualitative_origin",
        ),
        ck("source_role IN ('primary','cited','unknown')", "qualitative_role"),
        sa.UniqueConstraint("id", "event_id", name="uq_mv3_qualitative_event"),
        sa.UniqueConstraint(
            "event_id", "property_key", "record_sha256", name="uq_mv3_qualitative_record"
        ),
    )
    table(
        "event_field_evidence",
        uid("event_id", "research_events", True),
        uid("property_id"),
        uid("claim_id"),
        uid("qualitative_id"),
        uid("artifact_id", "evidence_artifacts", True),
        col("knowledge_origin"),
        col("source_role"),
        obj("locator"),
        sha("record_sha256"),
        sa.ForeignKeyConstraint(
            ["property_id", "event_id"],
            ["event_properties.id", "event_properties.event_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "event_id"],
            ["material_claims.id", "material_claims.event_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["qualitative_id", "event_id"],
            ["event_qualitative_claims.id", "event_qualitative_claims.event_id"],
            ondelete="RESTRICT",
        ),
        ck(
            "num_nonnulls(property_id,claim_id,qualitative_id)=1 AND locator<>'{}'::jsonb",
            "field_evidence_shape",
        ),
        ck(
            "knowledge_origin IN ('Observed','Computed','Inferred','AI-Proposed','Unknown')",
            "field_origin",
        ),
        ck("source_role IN ('primary','cited','unknown')", "field_role"),
    )
    table(
        "ner_interpretation_selections",
        material(),
        uid("occurrence_id", "ner_source_occurrences", True),
        uid("candidate_id", required=True),
        uid("supersedes_id", "ner_interpretation_selections"),
        col("selection_version"),
        obj("decision"),
        sha("record_sha256"),
        sa.ForeignKeyConstraint(
            ["candidate_id", "occurrence_id"],
            ["ner_candidates.id", "ner_candidates.occurrence_id"],
            ondelete="RESTRICT",
        ),
        ck(
            "(decision->>'scientific_acceptance') IS NOT DISTINCT FROM 'false'",
            "selection_not_approval",
        ),
    )
    table(
        "material_projection_snapshots",
        col("schema_version"),
        sha("manifest_sha256"),
        obj("manifest"),
        sa.UniqueConstraint("manifest_sha256", name="uq_mv3_projection_manifest"),
    )
    table(
        "material_projection_members",
        uid("snapshot_id", "material_projection_snapshots", True),
        material(),
        obj("projection"),
        sha("record_sha256"),
        sa.UniqueConstraint("snapshot_id", "material_id", name="uq_mv3_projection_material"),
    )
    sa.Index("ix_mv3_runs_capture", tables["ner_extraction_runs"].c.capture_id)
    sa.Index("ix_mv3_series_material", tables["research_series"].c.material_id)
    sa.Index("ix_mv3_candidates_capture", tables["ner_candidates"].c.capture_id)
    return tables
