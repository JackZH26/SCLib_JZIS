import type { MaterialSemanticEvidence, MaterialSemanticField, MaterialSemanticProperty, MaterialSemanticStatus, MaterialSemantics } from "@/lib/api";
import { objectValue } from "@/lib/property-evidence";

export const MATERIAL_SEMANTICS_VERSION = "material-semantics/1.0.0";
export const MATERIAL_SEMANTIC_FIELDS: MaterialSemanticField[] = ["pairing_symmetry", "is_unconventional", "has_competing_order"];
export const MATERIAL_SEMANTIC_LABELS: Record<MaterialSemanticField, string> = { pairing_symmetry: "Pairing symmetry", is_unconventional: "Unconventional classification", has_competing_order: "Competing-order report" };
const STATUSES: MaterialSemanticStatus[] = ["reported", "unknown", "not_reported", "not_extracted", "not_computed", "failed", "conflicted", "not_applicable"];
const MISSING_TEXT = new Set(["", "unknown", "not_reported", "not reported", "not_extracted", "not extracted", "not_computed", "not computed", "failed", "conflicted", "not_applicable", "not applicable", "none", "null", "n/a"]);
function priorBasis(value: unknown): boolean { return /prior|family_default|legacy_family_heuristic/i.test(String(value)); }

export function knownMaterialSemantics(value: unknown): MaterialSemantics | null {
  const raw = objectValue(value);
  return raw.version === MATERIAL_SEMANTICS_VERSION && raw.scientific_acceptance === false && Object.keys(objectValue(raw.properties)).length > 0
    ? raw as unknown as MaterialSemantics : null;
}

export function semanticCount(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

export function semanticText(value: unknown, limit = 512): string | null {
  return typeof value === "string" && value.length <= limit && value.trim() ? value : null;
}

function sourceBacked(evidence: Record<string, unknown>): boolean {
  return !!semanticText(evidence.paper_id, 200) || (Array.isArray(evidence.bibliographic_identifiers) && evidence.bibliographic_identifiers.some(identifier => {
    const source = objectValue(identifier);
    return ["paper_id", "doi", "arxiv_id"].includes(String(source.kind)) && !!semanticText(source.value, 200);
  }));
}

function evidenceSourceEligible(item: Record<string, unknown>): boolean {
  return item.eligible_for_summary === true && !!semanticText(item.result_id, 200) && sourceBacked(item) &&
    !["retracted", "withdrawn", "corrected", "disputed", "quarantined", "pending"].includes(String(item.source_status).trim().toLowerCase()) &&
    String(item.classification_status).trim().toLowerCase() !== "conflicted" && String(item.source_role).trim().toLowerCase() !== "conflicted" &&
    !!semanticText(item.basis, 160) && !priorBasis(item.basis);
}

export function negativeEvidenceQualified(evidence: unknown): boolean {
  const item = objectValue(evidence);
  const conditions = objectValue(item.detection_conditions);
  const numericKeys = ["temperature_min_k", "temperature_max_k", "magnetic_field_t", "pressure_gpa"];
  const textKeys = ["description", "detection_limit", "protocol_id"];
  const presentKeys = [...numericKeys, ...textKeys].filter(key => conditions[key] != null);
  const hasCondition = presentKeys.length > 0 && presentKeys.every(key => numericKeys.includes(key)
    ? typeof conditions[key] === "number" && Number.isFinite(conditions[key])
    : !!semanticText(conditions[key], 240) && !MISSING_TEXT.has(String(conditions[key]).trim().toLowerCase()));
  const lower = conditions.temperature_min_k;
  const upper = conditions.temperature_max_k;
  if ((typeof lower === "number" && lower < 0) || (typeof upper === "number" && upper < 0) || (typeof lower === "number" && typeof upper === "number" && lower > upper)) return false;
  return item.status === "reported" && item.value === false && item.negative_qualified === true && evidenceSourceEligible(item) && !!semanticText(item.method, 160) && !MISSING_TEXT.has(String(item.method).trim().toLowerCase()) && hasCondition;
}

function evidenceMatches(evidence: unknown, value: unknown): boolean {
  const item = objectValue(evidence);
  if (item.status !== "reported" || item.value !== value || !evidenceSourceEligible(item)) return false;
  if (value === false && !negativeEvidenceQualified(evidence)) return false;
  return true;
}

export function materialSemanticProperty(envelope: unknown, field: MaterialSemanticField): MaterialSemanticProperty | null {
  const known = knownMaterialSemantics(envelope);
  if (!known) return null;
  const property = objectValue(known.properties[field]);
  if (!STATUSES.includes(property.status as MaterialSemanticStatus) || !Array.isArray(property.evidence) || !semanticText(property.basis)) return null;
  if (property.status === "reported") {
    const validType = field === "pairing_symmetry" ? !!semanticText(property.value, 160) && !MISSING_TEXT.has(String(property.value).trim().toLowerCase()) : typeof property.value === "boolean";
    if (objectValue(known.support).assessment_complete !== true || !validType || priorBasis(property.basis) || !property.evidence.some(evidence => evidenceMatches(evidence, property.value))) return null;
  } else if (property.value !== null) return null;
  if (property.status === "not_applicable" && (objectValue(known.support).assessment_complete !== true || !property.evidence.some(evidence => {
    const item = objectValue(evidence);
    return item.status === "not_applicable" && item.value === null && evidenceSourceEligible(item) && !!semanticText(item.status_reason);
  }))) return null;
  return property as unknown as MaterialSemanticProperty;
}

export function materialSemanticValue(envelope: unknown, field: MaterialSemanticField): string {
  const property = materialSemanticProperty(envelope, field);
  if (!property) return "Unknown";
  if (property.status === "reported") return property.value === true ? "Reported true" : property.value === false ? "Reported false (scoped)" : String(property.value);
  const labels: Record<Exclude<MaterialSemanticStatus, "reported">, string> = {
    unknown: "Unknown", not_reported: "Not reported", not_extracted: "Not extracted", not_computed: "Not computed", failed: "Assessment failed", conflicted: "Conflicting reports", not_applicable: "Not applicable",
  };
  return labels[property.status];
}

export function semanticEvidence(envelope: unknown, field: MaterialSemanticField): MaterialSemanticEvidence[] {
  const known = knownMaterialSemantics(envelope);
  const evidence = objectValue(known?.properties[field]).evidence;
  // Keep retained negative/unqualified evidence inspectable, without promoting it.
  return Array.isArray(evidence) ? evidence.filter(item => item && typeof item === "object" && !Array.isArray(item)) as MaterialSemanticEvidence[] : [];
}

export function materialSourceCount(envelope: unknown): number | null {
  return semanticCount(objectValue(knownMaterialSemantics(envelope)?.support).bibliographic_identifier_count);
}

export function materialSourceCountLabel(envelope: unknown, legacyCount?: number): string {
  const count = materialSourceCount(envelope);
  if (count !== null) return `${count.toLocaleString("en-US")} IDs`;
  const legacy = semanticCount(legacyCount);
  return legacy === null ? "Unknown" : `${legacy.toLocaleString("en-US")} legacy links`;
}
