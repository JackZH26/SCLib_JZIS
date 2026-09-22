import type { EvidenceProvenance } from "@/lib/api";

const FIELDS = ["version", "chunk_kind", "evidence_revision_id", "evidence_record_sha256", "content_sha256", "parent_result_revision_id", "parent_result_sha256", "extraction_version", "rendering_version", "source_capture_id", "source_locator", "root_status", "permission_status", "currentness", "warning_codes", "support_eligible", "independent_evidence", "scientific_acceptance"];
const TEXT_LOCATORS = new Set(["section", "table", "figure", "equation", "xml_xpath", "section_path"]);
const INT_LOCATORS = new Set(["page", "page_start", "page_end", "row", "column", "char_start", "char_end", "span_start", "span_end"]);
const bounded = (value: unknown, length: number): value is string => typeof value === "string" && !!value.trim() && value.length <= length && !/[\u0000-\u001f]/.test(value);

/** Runtime data, including saved legacy history, is not trusted TypeScript. */
export function knownEvidenceProvenance(value: unknown): EvidenceProvenance | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as Record<string, unknown>;
  if (Object.keys(data).length !== FIELDS.length || FIELDS.some(key => !Object.hasOwn(data, key))) return null;
  if (data.version !== "rag-evidence/1.0.0" || typeof data.chunk_kind !== "string" || !["original_passage", "abstract", "derived_fact", "retained_legacy_snapshot", "legacy_unknown"].includes(data.chunk_kind)
    || data.root_status !== "unresolved" || typeof data.permission_status !== "string" || !["unresolved", "restricted"].includes(data.permission_status)
    || typeof data.currentness !== "string" || !["current", "stale", "unresolved"].includes(data.currentness)
    || data.support_eligible !== false || data.independent_evidence !== false || data.scientific_acceptance !== false) return null;
  for (const key of ["evidence_revision_id", "parent_result_revision_id", "source_capture_id"]) {
    const item = data[key];
    if (item !== null && (typeof item !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(item))) return null;
  }
  for (const key of ["content_sha256", "evidence_record_sha256", "parent_result_sha256"]) {
    const item = data[key];
    if (item === null && key !== "content_sha256") continue;
    if (typeof item !== "string" || !/^[0-9a-f]{64}$/.test(item)) return null;
  }
  for (const key of ["extraction_version", "rendering_version"]) if (data[key] !== null && !bounded(data[key], 160)) return null;
  const parentFields = ["parent_result_revision_id", "parent_result_sha256", "extraction_version"];
  if (data.chunk_kind === "legacy_unknown") {
    if (["evidence_revision_id", "evidence_record_sha256", "source_capture_id", "rendering_version", ...parentFields].some(key => data[key] !== null) || data.currentness === "current") return null;
  } else {
    if (data.evidence_revision_id === null || data.evidence_record_sha256 === null) return null;
    if (data.chunk_kind === "derived_fact" ? [...parentFields, "rendering_version"].some(key => data[key] === null) : parentFields.some(key => data[key] !== null)) return null;
  }
  const locator = data.source_locator;
  if (!locator || typeof locator !== "object" || Array.isArray(locator) || Object.keys(locator).length > TEXT_LOCATORS.size + INT_LOCATORS.size) return null;
  if (new TextEncoder().encode(JSON.stringify(locator)).length > 4096) return null;
  for (const [key, item] of Object.entries(locator)) {
    if (TEXT_LOCATORS.has(key) ? !bounded(item, 300) : !INT_LOCATORS.has(key) || !Number.isSafeInteger(item) || item < 0 || item > 1_000_000_000) return null;
  }
  const coordinates = locator as Record<string, number>;
  if (data.chunk_kind === "retained_legacy_snapshot" && (data.rendering_version !== "sclib-legacy-input-pack/1.0.0"
    || data.source_capture_id !== null || Object.keys(coordinates).sort().join(",") !== "char_end,char_start")) return null;
  for (const [lower, upper] of [["page_start", "page_end"], ["char_start", "char_end"], ["span_start", "span_end"]]) {
    if (Object.hasOwn(coordinates, lower) !== Object.hasOwn(coordinates, upper) || Object.hasOwn(coordinates, lower)
      && (coordinates[lower] > coordinates[upper] || lower !== "page_start" && coordinates[lower] === coordinates[upper])) return null;
  }
  if (!Array.isArray(data.warning_codes) || data.warning_codes.length > 12 || data.warning_codes.some(code => typeof code !== "string" || !/^[a-z][a-z0-9_]{0,79}$/.test(code))) return null;
  return data as unknown as EvidenceProvenance;
}
