/** Atomic catalogue selections, never a join of legacy material scalars. */
import type { MaterialPropertyEvidence, PropertyEvidenceItem } from "@/lib/api";
import { resultOrigin, scientificNumber } from "@/lib/result-semantics";

export const PROPERTY_EVIDENCE_VERSION = "property-evidence/1.1.0";
export const PROPERTY_LABELS: Record<string, string> = {
  tc_max: "Tc max", tc_ambient: "Tc ambient", tc_max_experimental: "Tc · Observed-record selection",
  tc_max_theoretical: "Tc · Computed-record selection", pairing_symmetry: "Pairing symmetry",
  crystal_structure: "Crystal structure", space_group: "Space group", structure_phase: "Phase",
  lattice_params: "Lattice parameters", gap_structure: "Gap structure", hc2_tesla: "Hc2",
  lambda_eph: "λ_eph (electron–phonon coupling)", omega_log_k: "ω_log", rho_s_mev: "ρ_s (superfluid stiffness)",
  competing_order: "Competing order", t_cdw_k: "T_CDW", t_sdw_k: "T_SDW", t_afm_k: "T_AFM",
  rho_exponent: "ρ(T) exponent", pressure_type: "Pressure type", sample_form: "Sample form",
  substrate: "Substrate", doping_type: "Doping type", doping_level: "Doping level",
  formula_substrate: "Substrate formula", formula_overlayer: "Overlayer formula", layer_thickness_nm: "Layer thickness",
  ambient_sc: "Ambient SC", is_unconventional: "Unconventional", has_competing_order: "Competing order present",
};

export const STRUCTURE_FIELDS = ["crystal_structure", "space_group", "structure_phase", "lattice_params"];
export const SC_FIELDS = ["pairing_symmetry", "gap_structure", "hc2_tesla", "lambda_eph", "omega_log_k", "rho_s_mev"];
export const ORDER_FIELDS = ["competing_order", "t_cdw_k", "t_sdw_k", "t_afm_k", "rho_exponent"];
export const SAMPLE_FIELDS = ["sample_form", "substrate", "pressure_type", "doping_type", "doping_level", "formula_overlayer", "formula_substrate", "layer_thickness_nm"];

export function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
export function evidenceText(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number" && Number.isFinite(value)) return scientificNumber(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return null;
}
export function hasPropertyContract(envelope?: MaterialPropertyEvidence): boolean {
  return envelope?.version === PROPERTY_EVIDENCE_VERSION && envelope.not_joint_observation === true && envelope.anomaly_policy_version === "anomaly-review/1.0.0";
}
const identifier = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
export function validAtomicItem(item: PropertyEvidenceItem | null | undefined, field: string): item is PropertyEvidenceItem {
  if (!item || item.property !== field || !identifier(item.result_id) ||
      !["paper_id", "doi", "arxiv_id"].some(key => identifier(objectValue(item.source)[key]))) return false;
  if (typeof item.value === "number") {
    const q = objectValue(item.quantity);
    if (q.relation !== "exact" || q.value !== item.value) return false;
  }
  return propertyValue(item) !== "—";
}
export function selectedProperty(envelope: MaterialPropertyEvidence | undefined, field: string): PropertyEvidenceItem | null {
  if (!hasPropertyContract(envelope)) return null;
  const property = envelope?.properties?.[field];
  const item = property?.selected;
  return property?.status === "supported" && eligibleAtomicItem(item, field) ? item : null;
}

export function eligibleAtomicItem(item: PropertyEvidenceItem | null | undefined, field: string): item is PropertyEvidenceItem {
  return anomalyAllowsProperties(item, [field]) && validAtomicItem(item, field);
}

export function anomalyAllowsProperties(item: PropertyEvidenceItem | null | undefined, fields: string[]): boolean {
  const review = objectValue(item?.anomaly_review);
  const affected = review.review_required_properties;
  return review.version === "anomaly-review/1.0.0" && review.scientific_acceptance === false &&
    review.raw_preserved === true && review.result_id === item?.result_id && ["no_findings", "review_required", "format_invalid"].includes(String(review.status)) &&
    Array.isArray(affected) && affected.every(value => typeof value === "string") && !affected.includes("*") && fields.every(field => !affected.includes(field));
}

/** Canonical quantity metadata takes precedence; no rounding a bound into a point. */
export function propertyValue(item: PropertyEvidenceItem, includeUnit = true): string {
  const q = objectValue(item.quantity);
  const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
  const unitLabel = q.unit === "angstrom" ? "Å" : q.unit === "degree" ? "°" : q.unit;
  const unit = typeof unitLabel === "string" && unitLabel !== "1" && includeUnit ? ` ${unitLabel}` : "";
  if (item.property === "lattice_params") {
    const components = objectValue(q.components);
    if (q.status === "parsed" && q.relation === "group" && Object.keys(components).length) {
      const selectedKeys = Object.keys(objectValue(item.value));
      if (selectedKeys.some(key => !["a", "b", "c", "alpha", "beta", "gamma"].includes(key) || objectValue(components[key]).value !== objectValue(item.value)[key])) return "—";
      return ["a", "b", "c", "alpha", "beta", "gamma"].filter(key => selectedKeys.includes(key)).flatMap(key => {
        const component = objectValue(components[key]);
        const value = propertyValue({ ...item, property: `lattice_${key}`, quantity: component, value: component.value });
        return value === "—" ? [] : [`${key}=${value}`];
      }).join(" · ") || "—";
    }
    return "—";
  }
  if (Object.keys(q).length) {
    if (q.status !== "parsed" || !Array.isArray(q.errors) || q.errors.length !== 0) return "—";
    const prefix = q.approximate === true ? "≈ " : "";
    if (q.relation === "interval" && finite(q.lower) && finite(q.upper)) return `${prefix}${scientificNumber(q.lower)}–${scientificNumber(q.upper)}${unit}`;
    if ((q.relation === "lt" || q.relation === "le") && finite(q.upper)) return `${prefix}${q.relation === "lt" ? "<" : "≤"} ${scientificNumber(q.upper)}${unit}`;
    if ((q.relation === "gt" || q.relation === "ge") && finite(q.lower)) return `${prefix}${q.relation === "gt" ? ">" : "≥"} ${scientificNumber(q.lower)}${unit}`;
    if (q.relation === "exact" && finite(q.value)) return `${prefix}${scientificNumber(q.value)}${finite(q.uncertainty) ? ` ± ${scientificNumber(q.uncertainty)}` : ""}${unit}`;
    return "—";
  }
  return typeof item.value === "number" ? "—" : evidenceText(item.value) ?? "—";
}

export function propertyOrigin(item: PropertyEvidenceItem): string {
  return resultOrigin(objectValue(item.origin).knowledge_origin);
}
export function propertyStatus(envelope: MaterialPropertyEvidence | undefined, field: string): string {
  if (!hasPropertyContract(envelope)) return "Source unavailable";
  const status = envelope?.properties?.[field]?.status;
  if (envelope?.properties?.[field]?.warnings?.includes("anomaly_review_required")) return "Anomaly review required";
  return status === "pending" ? "Selection pending" : status === "not_reported" ? "Not reported" : "Source unavailable";
}

export function supportedPropertyDescription(envelope: MaterialPropertyEvidence | undefined, field: string): string | null {
  const item = selectedProperty(envelope, field);
  return item ? `${PROPERTY_LABELS[field] ?? field} ${propertyValue(item)} (record origin: ${propertyOrigin(item)}; catalogue selection)` : null;
}

export function propertyJsonLd(envelope: MaterialPropertyEvidence | undefined, field: string): Record<string, unknown> | null {
  const item = selectedProperty(envelope, field);
  if (!item) return null;
  const source = objectValue(item.source);
  const q = objectValue(item.quantity);
  return {
    "@type": "PropertyValue", name: `${PROPERTY_LABELS[field] ?? field} (record origin: ${propertyOrigin(item)}; catalogue selection)`,
    value: propertyValue(item, false), ...(typeof q.unit === "string" && q.unit !== "1" ? { unitText: q.unit } : {}),
    description: `Separate result ${item.result_id}; source ${evidenceText(source.paper_id) ?? "see property evidence"}. Not a joint observation. Origin classification belongs to the source record, not an independent classification of each property.`,
  };
}

export function sourceHref(source: Record<string, unknown>): string | null {
  const paper = evidenceText(source.paper_id);
  if (paper) return `/paper/${encodeURIComponent(paper)}`;
  const doi = evidenceText(source.doi);
  if (doi && /^10\.\d{4,9}\/\S+$/.test(doi)) return `https://doi.org/${encodeURIComponent(doi).replace(/%2F/gi, "/")}`;
  const arxiv = evidenceText(source.arxiv_id);
  return arxiv && /^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?$/.test(arxiv) ? `https://arxiv.org/abs/${arxiv}` : null;
}
