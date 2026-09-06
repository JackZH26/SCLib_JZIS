/** Synthetic display fixtures only; not real source records or science reviews. */
import type { MaterialPropertyEvidence, PropertyEvidenceItem } from "@/lib/api";

export function atomicItem(field: string, value: unknown, overrides: Partial<PropertyEvidenceItem> = {}): PropertyEvidenceItem {
  const resultId = overrides.result_id ?? `synthetic-result:${field}`;
  return {
    result_id: resultId, property: field, value,
    anomaly_review: { version: "anomaly-review/1.0.0", result_id: resultId, status: "no_findings", findings: [], total_findings: 0, findings_truncated: false, review_required_properties: [], raw_preserved: true, scientific_acceptance: false },
    quantity: typeof value === "number" ? { status: "parsed", relation: "exact", value, lower: null, upper: null, uncertainty: null, approximate: false, unit: field === "hc2_tesla" ? "T" : field === "lambda_eph" ? "1" : "K", errors: [] } : null,
    conditions: { method: "Synthetic test method" },
    state: { state_id: "synthetic-state", sample_id: "synthetic-sample", structure_id: "synthetic-structure", run_id: "synthetic-run", pressure_semantics: { classifier_version: "pressure-policy/1.0.0", pressure_state: "not_reported" } },
    source: { paper_id: "arxiv:synthetic-test", doi: null, arxiv_id: null, year: 2026, source_locator: { table: "S1", row: "2" } },
    origin: { knowledge_origin: "Computed", classification_status: "resolved", source_role: "primary", classifier_version: "sclib-result-origin/v1" },
    structure: { crystal_structure: null, space_group: null, structure_phase: null, lattice_params: null, lattice_quantities: {} },
    ...overrides,
  };
}

export function propertyEnvelope(...items: PropertyEvidenceItem[]): MaterialPropertyEvidence {
  return {
    version: "property-evidence/1.1.0", anomaly_policy_version: "anomaly-review/1.0.0", not_joint_observation: true, evidence_scope: "selected_only",
    properties: Object.fromEntries(items.map(item => [item.property, { status: "supported", selection: "deterministic_result", selected: item, evidence: [], warnings: [], total_evidence_count: 1, truncated: false }])),
    joint_epc: { status: "not_evaluated", selected: null, pairs: [], warnings: ["joint_epc_evaluation_not_requested"], total_pair_count: null, total_pair_count_exact: false },
  };
}
