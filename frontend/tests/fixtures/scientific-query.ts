import type { BoundScientificQueryResult, RetrievalGeneration, ScientificLookup, ScientificQueryInterpretation, ScientificReportQuantity } from "@/lib/api";

export const generation: RetrievalGeneration = {
  version: "index-read/1.0.0", mode: "generation_snapshot",
  generation_id: "11111111-1111-1111-1111-111111111111",
  activation_event_id: "22222222-2222-2222-2222-222222222222", manifest_sha256: "a".repeat(64),
};

export function scientificQuery(raw = "Tc > 20 K for MgB₂"): ScientificQueryInterpretation {
  const chars = Array.from(raw), formula = "MgB₂", start = chars.join("").includes(formula) ? chars.findIndex((_, i) => chars.slice(i, i + 4).join("") === formula) : -1;
  return {
    version: "scientific-query/1.0.0", raw_query: raw, normalized_query: raw.replaceAll("MgB₂", "MgB2"),
    language: "en", intent: "numerical", status: "resolved", requested_fields: ["tc_kelvin"],
    formulas: start < 0 ? [] : [{ raw_text: formula, start, end: start + 4, normalization: {
      version: "formula-query/1.0.0", raw_formula: formula, normalized_formula: "MgB2", status: "normalized", reason_codes: [],
    } }],
    constraints: raw.startsWith("Tc > 20 K") ? [{ field: "tc_kelvin", raw_text: "Tc > 20 K", start: 0, end: 9,
      relation: "gt", value: null, lower: 20, upper: null, unit: "K", unit_basis: "explicit" }] : [],
    evidence_constraints: [], unresolved_clauses: [], clarification_questions: [], scientific_acceptance: false,
  };
}

export function quantity(patch: Partial<ScientificReportQuantity> = {}): ScientificReportQuantity {
  return { status: "parsed", relation: "exact", value: 39, lower: null, upper: null, uncertainty: null,
    approximate: false, unit: "K", unit_basis: "explicit", uncertainty_interpretation: null, ...patch };
}

export function scientificResult(): BoundScientificQueryResult {
  return {
    result: {
      version: "scientific-query-result/1.0.0", result_id: `legacy-result:${"b".repeat(64)}`, record_index: 0,
      formula: "MgB2", family: "boride", tc: quantity(),
      pressure: { ...quantity({ status: "unreported", relation: "unreported", value: null, unit: "GPa", unit_basis: "unreported" }), pressure_state: "not_reported" },
      minimum_temperature: quantity({ status: "unreported", relation: "unreported", value: null, unit_basis: "unreported" }),
      result_classification: { knowledge_origin: "Observed", classification_status: "resolved", source_role: "primary" },
      outcome_state: "positive_reported", reported_context: { tc_criterion: "onset", sample_label: null,
        sample_form: "bulk", structure_phase: null, measurement_method: "resistivity" }, warning_codes: [],
      scientific_acceptance: false, ml_training_eligible: false, detection_adequacy_verified: false,
    },
    binding: { paper_id: "synthetic:MgB2", vector_id: `ig62_${generation.generation_id!.replaceAll("-", "")}_${"c".repeat(64)}`,
      generation_id: generation.generation_id!, activation_event_id: generation.activation_event_id!, manifest_sha256: generation.manifest_sha256!,
      content_sha256: "d".repeat(64), evidence_revision_id: "33333333-3333-3333-3333-333333333333",
      evidence_record_sha256: "e".repeat(64), parent_result_revision_id: "44444444-4444-4444-4444-444444444444",
      parent_result_sha256: "f".repeat(64), association_scope: "derived_extraction_not_original_support" },
  };
}

export function scientificLookup(patch: Partial<ScientificLookup> = {}): ScientificLookup {
  return { status: "completed", reason_codes: [], returned_count: 1, has_more: false,
    scope: "declared_generation_derived_extractions", scientific_acceptance: false, ...patch };
}
