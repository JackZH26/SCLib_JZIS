export interface ReportQuantity {
  status: string; relation: string; value: number | null; lower: number | null; upper: number | null;
  unit: string; raw_value?: unknown; uncertainty?: number | null; approximate?: boolean; reason?: string | null;
}
export interface MaterialReportPoint {
  point_id: string; event_id: string | null; work_id: string | null; paper_id: string | null;
  title: string | null; year: number | null; sample_label: string | null; sample_form: string | null;
  series_id: string | null; path_direction: string; point_label: string | null; replicate_label: string | null;
  sc_outcome: string; tc: ReportQuantity; pressure: ReportQuantity;
  pressure_semantics?: string;
  pressure_role?: "measurement_pressure" | "calculation_pressure" | "unknown";
  conditions?: Array<{ key: string; status: string; quantity: ReportQuantity; value_raw?: string | null }>;
  tc_definition: string; method: string | null; knowledge_origin: string; source_role: string;
  minimum_test_temperature: ReportQuantity; source_locator: Record<string, unknown>;
  properties: Array<{ key: string; quantity: ReportQuantity; unit: string; value_raw?: string | null; knowledge_origin?: string; source_role?: string }>;
  identity_status: string; review_status: string;
  fixed_conditions_sha256?: string;
}
export interface MaterialReports {
  version: "material-reports/3.0"; material_id: string; display_formula?: string; projection_kind: string;
  total_points: number; offset: number; limit: number; has_more: boolean;
  report_groups: Array<{ group_id: string; work_id: string | null; points: MaterialReportPoint[] }>;
  support_counts: { source_ids: number; verified_unique_works: number; work_identity_unknown_sources: number;
    result_points: number; independent_data_groups: number | null; cited_report_points: number };
  coverage: { status: string; no_claim_found_allowed: boolean }; scientific_acceptance: false;
}

export function reportQuantity(q: ReportQuantity | null | undefined): string {
  if (!q || q.status !== "parsed") {
    const labels: Record<string, string> = {
      unresolved: "Value needs review", ambiguous: "Ambiguous", invalid: "Value needs review",
      unparsed: "Value needs review", source_unavailable: "Source unavailable",
      extraction_failed: "Extraction failed", explicitly_not_measured: "Not measured",
      not_applicable: "Not applicable",
    };
    return labels[q?.status ?? ""] ?? "Not reported";
  }
  const number = (v: number | null) => v === null ? "Unknown" : v.toLocaleString("en-US", { maximumSignificantDigits: 8 });
  const prefix = q.approximate ? "≈ " : "";
  const value = q.relation === "exact" || q.relation === "point" ? number(q.value)
    : q.relation === "interval" ? `${number(q.lower)}–${number(q.upper)}`
    : q.relation === "lt" || q.relation === "le" ? `${q.relation === "lt" ? "<" : "≤"} ${number(q.upper)}`
    : q.relation === "gt" || q.relation === "ge" ? `${q.relation === "gt" ? ">" : "≥"} ${number(q.lower)}` : "Unknown";
  return `${prefix}${value}${q.uncertainty !== null && q.uncertainty !== undefined ? ` ± ${number(q.uncertainty)}` : ""}${q.unit === "1" || !q.unit ? "" : ` ${q.unit}`}`;
}

export function reportPropertyLabel(key: string): string {
  const labels: Record<string, string> = {
    electron_phonon_lambda: "Electron–phonon λ", coulomb_mu_star: "Coulomb μ*", omega_log: "ω log",
    upper_critical_field: "Upper critical field", lower_critical_field: "Lower critical field",
    critical_current_density: "Critical current density", coherence_length: "Coherence length",
    penetration_depth: "Penetration depth", superfluid_density: "Superfluid density",
    superfluid_stiffness: "Superfluid stiffness", gap_energy: "Gap energy", pairing_symmetry: "Pairing symmetry",
  };
  return labels[key] ?? key.replaceAll("_", " ");
}

export function reportPressureRole(role: MaterialReportPoint["pressure_role"]): string {
  return role === "calculation_pressure" ? "Calculation pressure"
    : role === "measurement_pressure" ? "Measurement pressure" : "Pressure role unresolved";
}

export function reportLocator(locator: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, label] of [["page", "Page"], ["pages", "Pages"], ["section", "Section"], ["table", "Table"], ["row", "Row"], ["column", "Column"], ["figure", "Figure"]]) {
    const value = locator[key];
    if (typeof value === "string" && value.trim()) parts.push(`${label}: ${value}`);
    else if (typeof value === "number" && Number.isFinite(value)) parts.push(`${label}: ${value.toLocaleString("en-US")}`);
    else if (Array.isArray(value) && value.every(v => typeof v === "number" || typeof v === "string")) parts.push(`${label}: ${value.join(", ")}`);
  }
  return parts.join(" · ") || (Object.keys(locator).length ? "Source passage recorded; page or table label awaits review" : "Locator not supplied in this extraction");
}

export function outcomeLabel(outcome: string): string {
  const labels: Record<string, string> = { not_detected: "Not detected", inconclusive: "Inconclusive", positive_reported: "Positive report", observed: "Positive report", unknown: "Outcome not supplied" };
  return labels[outcome] ?? "Outcome not supplied";
}

/** Curve identity needs every explicit source/sample/path/criterion component. */
export function curveGroup(point: MaterialReportPoint): string | null {
  if (!point.work_id || !point.sample_label || !point.series_id || !point.fixed_conditions_sha256 || point.path_direction === "unknown" || point.tc_definition === "unknown" || point.source_role === "unknown" || point.knowledge_origin === "Unknown" || point.sc_outcome !== "positive_reported") return null;
  if (!point.pressure_role || point.pressure_role === "unknown") return null;
  if (point.pressure.status !== "parsed" || !["exact", "point"].includes(point.pressure.relation) || point.tc.status !== "parsed" || !["exact", "point"].includes(point.tc.relation)) return null;
  return JSON.stringify([point.work_id, point.sample_label, point.series_id, point.path_direction, point.tc_definition, point.knowledge_origin, point.source_role, point.replicate_label, point.method, point.pressure_role, point.fixed_conditions_sha256]);
}
