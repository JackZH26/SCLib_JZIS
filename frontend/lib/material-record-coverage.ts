/** Bounded record denominators. Candidate extractions never count as retained values. */
import type { MaterialRecordCoverage } from "./api";
import { expressionCanonical, expressionSha } from "./source-expressions";

type Row = Record<string, unknown>;
const HASH = /^[a-f0-9]{64}$/;
const LIMITATIONS = ["retained_value_presence_is_not_scientific_acceptance", "missing_retained_value_is_not_source_absence", "unchecked_records_have_no_field_or_applicability_assessment", "method_role_exclusions_do_not_assert_a_joint_sample_or_run"];
function closed(value: unknown, keys: string): value is Row {
  const names = keys.split(" ");
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
}
function count(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) >= 0; }
function text(value: unknown, limit: number): value is string { return typeof value === "string" && value.length > 0 && Array.from(value).length <= limit && !/[\u0000-\u001f\ud800-\udfff]/u.test(value); }
function field(value: unknown): value is string { return typeof value === "string" && /^[a-z][a-z0-9_]{0,79}$/.test(value); }
/** Allowlisted exact DTO only: no retained raw records or source text are exposed. */
export function projectRecordCoverage(value: unknown, materialId: string): MaterialRecordCoverage | null {
  if (!closed(value, "version material_id records_total records_inspected records_unchecked records_limit record_denominator records fields limitations scientific_acceptance database_changed ml_training_approved public_release coverage_sha256")
      || value.version !== "materials-record-field-coverage/1.0.0" || value.material_id !== materialId
      || !count(value.records_total) || !count(value.records_inspected) || !count(value.records_unchecked)
      || value.records_inspected + value.records_unchecked !== value.records_total
      || value.records_limit !== 32 || value.records_inspected > 32 || value.record_denominator !== "current_eligible_retained_records"
      || !["scientific_acceptance", "database_changed", "ml_training_approved", "public_release"].every(key => value[key] === false)
      || typeof value.coverage_sha256 !== "string" || !HASH.test(value.coverage_sha256)
      || !Array.isArray(value.limitations) || value.limitations.length !== LIMITATIONS.length || !value.limitations.every((item, index) => item === LIMITATIONS[index])
      || !Array.isArray(value.fields) || value.fields.length > 128 || !Array.isArray(value.records) || value.records.length !== value.records_inspected) return null;
  const names = new Set<string>();
  for (const item of value.fields) {
    if (!closed(item, "field counts applicability_unknown") || !field(item.field) || names.has(item.field)
        || !closed(item.counts, "present missing unchecked not_applicable") || !Object.values(item.counts).every(count)
        || Object.values(item.counts).reduce((a, b) => (a as number) + (b as number), 0) !== value.records_total
        || item.counts.unchecked !== value.records_unchecked || !count(item.applicability_unknown) || item.applicability_unknown > (item.counts.missing as number)) return null;
    names.add(item.field);
  }
  const offsets = new Set<number>();
  const tallies = new Map<string, { present: number; missing: number; not_applicable: number }>(Array.from(names, name => [name, { present: 0, missing: 0, not_applicable: 0 }]));
  for (const record of value.records) {
    if (!closed(record, "record_offset result_id record_sha256 paper_id knowledge_origin classification_status fields")
        || !count(record.record_offset) || record.record_offset >= value.records_total || offsets.has(record.record_offset)
        || !text(record.result_id, 200) || typeof record.record_sha256 !== "string" || !HASH.test(record.record_sha256)
        || !(record.paper_id === null || text(record.paper_id, 100)) || !text(record.knowledge_origin, 80) || !text(record.classification_status, 80)
        || !Array.isArray(record.fields) || record.fields.length !== names.size) return null;
    offsets.add(record.record_offset);
    const seen = new Set<string>();
    for (const item of record.fields) {
      if (!closed(item, "field status reason_codes") || !field(item.field) || !names.has(item.field) || seen.has(item.field)
          || !["present", "missing", "not_applicable"].includes(item.status as string) || !Array.isArray(item.reason_codes)
          || item.reason_codes.length > 16 || !item.reason_codes.every(field)) return null;
      if (item.status === "not_applicable" && (record.classification_status !== "resolved" ||
          !(item.field === "measurement_method" && record.knowledge_origin === "Computed" || item.field === "calculation_method" && record.knowledge_origin === "Observed"))) return null;
      seen.add(item.field);
      const counts = tallies.get(item.field)!;
      counts[item.status as keyof typeof counts]++;
    }
  }
  if (!value.fields.every(item => ["present", "missing", "not_applicable"].every(key => item.counts[key] === tallies.get(item.field)![key as "present" | "missing" | "not_applicable"]))) return null;
  return value as unknown as MaterialRecordCoverage;
}
export async function verifiedRecordCoverage(value: unknown, materialId: string): Promise<MaterialRecordCoverage | null> {
  const projected = projectRecordCoverage(value, materialId);
  if (!projected) return null;
  try {
    const { coverage_sha256, ...body } = projected;
    // Snapshot the canonical bytes before the asynchronous digest.
    const bytes = expressionCanonical(body);
    const snapshot = JSON.parse(bytes) as Omit<MaterialRecordCoverage, "coverage_sha256">;
    return await expressionSha(bytes) === coverage_sha256 ? { ...snapshot, coverage_sha256 } : null;
  } catch { return null; }
}
export function recordCoverageSummary(value: MaterialRecordCoverage) {
  const complete = value.fields.filter(row => row.counts.missing === 0 && row.counts.unchecked === 0 && row.counts.present > 0).length;
  const incomplete = value.fields.filter(row => row.counts.missing > 0 || row.counts.unchecked > 0).length;
  const notApplicable = value.records_total > 0 ? value.fields.filter(row => row.counts.not_applicable === value.records_total).length : 0;
  return { complete, incomplete, notApplicable };
}
