/** Synthetic fixtures only; these do not assert real anomaly reviews or approval. */
import type { MaterialAnomalyReview, MaterialRawArchive, ScientificAnomalyAssessment } from "@/lib/api";

export function anomalyAssessment(resultId = "synthetic-result:tc_max", field = "tc_max"): ScientificAnomalyAssessment {
  return {
    version: "anomaly-review/1.0.0", result_id: resultId, status: "review_required",
    findings: [{ finding_id: "synthetic-finding:1", result_id: resultId, rule_id: "legacy_compound_reference_review", rule_version: "anomaly-review/1.0.0", category: "unusual", field, affected_properties: [field], applicability: { threshold: 45, unit: "K", reference_basis: "legacy_operational_review_reference", physical_limit: false }, reason: "reported_extent_above_reference", description: "A value crosses a view-scoped legacy compound reference, not a cap.", severity: "warning", outcome: "pending", action: "retain_raw_and_review", quantity: { raw_value: "60 K", raw_unit: "K" }, default_view_disposition: "review_required" }],
    total_findings: 1, findings_truncated: false, review_required_properties: [field], raw_preserved: true, scientific_acceptance: false,
  };
}

export function materialAnomalyReview(): MaterialAnomalyReview {
  return { version: "anomaly-review/1.0.0", needs_review: true, counts: { total_records: 1, review_required: 1, no_findings: 0, format_invalid: 0 }, rule_counts: { legacy_compound_reference_review: 1 }, records: [anomalyAssessment()], total_records: 1, records_truncated: false, raw_preserved: true, scientific_acceptance: false, warnings: ["operational_review_references_not_physical_limits"] };
}

export function rawArchive(): MaterialRawArchive {
  return { version: "anomaly-review/1.0.0", scope: "material_retained_records", raw_field_policy: "scientific_allowlist_not_full_source", records: [{ result_id: "synthetic-result:tc_max", record_index: 0, raw: { formula: "TEST", tc_kelvin: "60 K", paper_id: "synthetic-source", tc_conditions: "<script>untrusted source text</script>" }, assessment: anomalyAssessment() }], total: 1, returned: 1, truncated: false };
}
