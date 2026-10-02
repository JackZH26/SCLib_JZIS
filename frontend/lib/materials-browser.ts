/** URL and result presentation for the Materials browser. No legacy scalar joins. */
import type { MaterialListParams, MaterialSummary, MatchingScientificResult, PropertyEvidenceItem } from "@/lib/api";
import { eligibleAtomicItem, hasPropertyContract, objectValue, selectedProperty } from "@/lib/property-evidence";
import { visibilityIsRestricted } from "@/lib/material-visibility";

export type MaterialsQuery = Record<string, string | undefined>;
export type MaterialsSearchParams = Record<string, string | string[] | undefined>;
/** Repeated URL values can be displayed for recovery but never admitted as a query. */
export function materialsQueryFromSearchParams(raw: MaterialsSearchParams): { query: MaterialsQuery; errors: string[] } {
  const repeated = Object.values(raw).some(Array.isArray);
  return {
    query: Object.fromEntries(Object.entries(raw).map(([key, value]) => [key, Array.isArray(value) ? value[0] : value])),
    errors: repeated ? ["Each material filter must have one value. Remove repeated query parameters or clear filters."] : [],
  };
}
export const MATERIALS_PAGE_SIZES = [25, 50, 100, 200];
const SORTS = ["tc_max", "tc_ambient", "arxiv_year", "total_papers"];
const ORIGINS = ["Observed", "Computed", "Inferred", "AI-Proposed", "Unknown"];
const TRI = (value?: string) => value === "true" ? true : value === "false" ? false : undefined;
// Python str.strip whitespace; U+FEFF remains literal formula text.
const stripFormulaWhitespace = (raw: string) => raw.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, "");
const formulaText = (raw?: string) => raw === undefined ? undefined : stripFormulaWhitespace(raw.normalize("NFKC")) || undefined;
const formulaControls = /[\u0000-\u001f\u007f-\u009f]/;
const nonnegative = (raw?: string) => {
  if (!raw?.trim()) return undefined;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : undefined;
};
export function materialsPageSize(raw?: string): number {
  const value = Number(raw);
  return MATERIALS_PAGE_SIZES.includes(value) ? value : 50;
}
export function materialsPageIndex(raw?: string): number {
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : 0;
}
/** Invalid scientific filters must not silently broaden a shared query. */
export function materialsQueryErrors(query: MaterialsQuery): string[] {
  const errors: string[] = [];
  if (query.q !== undefined) {
    const normalized = query.q.normalize("NFKC");
    if (Array.from(query.q).length > 200 || Array.from(normalized).length > 200 || formulaControls.test(query.q) || formulaControls.test(normalized)) errors.push("Formula text must contain at most 200 characters and no control characters.");
  }
  for (const [key, label] of [["tc_min", "Tc minimum"], ["pressure_min", "Pressure minimum"], ["pressure_max", "Pressure maximum"], ["min_papers", "Minimum source links"]]) {
    if (!query[key]) continue;
    const value = nonnegative(query[key]);
    if (value === undefined || (key === "min_papers" && (!Number.isInteger(value) || value < 1))) errors.push(`${label} must be ${key === "min_papers" ? "a positive integer" : "a finite, nonnegative number"}.`);
  }
  if (query.knowledge_origin && !ORIGINS.includes(query.knowledge_origin)) errors.push("Choose a supported result origin.");
  if (query.min_tier && !["T1", "T2", "T3"].includes(query.min_tier)) errors.push("Choose a supported source tier.");
  if (query.source_role && !["primary", "cited"].includes(query.source_role)) errors.push("Choose a supported source role.");
  for (const key of ["ambient_sc", "is_unconventional", "has_competing_order", "experimental_only", "only_aps", "include_skeletons", "include_unknown_pressure", "parents_only"]) if (query[key] && !["true", "false"].includes(query[key]!)) errors.push(`Invalid ${key.replaceAll("_", " ")} filter.`);
  const lower = nonnegative(query.pressure_min); const upper = nonnegative(query.pressure_max);
  if (lower !== undefined && upper !== undefined && lower > upper) errors.push("Pressure minimum must not exceed pressure maximum.");
  return errors;
}
export function materialsParams(query: MaterialsQuery): MaterialListParams {
  const origin = ORIGINS.includes(query.knowledge_origin ?? "") ? query.knowledge_origin : undefined;
  const tier = ["T1", "T2", "T3"].includes(query.min_tier ?? "") ? query.min_tier as MaterialListParams["min_tier"] : undefined;
  const minPapers = nonnegative(query.min_papers);
  return {
    q: formulaText(query.q),
    family: query.family || undefined, tc_min: nonnegative(query.tc_min), pressure_max: nonnegative(query.pressure_max),
    pressure_min: nonnegative(query.pressure_min), include_unknown_pressure: query.include_unknown_pressure === "true",
    knowledge_origin: origin, source_role: query.source_role === "primary" || query.source_role === "cited" ? query.source_role : undefined,
    experimental_only: query.experimental_only === "true" || origin === "Observed",
    ambient_sc: TRI(query.ambient_sc), is_unconventional: TRI(query.is_unconventional), has_competing_order: TRI(query.has_competing_order),
    pairing_symmetry: query.pairing_symmetry || undefined, structure_phase: query.structure_phase || undefined,
    min_tier: tier, min_papers: minPapers !== undefined && Number.isInteger(minPapers) && minPapers >= 1 ? minPapers : undefined,
    sort: SORTS.includes(query.sort ?? "") ? query.sort as MaterialListParams["sort"] : "tc_max",
    limit: materialsPageSize(query.per_page), offset: materialsPageIndex(query.page) * materialsPageSize(query.per_page),
    include_skeletons: query.include_skeletons === "true", only_aps: query.only_aps === "true", parents_only: query.parents_only === "true",
  };
}

export const MATERIALS_ADVANCED_KEYS = ["pairing_symmetry", "is_unconventional", "has_competing_order", "ambient_sc", "min_tier", "min_papers", "only_aps", "include_skeletons", "structure_phase", "pressure_min", "source_role", "include_unknown_pressure", "parents_only"];
const FILTER_LABELS: Record<string, string> = {
  q: "Formula",
  family: "Family", tc_min: "Tc ≥", pressure_max: "Pressure ≤", pressure_min: "Pressure ≥", knowledge_origin: "Origin", experimental_only: "Observed only",
  pairing_symmetry: "Pairing", is_unconventional: "Unconventional", has_competing_order: "Competing order", ambient_sc: "Ambient result",
  min_tier: "Source tier", min_papers: "Source links ≥", only_aps: "APS only", include_skeletons: "Library-only entries", structure_phase: "Saved phase (unavailable)",
  source_role: "Source role", include_unknown_pressure: "Unknown pressure included", parents_only: "Parent materials only",
};
export function materialFilterChips(query: MaterialsQuery): { key: string; label: string }[] {
  return Object.entries(FILTER_LABELS).flatMap(([key, label]) => {
    const value = key === "q" && query[key] !== undefined ? stripFormulaWhitespace(query[key]!) : query[key];
    if (!value || (["experimental_only", "only_aps", "include_skeletons", "include_unknown_pressure", "parents_only"].includes(key) && value !== "true")) return [];
    if (key === "experimental_only" && query.knowledge_origin === "Observed") return [];
    const unit = key === "tc_min" ? " K" : key.startsWith("pressure_") ? " GPa" : "";
    const text = key === "q" ? value : value === "true" ? (key === "ambient_sc" ? "Explicit ambient" : "Yes") : value === "false" ? "Qualified false" : value;
    return [{ key, label: `${label}: ${text}${unit}` }];
  });
}
export function materialsHref(query: MaterialsQuery, removeKeys: string[] = []): string {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value && key !== "page" && !removeKeys.includes(key)) parameters.set(key, value);
  return `/materials${parameters.size ? `?${parameters}` : ""}`;
}

export interface MaterialsTcDisplay { item: PropertyEvidenceItem | null; matched: MatchingScientificResult | null; usesMatch: boolean; matchCount: number }
/** Matching quantity candidates can be intervals without becoming a catalogue point selection. */
function displayableMatchingTc(item: PropertyEvidenceItem | null | undefined): item is PropertyEvidenceItem {
  const blocked = ["outcome_does_not_support_positive_tc", "nonpositive_tc_not_positive_headline", "result_origin_not_supported", "ambient_pressure_not_explicit", "anomaly_review_required"];
  return eligibleAtomicItem(item, "tc_max") && !item.warnings?.some(warning => blocked.includes(warning));
}
export function materialTcQuantityKind(item: PropertyEvidenceItem): string | null {
  const quantity = objectValue(item.quantity);
  if (quantity.relation === "interval") return "Reported interval";
  if (quantity.relation === "ge" || quantity.relation === "gt") return "Reported lower bound";
  if (quantity.relation === "le" || quantity.relation === "lt") return "Reported upper bound";
  return typeof quantity.uncertainty === "number" ? "Uncertainty reported" : null;
}
/** Pick a public-eligible atomic Tc from exactly one result. A filter lower bound is never promoted to a point value. */
export function materialRowTc(material: MaterialSummary, resultFiltersActive = false): MaterialsTcDisplay {
  const selected = selectedProperty(material.property_evidence, "tc_max");
  const matches = material.matching_results?.filter(result => !visibilityIsRestricted(result.visibility)) ?? [];
  if (!resultFiltersActive) return { item: selected, matched: null, usesMatch: false, matchCount: 0 };
  const candidates = hasPropertyContract(material.property_evidence)
    ? Object.values(material.property_evidence!.properties).flatMap(entry => [entry.selected, ...entry.evidence]).filter((item): item is PropertyEvidenceItem => !!item)
    : [];
  for (const match of matches) {
    const item = objectValue(match).tc_evidence as PropertyEvidenceItem | undefined;
    const atomic = item?.result_id === match.result_id && displayableMatchingTc(item) ? item
      : candidates.find(candidate => candidate.result_id === match.result_id && displayableMatchingTc(candidate)) ?? null;
    if (atomic) return { item: atomic, matched: match, usesMatch: selected?.result_id !== atomic.result_id, matchCount: matches.length };
  }
  return { item: null, matched: matches[0] ?? null, usesMatch: matches.length > 0, matchCount: matches.length };
}
export function materialResultFiltersActive(query: MaterialsQuery): boolean {
  return !!(query.family || query.tc_min || query.pressure_max || query.pressure_min || query.knowledge_origin || query.experimental_only === "true" || query.ambient_sc === "true" || query.min_tier || query.only_aps === "true" || query.source_role);
}


/** Display known criterion codes as readable labels; the unchanged token remains in provenance. */
export function materialTcCriterion(raw: string | null): string | null {
  if (!raw) return null;
  const labels: Record<string, string> = {
    zero_resistance: "Zero resistance", zero_resistivity: "Zero resistivity", resistance_zero: "Zero resistance",
    onset: "Onset", resistive_onset: "Resistive onset", resistance_onset: "Resistive onset",
    midpoint: "Midpoint", resistive_midpoint: "Resistive midpoint", transition_midpoint: "Transition midpoint",
    offset: "Offset", resistive_offset: "Resistive offset", magnetic_onset: "Magnetic onset", diamagnetic_onset: "Diamagnetic onset",
    susceptibility_onset: "Susceptibility onset", heat_capacity: "Heat capacity", specific_heat: "Specific heat",
  };
  return labels[raw.trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_")] ?? raw;
}
