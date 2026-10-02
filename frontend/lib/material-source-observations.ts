import rawBatch from "@/public/research-pilots/materials-source-observations-2026-10-02.json";
import type { MaterialEnrichmentReport, MaterialStructureReferences } from "@/lib/api";
import { materialRecoveryMetadata } from "@/lib/material-recovery-metadata";

type Row = Record<string, unknown>;
const isRow = (v: unknown): v is Row => v != null && typeof v === "object" && !Array.isArray(v);
const row = (v: unknown): Row => isRow(v) ? v : {};
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 2000;
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const closed = (v: unknown, keys: string[]) => isRow(v) && Object.keys(v).every(key => keys.includes(key));
const scalar = (v: unknown) => v === null || typeof v === "boolean" || finite(v) || typeof v === "string" && v.length <= 2000;
const scalarExcept = (v: unknown, nested: string[] = []) => Object.entries(row(v)).every(([key, value]) => nested.includes(key) || scalar(value));
const FLAGS = ["formal_human_review", "formal_scientific_review", "scientific_acceptance", "ml_training_approved", "database_changed", "sample_identity_established", "phase_identity_established", "public_release_completed_at_preparation"];
const QUANTITY_KEYS = ["raw_value", "value", "raw_unit", "unit", "approximate", "raw_uncertainty", "uncertainty", "uncertainty_interpretation", "uncertainty_normalization", "unit_basis", "unit_source_field"];
const SOURCE_KEYS = ["capture_id", "paper_id", "kind", "source_url", "source_revision", "source_revision_basis", "publication_revision_verified", "source_status", "current_publication_status", "captured_at_utc", "capture_sha256", "content_sha256", "locator", "span", "provider", "cod_id", "captured_revision", "entry_url", "file_sha256", "bytes", "license", "license_basis", "coordinate_model_validated"];
const WINDOW_KEYS = ["id", "magnetic_field_direction_raw", "curve_criterion_raw", "slope_temperature_window_raw", "pressure", "pressure_status", "model_temperature_k", "model_label", "pressure_expression_raw", "pressure_gpa", "pressure_normalization", "method_scope", "source_column", "raw_column_header", "raw_row_label", "measurement_temperature_k", "temperature_role", "temperature_k", "conditions_status", "source_year"];
const LOCATOR_KEYS = ["char_start", "char_end", "token_sha256", "spans", "table_column", "table_row_label", "line_start", "line_end", "physical_span_sha256"];
const ORIGINAL_BATCH_SHA = "947e13d7947f27d9d291a3783ad262308babcec14c186de0e5fbf1c70b8a884f";
const PRIOR_BATCH_SHA = "1bdc386c9f67bfa4a454ee17c07910ee72ee49b0f1adfb656dba56a60735fdd2";
export const sourceObservationDownloadPath = `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/materials-source-observations-2026-10-02.json`;

const profiles: Record<string, { group: string; role: string; unit?: string; label: string }> = {
  hc2_temperature_slope: { group: "pt", role: "source_curve_derived_slope", unit: "T/K", label: "dHc₂/dT" },
  hc2_whh_orbital_zero_temperature: { group: "pt", role: "source_reported_model_estimate", unit: "T", label: "Hc₂(0) · WHH orbital estimate" },
  hc2_linear_zero_temperature: { group: "pt", role: "source_reported_model_estimate", unit: "T", label: "Hc₂(0) · linear extrapolation" },
  hc2_resistive_criterion: { group: "pt", role: "curve_definition", unit: "%", label: "Hc₂ curve criterion" },
  hc2_measurement_window: { group: "pt", role: "source_condition_expression", label: "Field and temperature window" },
  ambient_fitted_tc: { group: "cs_nb", role: "source_reported_fit", unit: "K", label: "Tc · prose fit" },
  ambient_fitted_penetration: { group: "cs_nb", role: "source_reported_fit", unit: "nm", label: "London penetration depth · prose fit" },
  ambient_fitted_gap: { group: "cs_nb", role: "source_reported_fit", unit: "meV", label: "Gap Δ₀ · prose fit" },
  zero_gpa_table_tc: { group: "cs_nb", role: "source_reported_fit_table", unit: "K", label: "Tc · table fit" },
  zero_gpa_table_penetration: { group: "cs_nb", role: "source_reported_fit_table", unit: "nm", label: "London penetration depth · λ(T > 0)" },
  zero_gpa_table_gap_1: { group: "cs_nb", role: "source_reported_fit_table", unit: "meV", label: "Gap Δ₁ · table fit" },
  listed_atomic_sites: { group: "crb2_cif", role: "listed_CIF_source_metadata", label: "Listed atomic sites" },
  declared_symmetry_operations: { group: "crb2_cif", role: "listed_CIF_source_metadata", label: "Declared symmetry operations" },
  reported_hall_symbol: { group: "crb2_cif", role: "listed_CIF_source_metadata", label: "Declared Hall symbol" },
  cell_formula_units_z: { group: "crb2_cif", role: "listed_CIF_source_metadata", unit: "dimensionless", label: "Formula units per cell · Z" },
};
export interface SourceObservation {
  id: string; source_group: string; field: string; value: unknown; source_role: string;
  source_subject: Row; source_window: Row; source: Row; field_locator: Row;
  limitations: string[]; selected_result_association: "unestablished";
}
export interface SourceObservationBatch {
  version: "materials-source-observations/1.0.0"; prepared_on: string;
  original_batch_sha256: string; source_case_count: number; field_projection_count: number;
  prior_source_expression_batch_sha256: string;
  entries: SourceObservation[];
}
export interface SourceObservationWindow {
  version: "material-source-observation-window/1.0.0";
  view_context: { material_id: string | null; matching_basis: string };
  original_batch_sha256: string; entries: SourceObservation[];
  prior_source_expression_batch_sha256: string;
  scientific_acceptance: false; canonical_promotions: 0; selected_result_association: "unestablished";
}

export function sourceObservationUrl(value: unknown): string | null {
  if (!text(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port && ["arxiv.org", "www.crystallography.net"].includes(url.hostname) ? url.href : null;
  } catch { return null; }
}
function quantity(v: unknown, unit: string): boolean {
  const q = row(v);
  const fieldDerivedUnit = q.raw_unit === null && (
    unit === "fractional" && q.unit_basis === "cif_fractional_coordinate_field" && ["_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z"].includes(String(q.unit_source_field))
    || unit === "dimensionless" && (q.unit_basis === "cif_atom_site_occupancy_field" && q.unit_source_field === "_atom_site_occupancy"
      || q.unit_basis === "cif_formula_units_z_field" && q.unit_source_field === "_cell_formula_units_Z"));
  const printedUnit = q.raw_unit === unit && q.unit_basis === undefined && q.unit_source_field === undefined;
  if (!(closed(q, QUANTITY_KEYS) && scalarExcept(q) && text(q.raw_value) && finite(q.value) && q.unit === unit && (printedUnit || fieldDerivedUnit)
    && typeof q.approximate === "boolean" && (q.uncertainty === null || finite(q.uncertainty) && q.uncertainty >= 0)
    && (q.raw_uncertainty === null || text(q.raw_uncertainty)) && text(q.uncertainty_interpretation)
    && (q.uncertainty_normalization === null || text(q.uncertainty_normalization)))) return false;
  const match = q.raw_value.match(/^([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:\((\d+)\))?$/);
  if (!match || Number(match[1]) !== q.value) return false;
  if (!match[2]) return q.raw_uncertainty === null && q.uncertainty === null && q.uncertainty_normalization === null;
  const sigma = Number(match[2]) * 10 ** -(match[1].split(".")[1]?.length ?? 0);
  return q.raw_uncertainty === match[2] && finite(q.uncertainty) && Math.abs(sigma - q.uncertainty) < 1e-12
    && q.uncertainty_normalization === "parentheses_in_last_displayed_digits";
}
function source(v: unknown, requireStatus = true): boolean {
  const s = row(v);
  if (!closed(s, SOURCE_KEYS) || !scalarExcept(s, ["locator", "span"]) || !sourceObservationUrl(s.source_url) || requireStatus && s.current_publication_status !== "not_checked" || !requireStatus && s.current_publication_status !== undefined && s.current_publication_status !== "not_checked") return false;
  if (s.provider === "COD") return closed(s, ["provider", "cod_id", "captured_revision", "source_url", "entry_url", "file_sha256", "bytes", "license", "license_basis", "current_publication_status", "coordinate_model_validated"])
    && s.cod_id === "1510641" && s.captured_revision === 176435 && hash(s.file_sha256) && s.coordinate_model_validated === false && s.license === "CC0-1.0";
  return text(s.paper_id) && text(s.capture_id) && hash(s.content_sha256) && s.publication_revision_verified === false
    && ["original_passage", "table"].includes(String(s.kind)) && closed(s.locator, ["xml_xpath", "table", "section"]) && scalarExcept(s.locator)
    && text(row(s.locator).xml_xpath)
    && (s.capture_sha256 === undefined || hash(s.capture_sha256)) && (s.span === undefined || closed(s.span, ["char_start", "char_end", "text_sha256"]) && scalarExcept(s.span)
      && unsignedInteger(row(s.span).char_start) && unsignedInteger(row(s.span).char_end) && Number(row(s.span).char_end) > Number(row(s.span).char_start) && hash(row(s.span).text_sha256));
}
const unsignedInteger = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
function literalSpan(v: unknown): boolean {
  const span = row(v);
  return unsignedInteger(span.char_start) && unsignedInteger(span.char_end) && Number(span.char_end) > Number(span.char_start) && hash(span.token_sha256);
}
/** Window-specific requirements keep hard-coded scientific labels tied to the supplied conditions. */
function windowAndLocator(e: Row): boolean {
  const w = row(e.source_window), l = row(e.field_locator), field = String(e.field);
  if (e.source_group === "pt") {
    if (w.magnetic_field_direction_raw !== "parallel to the c-axis" || w.curve_criterion_raw !== "50% resistive transition" || w.slope_temperature_window_raw !== "T<20 K"
      || w.pressure !== null || w.pressure_status !== "not_supplied_in_this_source_scope") return false;
    if (field === "hc2_whh_orbital_zero_temperature" && (w.model_temperature_k !== 0 || w.model_label !== "WHH orbital estimate")) return false;
    if (field === "hc2_linear_zero_temperature" && (w.model_temperature_k !== 0 || w.model_label !== "linear extrapolation")) return false;
    return field === "hc2_measurement_window" ? Array.isArray(l.spans) && l.spans.length === 2 && l.spans.every(literalSpan) : literalSpan(l);
  }
  if (e.source_group === "cs_nb") {
    if (!literalSpan(l)) return false;
    if (field.startsWith("ambient_")) return w.id === "ambient_prose_fit" && w.pressure_expression_raw === "ambient conditions" && w.pressure_gpa === null
      && w.pressure_normalization === "not_numericized_from_ambient" && w.method_scope === "muon relaxation and superfluid-density fitting";
    const labels: Record<string, string> = { zero_gpa_table_tc: "T_{\\mathrm{C}} (K)", zero_gpa_table_penetration: "\\lambda(T>0) (nm)", zero_gpa_table_gap_1: "\\Delta_{1} (meV)" };
    return w.id === "pressure_series_table_zero_column" && quantity(w.pressure, "GPa") && row(w.pressure).value === 0 && w.source_column === 1 && w.raw_column_header === "0"
      && w.raw_row_label === labels[field] && w.measurement_temperature_k === null && w.temperature_role === "retain_row_label; not inferred"
      && l.table_column === 1 && l.table_row_label === labels[field];
  }
  return w.temperature_k === null && w.pressure_gpa === null && w.conditions_status === "not_supplied_in_captured_CIF" && w.source_year === 1954
    && unsignedInteger(l.line_start) && Number(l.line_start) > 0 && unsignedInteger(l.line_end) && Number(l.line_end) >= Number(l.line_start) && hash(l.physical_span_sha256);
}
function subject(v: unknown): boolean {
  const s = row(v);
  if (!closed(s, ["source_formula_raw", "source_alias_raw", "source_formula_definition_proposal", "catalogue_association", "composition_kind"]) || !scalarExcept(s, ["source_formula_definition_proposal"]) || s.catalogue_association !== "unestablished") return false;
  if (s.source_formula_definition_proposal) {
    const p = row(s.source_formula_definition_proposal);
    if (!closed(p, ["formula", "doping_assignment_raw", "association_reviewed", "source"]) || !scalarExcept(p, ["source"]) || p.association_reviewed !== false || !source(p.source, false)) return false;
  }
  return text(s.source_formula_raw) || text(s.source_alias_raw);
}
function observation(v: unknown): v is SourceObservation {
  const e = row(v), p = profiles[String(e.field)];
  if (!p || e.source_group !== p.group || e.source_role !== p.role || e.id !== `source-only:${p.group}:${e.field}`
    || !closed(e, ["id", "source_group", "field", "value", "source_subject", "source_window", "source_role", "source", "field_locator", "association_status", "limitations", "canonical_promotions", "selected_result_association", ...FLAGS])
    || FLAGS.some(key => e[key] !== false) || e.canonical_promotions !== 0 || e.association_status !== "unestablished" || e.selected_result_association !== "unestablished"
    || !source(e.source) || !subject(e.source_subject) || !closed(e.source_window, WINDOW_KEYS) || !scalarExcept(e.source_window, ["pressure"]) || !closed(e.field_locator, LOCATOR_KEYS) || !scalarExcept(e.field_locator, ["spans"])
    || !Array.isArray(e.limitations) || !e.limitations.every(text)) return false;
  const w = row(e.source_window), l = row(e.field_locator);
  if (!windowAndLocator(e)) return false;
  if (w.pressure != null && !quantity(w.pressure, "GPa")) return false;
  if (l.spans !== undefined && (!Array.isArray(l.spans) || !l.spans.every(v => closed(v, ["char_start", "char_end", "token_sha256"]) && scalarExcept(v)) )) return false;
  if (p.unit) return quantity(e.value, p.unit) && (e.field !== "cell_formula_units_z" || row(e.value).unit_basis === "cif_formula_units_z_field" && row(e.value).unit_source_field === "_cell_formula_units_Z");
  if (e.field === "hc2_measurement_window") return closed(e.value, ["field_direction_raw", "temperature_raw"])
    && row(e.value).field_direction_raw === w.magnetic_field_direction_raw && row(e.value).temperature_raw === w.slope_temperature_window_raw;
  if (e.field === "reported_hall_symbol") return text(e.value);
  if (e.field === "declared_symmetry_operations") return Array.isArray(e.value) && e.value.length === 24 && e.value.every(v => text(v) && /^[xyz0-9,+\- /]+$/.test(v));
  return Array.isArray(e.value) && e.value.length === 2 && e.value.every(v => {
    const s = row(v);
    return closed(s, ["label", "element", "fractional_coordinates", "occupancy", "physical_source_line", "source_line_sha256"]) && scalarExcept(s, ["fractional_coordinates", "occupancy"])
      && text(s.label) && /^[A-Z][a-z]?$/.test(String(s.element)) && hash(s.source_line_sha256)
      && Array.isArray(s.fractional_coordinates) && s.fractional_coordinates.length === 3 && s.fractional_coordinates.every((q, axis) => quantity(q, "fractional") && row(q).unit_source_field === ["_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z"][axis])
      && quantity(s.occupancy, "dimensionless") && row(s.occupancy).unit_source_field === "_atom_site_occupancy";
  });
}
function matchesSnapshot(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 24) return false;
  if (expected === null || typeof expected !== "object") return value === expected;
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length && value.length <= 128
    && value.every((entry, index) => matchesSnapshot(entry, expected[index], depth + 1));
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const current = value as Record<string, unknown>, pinned = expected as Record<string, unknown>, keys = Object.keys(pinned);
  return keys.length <= 64 && Object.keys(current).length === keys.length
    && keys.every(key => Object.hasOwn(current, key) && matchesSnapshot(current[key], pinned[key], depth + 1));
}
function matchesPinnedObservation(entry: SourceObservation): boolean {
  const expected = rawBatch.entries.find(value => value.id === entry.id);
  return expected !== undefined && matchesSnapshot(entry, expected);
}
/** Checks the closed mapping and finite inspected snapshot, not scientific validity or source rights. */
export function loadSourceObservationBatch(value: unknown = rawBatch): SourceObservationBatch | null {
  const b = row(value);
  if (!closed(b, ["version", "prepared_on", "scope", "source_case_count", "field_projection_count", "field_count_is_independent_experiments", "ai_source_expression_inspected", "fulltext_or_private_context_included", "entries", "original_batch_sha256", "prior_source_expression_batch_sha256", "canonical_promotions", "selected_result_association", ...FLAGS]) || !scalarExcept(b, ["entries"])
    || b.version !== "materials-source-observations/1.0.0" || b.original_batch_sha256 !== ORIGINAL_BATCH_SHA || b.prior_source_expression_batch_sha256 !== PRIOR_BATCH_SHA
    || FLAGS.some(key => b[key] !== false) || b.canonical_promotions !== 0 || b.selected_result_association !== "unestablished"
    || b.field_count_is_independent_experiments !== false || b.fulltext_or_private_context_included !== false
    || b.ai_source_expression_inspected !== true || !/^\d{4}-\d{2}-\d{2}$/.test(String(b.prepared_on)) || b.source_case_count !== 3 || b.field_projection_count !== 15 || !Array.isArray(b.entries) || b.entries.length !== 15
    || !b.entries.every(observation) || new Set(b.entries.map(e => e.id)).size !== 15 || !matchesSnapshot(b, rawBatch)) return null;
  return JSON.parse(JSON.stringify(b)) as SourceObservationBatch;
}
export function sourceObservationWindow(entries: SourceObservation[], materialId: string | null, basis: string): SourceObservationWindow | null {
  if (!entries.length || entries.length > 15 || !entries.every(entry => observation(entry) && matchesPinnedObservation(entry)) || new Set(entries.map(e => e.id)).size !== entries.length || !text(basis) || materialId !== null && !text(materialId)) return null;
  return { version: "material-source-observation-window/1.0.0", view_context: { material_id: materialId, matching_basis: basis }, original_batch_sha256: ORIGINAL_BATCH_SHA, prior_source_expression_batch_sha256: PRIOR_BATCH_SHA,
    entries: JSON.parse(JSON.stringify(entries)), scientific_acceptance: false, canonical_promotions: 0, selected_result_association: "unestablished" };
}
const PT_SEED_SHA = "810b25f4bec44212efe739a1b03d60bfc83c71cabd89bdfd332b9c1fde70c534";
const CS_SEED_SHA = "6aa56ccc9b4f1cfbf110dfa692cb4f6474539a674399414040346943db671787";
const CS_PINS = [
  ["classification:cad03c6b89722d39ae71eaabd924d9221029f5384de8bf81b0b4e0160d339da9", "92964ee349d7364a6ceb2d7b8f10cb5039a94d5714370ddbe11f5b5175163901"],
  ["classification:fcfa8a6d19f6ccea5a5f34759b515ff03af8670c3d56df153149c234695b6418", "b9ec10f918b41c83182f8ac6b4daa193495a3bfa3b7e4e55dd38b71b892d3195"],
];
/** The API already checks current retained fingerprints before exposing its immutable seed. No formula-only fallback. */
export function sourceObservationsForRecovery(report: MaterialEnrichmentReport, materialId: string): SourceObservationWindow | null {
  const metadata = materialRecoveryMetadata(report, materialId), batch = loadSourceObservationBatch();
  if (!metadata || !batch) return null;
  let group: string | null = null;
  if (materialId === "mat:bafe1.906pt0.094as2" && metadata.primary_source_seed.status === "available" && metadata.primary_source_seed.seed_sha256 === PT_SEED_SHA
    && metadata.candidates.some(c => row(c.source).paper_id === "arxiv:0912.2752" && row(c.source).capture_sha256 === "f74c213adefb0dafe0dde174be506aeeceb00eb0faaaf252891bd2f65d452c9d")) group = "pt";
  if (materialId === "mat:cs(v0.93nb0.07)3sb5" && metadata.classification_primary_source_seed.status === "available" && metadata.classification_primary_source_seed.seed_sha256 === CS_SEED_SHA
    && CS_PINS.every(([id, sha]) => metadata.classification_candidates.some(c => c.candidate_id === id && row(c.source).paper_id === "arxiv:2411.18744" && row(c.source).source_revision === "arxiv:2411.18744v1" && row(c.source).content_sha256 === sha))) group = "cs_nb";
  return group ? sourceObservationWindow(batch.entries.filter(e => e.source_group === group), materialId, "Current recovery seed source is present; additional source windows remain unassociated with the selected result") : null;
}
export function sourceObservationsForCod(report: MaterialStructureReferences, materialId: string): SourceObservationWindow | null {
  const batch = loadSourceObservationBatch();
  if (!batch || report.version !== "material-crystal-references/1.0.0" || report.provider !== "COD" || report.status !== "available"
    || report.scientific_acceptance !== false || report.database_changed !== false || report.sample_identity_established !== false || report.phase_identity_established !== false
    || !report.references.some(r => r.id === "1510641" && r.source_revision === "svn:176435" && r.coordinate_model_validated === false && r.sample_identity_established === false && r.phase_identity_established === false)) return null;
  return sourceObservationWindow(batch.entries.filter(e => e.source_group === "crb2_cif"), materialId, "Matching returned COD identifier and revision; captured CIF metadata is an independent reference");
}
export const observationLabel = (field: string) => profiles[field]?.label ?? "Source field";
export function observationValue(e: SourceObservation): string {
  if (e.field === "reported_hall_symbol") return String(e.value);
  if (e.field === "listed_atomic_sites") return "2 listed asymmetric-unit sites";
  if (e.field === "declared_symmetry_operations") return "24 declared operations";
  if (e.field === "hc2_measurement_window") return `${row(e.value).field_direction_raw} · ${row(e.value).temperature_raw}`;
  const q = row(e.value);
  return `${q.approximate ? "≈ " : ""}${q.raw_value}${q.unit === "dimensionless" ? "" : ` ${q.unit}`}`;
}
export function groupSourceObservations(entries: SourceObservation[]) {
  const groups = new Map<string, { id: string; label: string; entries: SourceObservation[] }>();
  for (const e of entries) {
    const id = e.source_group === "cs_nb" ? String(e.source_window.id) : e.source_group;
    const label = id === "pt" ? "Pt substituted BaFe₂As₂ · Hc₂ curve" : id === "ambient_prose_fit" ? "Nb₀.₀₇–CVS · ambient prose fit" : id === "pressure_series_table_zero_column" ? "Nb₀.₀₇–CVS · pressure-series table, 0 GPa" : "CrB₂ · captured COD 1510641, revision 176435";
    if (!groups.has(id)) groups.set(id, { id, label, entries: [] });
    groups.get(id)!.entries.push(e);
  }
  return [...groups.values()];
}
export function downloadSourceObservationWindow(window: SourceObservationWindow): boolean {
  const checked = sourceObservationWindow(window.entries, window.view_context.material_id, window.view_context.matching_basis);
  if (!checked) return false;
  const url = URL.createObjectURL(new Blob([JSON.stringify(checked, null, 2) + "\n"], { type: "application/json;charset=utf-8" }));
  let link: HTMLAnchorElement | null = null;
  try {
    link = document.createElement("a"); link.href = url;
    link.download = `source-observations-${(checked.view_context.material_id ?? "independent-sources").replace(/[^a-zA-Z0-9._-]/g, "_")}.json`;
    document.body.appendChild(link); link.click(); return true;
  } finally { link?.remove(); setTimeout(() => URL.revokeObjectURL(url), 0); }
}
