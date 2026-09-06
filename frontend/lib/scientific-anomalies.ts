/** Display the server policy; never recalculate scientific thresholds in the UI. */
import { objectValue } from "@/lib/property-evidence";

export const ANOMALY_POLICY_VERSION = "anomaly-review/1.0.0";
export const RAW_ARCHIVE_DISPLAY_LIMIT = 100;

export function hasAnomalyPolicy(value: unknown): boolean {
  const review = objectValue(value);
  return review.version === ANOMALY_POLICY_VERSION && review.raw_preserved === true && review.scientific_acceptance === false;
}

export function anomalyStatus(value: unknown): string {
  if (!hasAnomalyPolicy(value)) return "Review status unavailable";
  const review = objectValue(value);
  if (review.status === "format_invalid") return "Format or parser review required";
  if (review.status === "review_required") return "Anomaly review required";
  if (review.status === "no_findings") return "No findings under this policy";
  return "Review status unavailable";
}

export function hasMaterialAnomalyReview(value: unknown): boolean {
  if (!hasAnomalyPolicy(value)) return false;
  const review = objectValue(value);
  const counts = objectValue(review.counts);
  if (!["total_records", "no_findings", "review_required", "format_invalid"].every(key => typeof counts[key] === "number" && Number.isSafeInteger(counts[key]) && (counts[key] as number) >= 0)) return false;
  return counts.total_records === review.total_records &&
    (counts.no_findings as number) + (counts.review_required as number) + (counts.format_invalid as number) === counts.total_records &&
    review.needs_review === ((counts.review_required as number) > 0 || (counts.format_invalid as number) > 0);
}

export function hasRawArchive(value: unknown): boolean {
  const archive = objectValue(value);
  return archive.version === ANOMALY_POLICY_VERSION && archive.scope === "material_retained_records" &&
    archive.raw_field_policy === "scientific_allowlist_not_full_source" && Array.isArray(archive.records) &&
    archive.records.every(value => { const record = objectValue(value); return typeof record.result_id === "string" && record.result_id.trim() && Number.isSafeInteger(record.record_index) && (record.record_index as number) >= 0 && record.raw != null && typeof record.raw === "object" && !Array.isArray(record.raw); });
}

export function archiveJson(value: unknown): string {
  // Text only: never interpret source content as HTML, a URL or UI instructions.
  try { return JSON.stringify(value, null, 2) ?? "Not reported"; } catch { return "Record could not be displayed"; }
}
