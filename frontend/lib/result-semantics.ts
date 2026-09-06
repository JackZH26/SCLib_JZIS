/** Display the API's versioned result classification; never infer it from T1,
 * paper genre, pressure or a legacy is_theoretical=false flag. */
const ORIGINS = new Set(["Observed", "Computed", "Inferred", "AI-Proposed", "Unknown"]);

export function resultOrigin(value: unknown): string {
  return typeof value === "string" && ORIGINS.has(value) ? value : "Unknown";
}

export function recordClassification(record: Record<string, unknown>) {
  const raw = record.result_classification;
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const version = typeof value.classifier_version === "string" ? value.classifier_version : "unclassified";
  return {
    origin: version === "unclassified" ? "Unknown" : resultOrigin(value.knowledge_origin),
    status: value.classification_status === "conflicted" ? "conflicted" : value.classification_status === "resolved" ? "resolved" : "unknown",
    role: ["primary", "cited", "conflicted"].includes(String(value.source_role)) ? String(value.source_role) : "unknown",
    version,
  };
}

export function scientificNumber(value: number): string {
  return Number.isFinite(value)
    ? value.toLocaleString("en-US", { maximumSignificantDigits: 6, useGrouping: false })
    : "—";
}
