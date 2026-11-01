import type { TcDisplayPolicy } from "./tc-display-policy";

export type AdmittedTcResult = {
  id: string; material_id: string; formula: string; family?: string;
  display?: Record<string, string>;
  compositions: { formula: string; basis: string }[];
  sample_label: string | null; sample_form: string | null; substrate: string | null;
  value_kelvin: number | null; value_lower_kelvin: number | null; value_upper_kelvin: number | null;
  value_relation: string; quantity: { raw: string; unit: string | null; approximate: boolean };
  criterion: string; criterion_raw?: string | null; method: string; method_raw: string | null; measurement_context: string | null;
  pressure_regime: "explicit_ambient" | "nonambient" | "unknown";
  pressure_gpa: number | null; pressure_raw: string | null;
  paper_id: string; paper_title: string; source_url: string; source_versions: string[];
  evidence: { locator: string; page: number | null; quote_sha256: string; field_paths: string[] }[];
  validity_status: string;
  review: { quality_status: "model_source_checked" | "batch_sampled"; per_record_checked: boolean;
    admission_route?: "qualified_batch" | "individual_source_check"; batch_qualified?: boolean;
    independent_expert_review: false; complete_paper: false };
};

export type AdmittedTcPage = {
  display_policy?: TcDisplayPolicy;
  items: AdmittedTcResult[]; total: number; material_count: number; paper_count: number;
  limit: number; offset: number; dataset: string; count_scope: string;
};

export type MaterialsDataset = {
  version: string; created_at: string; paper_count: number;
  files: Record<"results" | "evidence" | "training", { rows: number; columns: number; sha256: string }>;
  source_scope: string; training_policy: string; grouping_policy: string;
};

export const tcCriteria: Record<string, string> = {
  onset: "Onset", midpoint: "Midpoint", zero_resistance: "Zero resistance",
  diamagnetic_onset: "Diamagnetic onset", heat_capacity_anomaly: "Heat-capacity anomaly",
  unspecified: "Not specified",
};

export function admittedTcLabel(row: AdmittedTcResult): string {
  const approximate = row.quantity.approximate ? "≈ " : "";
  if (row.value_relation === "exact" && row.value_kelvin !== null) return `${approximate}${row.value_kelvin} K`;
  if (row.value_relation === "interval" && row.value_lower_kelvin !== null && row.value_upper_kelvin !== null) return `${approximate}${row.value_lower_kelvin}–${row.value_upper_kelvin} K`;
  if (["lt", "le"].includes(row.value_relation) && row.value_upper_kelvin !== null) return `${row.value_relation === "lt" ? "<" : "≤"} ${approximate}${row.value_upper_kelvin} K`;
  if (["gt", "ge"].includes(row.value_relation) && row.value_lower_kelvin !== null) return `${row.value_relation === "gt" ? ">" : "≥"} ${approximate}${row.value_lower_kelvin} K`;
  return row.quantity.raw;
}

export function admittedPressureLabel(row: AdmittedTcResult): string {
  if (row.pressure_regime === "explicit_ambient") return "Ambient pressure";
  if (row.pressure_gpa !== null) return `${row.pressure_gpa} GPa`;
  if (row.pressure_raw) return row.pressure_raw;
  return row.pressure_regime === "nonambient" ? "Nonambient pressure; value unavailable" : "Pressure not reported";
}

/** Apply only presentation strings supplied by the source-bound API reader. */
export function materialDisplay(row: AdmittedTcResult): AdmittedTcResult {
  const d = row.display ?? {};
  const text = (key: string, raw: string | null | undefined) => d[key] ?? raw;
  return { ...row, formula: d.formula ?? row.formula,
    sample_label: text("sample_label", row.sample_label) ?? null,
    sample_form: text("sample_form", row.sample_form) ?? null,
    substrate: text("substrate", row.substrate) ?? null,
    method_raw: text("method_raw", row.method_raw) ?? null,
    criterion_raw: text("criterion_raw", row.criterion_raw) ?? null,
    measurement_context: text("measurement_context", row.measurement_context) ?? null,
    pressure_raw: text("pressure_raw", row.pressure_raw) ?? null,
    paper_title: d.paper_title ?? row.paper_title,
    quantity: { ...row.quantity, raw: d.quantity_raw ?? row.quantity.raw },
    compositions: row.compositions.map((c, i) => ({ ...c, formula: d[`composition:${i}`] ?? c.formula })),
  };
}
