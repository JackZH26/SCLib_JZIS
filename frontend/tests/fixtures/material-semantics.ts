/** Synthetic UI fixtures only: not measured material data or scientific reviews. */
import type { MaterialSemanticEvidence, MaterialSemanticField, MaterialSemanticProperty, MaterialSemantics } from "@/lib/api";

export function semanticReport(value: boolean | string | null = true, overrides: Partial<MaterialSemanticEvidence> = {}): MaterialSemanticEvidence {
  return {
    result_id: "synthetic-result", result_revision: 1, occurrence_id: "synthetic-occurrence", occurrence_count: 1,
    paper_id: "arxiv:synthetic", bibliographic_identifiers: [{ kind: "paper_id", value: "arxiv:synthetic" }],
    source_status: "active", status: "reported", value, basis: "explicit_source_report",
    eligible_for_summary: true, negative_qualified: false, knowledge_origin: "Observed", classification_status: "resolved", source_role: "primary",
    state: { sample_id: "synthetic-sample", pressure: { state: "reported", relation: "exact", value: 0.0001 } },
    method: "Synthetic scattering method", detection_conditions: {}, source_locator: { table: "S1", row: "2" }, reason_codes: [],
    ...overrides,
  };
}

export function semanticProperty(value: boolean | string | null = true, evidence = semanticReport(value)): MaterialSemanticProperty {
  return { status: "reported", value, basis: "eligible_source_reports", reason_codes: [], evidence: [evidence], total_evidence: 1, total_occurrences: 1, evidence_truncated: false };
}

export function materialSemantics(properties: Partial<Record<MaterialSemanticField, MaterialSemanticProperty>> = {}): MaterialSemantics {
  const unknown = (): MaterialSemanticProperty => ({ status: "unknown", value: null, basis: "no_eligible_report", reason_codes: ["not_reported"], evidence: [], total_evidence: 0, total_occurrences: 0, evidence_truncated: false });
  return {
    version: "material-semantics/1.0.0", scientific_acceptance: false,
    properties: { has_competing_order: unknown(), is_unconventional: unknown(), pairing_symmetry: unknown(), ...properties },
    priors: [],
    conflicts: { state_variability: { detected: false, count: 0, properties: [], evidence: [] }, extraction_conflict: { detected: false, count: 0, properties: [], evidence: [] }, scientific_dispute: { status: "not_reported", count: 0, evidence: [] } },
    support: { occurrence_count: 3, bibliographic_identifier_count: 2, source_backed_occurrence_count: 3, legacy_total_papers: 7, count_basis: "bibliographic_identifiers_in_assessed_raw_occurrences; legacy_total_papers_can_include_parent_rollups_or_other_catalogue_policy", independent_work_count: null, independent_replication_count: null, assessment_complete: true },
    warnings: [],
  };
}
