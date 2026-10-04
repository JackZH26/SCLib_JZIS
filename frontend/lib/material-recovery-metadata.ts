import type { MaterialEnrichmentReport, MaterialSourceCoverage } from "@/lib/api";

type ObjectRow = Record<string, unknown>;
const object = (value: unknown): ObjectRow => value != null && typeof value === "object" && !Array.isArray(value) ? value as ObjectRow : {};
const scalar = (value: unknown) => value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value)) || (typeof value === "string" && value.length <= 2000);
const pick = (value: unknown, keys: readonly string[]): ObjectRow => {
  const row = object(value);
  return Object.fromEntries(keys.filter(key => Object.hasOwn(row, key) && scalar(row[key])).map(key => [key, row[key]]));
};
const code = (value: unknown): value is string => typeof value === "string" && /^[a-z][a-z0-9_/-]{0,119}$/.test(value);
const codes = (value: unknown): string[] => Array.isArray(value) ? value.filter(code) : [];
const countMap = (value: unknown): Record<string, number> => Object.fromEntries(Object.entries(object(value)).filter(([key, number]) => code(key) && typeof number === "number" && Number.isSafeInteger(number) && number >= 0)) as Record<string, number>;

export const RECOVERY_REASON_LABELS: Record<string, string> = {
  paper_sampling_limit: "Paper was outside this request’s paper limit",
  no_indexed_chunks: "No indexed chunks were available for this paper",
  indexed_chunk_length_outside_bounds: "Indexed chunk length was outside the permitted bounds",
  chunk_inspection_limit: "Shared chunk budget reached",
  character_inspection_limit: "Shared character budget reached; whole chunk omitted",
  indexed_chunk_changed_or_unavailable: "Chunk changed or was unavailable before reading",
  source_permission_restricted: "Source permission excludes this chunk",
  source_not_current: "Source is no longer current",
  derived_source: "Derived text is excluded from original-source recovery",
  unsupported_source_kind: "Source kind is outside this recovery scope",
  source_locator_required: "Source locator is missing or exceeds this read scope",
  source_locator_invalid: "Source locator needs format review",
  source_locator_span_invalid: "Source span bounds need review",
  retained_record_inventory_not_fully_inspected: "Some retained records were outside this sample",
  retained_value_source_location_and_state_may_require_review: "Retained value still needs source and state review",
  source_candidates_available: "Source candidates are available for review",
  retained_source_identity_missing: "Retained record has no usable source identity",
  paper_field_extractor_not_implemented: "This field has no implemented paper extractor",
  specialist_extractor_not_implemented: "This field needs a specialist extractor",
  external_reference_route_is_not_a_lookup_hit: "A reference route is suggested; no lookup hit is established",
  original_source_capture_not_supplied: "No usable source capture was supplied",
  bounded_extractor_did_not_find_local_candidate: "No local candidate found in the checked chunks",
  bounded_specialist_grammar_has_incomplete_recall: "Specialist extraction does not cover every source expression",
  bounded_source_value_grammar_has_incomplete_recall: "Literal extraction does not cover every reported value or table",
  raw_source_value_not_normalized: "Original value and unit are retained without conversion",
  reported_scope_requires_review: "Reported property and measurement scope need review",
  cited_negative_or_qualified_context: "Citation or qualified statement needs interpretation",
  model_or_calculation_context: "Value appears in a model or calculation context",
  inference_or_unmeasured_context: "Value is inferred or not measured in this context",
  fit_or_estimate_context: "Value appears in a fit, estimate or extrapolation",
  source_assertion_subject_or_scope_requires_review: "Statement subject or scope needs review",
  fulltext_coverage_incomplete: "Full paper coverage is incomplete",
  supplement_coverage_incomplete: "Supplement coverage is incomplete",
};
export const recoveryReasonLabel = (reason: string) => RECOVERY_REASON_LABELS[reason] ?? reason.replaceAll("_", " ");

const LOCATOR_KEYS = ["page", "table", "figure", "section", "row", "column", "line", "paragraph", "char_start", "char_end", "xml_xpath", "chunk_id", "span_id"];
const span = (value: unknown) => pick(value, ["char_start", "char_end", "text_sha256"]);
function source(value: unknown): ObjectRow {
  const row = object(value);
  const result = pick(row, ["paper_id", "capture_id", "kind", "source_revision", "source_revision_basis", "content_sha256", "capture_sha256", "source_status", "publication_revision_verified"]);
  if (typeof row.source_url === "string") {
    try {
      const url = new URL(row.source_url);
      if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password && ["arxiv.org", "export.arxiv.org", "journals.aps.org", "doi.org", "dx.doi.org"].includes(url.hostname)) result.source_url = url.href;
    } catch { /* A malformed URL is not a public provenance link. */ }
  }
  result.locator = pick(row.locator, LOCATOR_KEYS);
  result.span = span(row.span);
  return result;
}
function quantity(value: unknown): ObjectRow | null {
  if (value == null) return null;
  const row = object(value);
  return { ...pick(row, ["field", "raw_value", "raw_unit", "input_unit", "value", "lower", "upper", "uncertainty", "uncertainty_interpretation", "approximate", "relation", "status", "unit", "unit_basis", "value_kind", "parser_version", "normalization_version", "proposal_hash"]),
    source_locator: pick(row.source_locator, LOCATOR_KEYS), errors: codes(row.errors) };
}
function sourceValue(value: unknown): ObjectRow | null {
  const row = object(value);
  if (row.normalization !== "none") return null;
  return { ...pick(row, ["raw_value", "raw_unit", "raw_uncertainty", "normalization", "role", "field_cue"]),
    qualifiers: codes(row.qualifiers), value_span: span(row.value_span),
    unit_span: row.unit_span == null ? null : span(row.unit_span), cue_span: span(row.cue_span) };
}
/** Scientific structured values have field-specific keys; arbitrary nested context is never serialized. */
function rawValue(value: unknown): unknown {
  if (scalar(value)) return value;
  const row = object(value);
  const result = pick(row, ["catalogue_formula", "source_formula", "nominal_formula_raw", "refined_formula_raw", "relation", "association_reviewed", "site", "fractional_coordinate_raw", "full_coordinates_and_symmetry_reviewed", "occupancy_and_structure_binding_reviewed", "interpretation"]);
  if (Array.isArray(row.site_elements)) result.site_elements = row.site_elements.filter((v): v is string => typeof v === "string" && /^[A-Z][a-z]?$/.test(v));
  if (row.fractions_raw) result.fractions_raw = Object.fromEntries(Object.entries(object(row.fractions_raw)).filter(([key, v]) => /^[A-Z][a-z]?$/.test(key) && scalar(v)));
  return result;
}
function subject(value: unknown): ObjectRow {
  const row = object(value);
  const result = pick(row, ["formula", "formula_raw", "source_formula", "identity_basis", "association_status", "knowledge_origin", "measurement_method", "calculation_method", "tc_criterion", "pressure_state", "pressure_role", "field_role", "sample_label", "state_label", "phase_label", "run_label", "table_column", "table_column_formula", "respective_alignment", "doping_assignment_raw"]);
  if (Object.hasOwn(row, "pressure_quantity")) result.pressure_quantity = quantity(row.pressure_quantity);
  if (row.binding_span) result.binding_span = span(row.binding_span);
  if (row.binding_proposal) {
    const binding = object(row.binding_proposal);
    result.binding_proposal = { ...pick(binding, ["alias_raw", "binding_id", "doping_assignment_raw", "formula", "scope", "association_reviewed"]), source: source(binding.source) };
  }
  if (row.conditions) {
    const conditions = object(row.conditions);
    result.conditions = { ...pick(conditions, ["measurement_window_verified", "pressure_status"]), mentions: Array.isArray(conditions.mentions) ? conditions.mentions.map(value => ({ ...pick(value, ["kind", "raw_value", "raw_unit"]), quantity: quantity(object(value).quantity) })) : [] };
  }
  if (Array.isArray(row.methods)) result.methods = row.methods.map(value => pick(value, ["name", "value_raw"]));
  return result;
}
const AUTHORITY_KEYS = ["scientific_acceptance", "ml_training_approved", "public_release", "database_changed", "source_content_checked", "material_state_reviewed"];
const LITERAL_FIELDS = ["tc_kelvin", "pressure_gpa", "tc_criterion", "measurement_method", "calculation_method", "sample_form", "space_group", "crystal_structure", "lattice_a", "lattice_b", "lattice_c", "lattice_alpha", "lattice_beta", "lattice_gamma", "atomic_sites", "site_occupancies", "composition_identity", "measurement_temperature_k", "lambda_eph", "omega_log_source_value", "mu_star", "hc2_tesla", "lambda_london_nm", "xi_gl_nm"];
LITERAL_FIELDS.push("hc1_source_value", "gap_energy_source_value", "gap_ratio_source_value", "electronic_specific_heat_coefficient_source_value", "debye_temperature_source_value", "isotope_effect_exponent", "dtc_dp_source_value", "maximum_applied_pressure_source_value", "meissner_fraction_percent", "transition_width_source_value", "minimum_temperature_k", "t_cdw_k", "t_afm_k", "t_sdw_k");
const CLASSIFICATION_FIELDS = ["pairing_symmetry", "is_unconventional", "gap_structure", "reported_order", "competing_order"];
function candidate(value: unknown, materialId: string, classification: boolean): ObjectRow | null {
  const row = object(value);
  const version = classification ? "material-classification-candidates/1.0.0" : "materials-enrichment/1.0.0";
  if (row.version !== version || row.material_id !== materialId || row.disposition !== "pending" || AUTHORITY_KEYS.some(key => row[key] !== false) || row.coordinates_validated === true || object(row.identity_candidate).association_reviewed === true || object(object(row.subject).binding_proposal).association_reviewed === true || typeof row.candidate_id !== "string" || !new RegExp(`^${classification ? "classification" : "enrichment"}:[a-f0-9]{64}$`).test(row.candidate_id) || ![...(classification ? CLASSIFICATION_FIELDS : LITERAL_FIELDS)].includes(String(row.field))) return null;
  const result: ObjectRow = { ...pick(row, ["version", "extractor_version", "material_id", "candidate_id", "field", "disposition", "retained_result_id", "retained_record_sha256", "retained_reference_count", "evidence_text_sha256", "coordinates_validated", "table_row_label", ...AUTHORITY_KEYS]),
    subject: subject(row.subject), source: source(row.source), reason_codes: codes(row.reason_codes), review_requirements: codes(row.review_requirements),
    retained_result_refs: Array.isArray(row.retained_result_refs) ? row.retained_result_refs.map(value => pick(value, ["result_id", "record_sha256"])) : [] };
  if (classification) result.claim = pick(row.claim, ["normalized_value", "relation_to_superconductivity", "scope", "source_role", "stance", "value_raw"]);
  else {
    result.raw_value = rawValue(row.raw_value); result.value = rawValue(row.value); result.quantity = quantity(row.quantity);
    if (row.source_value) result.source_value = sourceValue(row.source_value);
  }
  if (row.identity_candidate) {
    const identity = object(row.identity_candidate);
    result.identity_candidate = { ...pick(identity, ["candidate_id", "association_reviewed"]), source: source(identity.source) };
  }
  return result;
}
export function projectSourceCoverage(value: unknown): Record<string, MaterialSourceCoverage> {
  return Object.fromEntries(Object.entries(object(value)).filter(([paper, row]) => paper.length <= 200 && Object.keys(object(row)).length > 0).map(([paper, value]) => {
    const row = object(value), projected: ObjectRow = {};
    for (const key of ["indexed_chunks_total", "bounded_indexed_chunks_total", "chunks_considered", "chunks_inspected", "chunks_supplied", "excluded_chunks_total", "omitted_chunks_total"]) {
      const number = row[key];
      if (number === null || (typeof number === "number" && Number.isSafeInteger(number) && number >= 0)) projected[key] = number;
    }
    for (const key of ["fulltext_checked", "supplement_checked", "truncated"]) if (typeof row[key] === "boolean") projected[key] = row[key];
    if (code(row.scope)) projected.scope = row.scope;
    return [paper, { ...projected, excluded_chunk_reasons: countMap(row.excluded_chunk_reasons), omitted_chunk_reasons: countMap(row.omitted_chunk_reasons), reason_codes: codes(row.reason_codes) }];
  })) as Record<string, MaterialSourceCoverage>;
}
const COUNT_KEYS = ["materials", "retained_records", "raw_retained_records", "retained_records_inspected", "retained_records_omitted", "source_captures", "primary_source_captures", "candidate_facts", "candidate_retained_references", "candidate_facts_returned", "candidate_facts_omitted", "source_record_statement_matches", "source_record_matches_omitted", "source_record_matches_truncated", "review_findings", "report_row_limit", "source_record_review_findings_total", "source_record_review_findings_omitted", "source_record_review_findings_truncated", "promoted_facts"];
/** Export only the currently returned, pending public metadata. This is neither a full report clone nor an INSERT package. */
export function materialRecoveryMetadata(report: MaterialEnrichmentReport, materialId: string, preparedAt = new Date().toISOString()) {
  const coverage = report.coverage.find(row => row.material_id === materialId);
  if (!coverage || report.version !== "materials-enrichment/1.0.0" || report.scientific_acceptance !== false || report.database_changed !== false) return null;
  const literals = report.candidates.map(row => candidate(row, materialId, false)).filter((row): row is ObjectRow => row !== null);
  const statements = (report.classification_candidates ?? []).map(row => candidate(row, materialId, true)).filter((row): row is ObjectRow => row !== null);
  return {
    version: "materials-recovery-metadata/1.0.0", prepared_at_utc: preparedAt,
    scope: "Allowlisted metadata from this material’s current bounded recovery response; not complete papers, supplements or an import payload",
    material: { material_id: materialId, formula: coverage.formula },
    report_identity: pick(report, ["version", "extractor_version", "classification_extractor_version", "input_sha256", "report_sha256"]),
    scientific_acceptance: false, database_changed: false, ml_training_approved: false, public_release: false, disposition: "pending", source_content_checked: false, material_state_reviewed: false,
    primary_source_seed: pick(object(report).primary_source_seed, ["status", "seed_id", "seed_sha256", "candidate_facts_added"]),
    classification_primary_source_seed: pick(object(report).classification_primary_source_seed, ["status", "seed_id", "seed_sha256", "candidate_facts_added"]),
    inspection_scope: pick(report.inspection_scope, ["version", "records_total", "records_inspected", "records_truncated", "records_limit", "raw_retained_records_total", "current_eligible_records_total", "papers_total", "papers_inspected", "papers_truncated", "papers_limit", "papers_with_bounded_indexed_chunks", "record_sampling", "paper_sampling", "chunks_considered", "chunks_inspected", "chunks_limit", "characters_inspected", "characters_limit", "chunk_sampling"]),
    source_coverage: projectSourceCoverage(coverage.source_coverage),
    coverage: coverage.fields.map(row => ({ ...pick(row, ["field", "status", "retained_present", "candidate_count", "classification_review_finding_count"]), reason_codes: codes(row.reason_codes), routes: codes(row.routes) })),
    counts: pick(report.counts, COUNT_KEYS), classification_counts: pick(report.classification_counts, COUNT_KEYS),
    returned_window: { literal_received: report.candidates.length, literal_exported: literals.length, literal_truncated: report.candidates_truncated === true, classification_received: report.classification_candidates?.length ?? 0, classification_exported: statements.length, classification_truncated: report.classification_candidates_truncated === true, review_findings_truncated: report.classification_review_findings_truncated === true, rejected_candidate_count: report.candidates.length + (report.classification_candidates?.length ?? 0) - literals.length - statements.length },
    candidates: literals, classification_candidates: statements,
    classification_review_findings: (report.classification_review_findings ?? []).filter(row => row.material_id === materialId).map(row => ({ ...pick(row, ["material_id", "retained_result_id", "retained_record_sha256"]), fields: codes(row.fields).filter(field => CLASSIFICATION_FIELDS.includes(field)), reason_codes: codes(row.reason_codes), source: source(row.source) })),
    limitations: ["Candidate identities are retained for reference; this redacted projection is not the original hash-validation payload", "Retained result references do not establish physical sample or state associations, scientific validity, source permissions, or independent experiments", "Unreturned candidates and unchecked sources remain unresolved; no source text or private context is exported"],
  };
}
export function downloadMaterialRecoveryMetadata(report: MaterialEnrichmentReport, materialId: string): boolean {
  const metadata = materialRecoveryMetadata(report, materialId);
  if (!metadata) return false;
  const url = URL.createObjectURL(new Blob([JSON.stringify(metadata, null, 2) + "\n"], { type: "application/json;charset=utf-8" }));
  let link: HTMLAnchorElement | null = null;
  try {
    link = document.createElement("a");
    link.href = url;
    link.download = `materials-recovery-${materialId.replace(/[^a-zA-Z0-9._-]/g, "_")}.json`;
    document.body.appendChild(link);
    link.click();
    return true;
  } finally {
    link?.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
