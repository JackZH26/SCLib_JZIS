import snapshot from "@/public/research-pilots/materials-study-context-2026-10-04.json";

export type StudyContextBatch = typeof snapshot;
export type StudyContextEntry = StudyContextBatch["entries"][number];
export type StudyContextField = StudyContextEntry["fields"][number];
export type StudyContextWindow = StudyContextBatch["source_windows"][keyof StudyContextBatch["source_windows"]];
export type StudyContextSource = StudyContextBatch["sources"][number];

export const studyContextDownloadPath = (process.env.NEXT_PUBLIC_BASE_PATH || "") + "/research-pilots/materials-study-context-2026-10-04.json";
export const studyContextSnapshotSha256 = "75f628dfd479b1d0512caa7ccbc81202ce4b2e4136cbf093e86e2f7fa0607481";

const isRow = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const unsignedInteger = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const sourceUrls = new Set([
  "https://arxiv.org/pdf/1501.06203",
  "https://arxiv.org/pdf/1603.02892",
  "https://arxiv.org/html/0912.2752v2",
]);
const contextIds = new Set([
  "study-context:bi:transport",
  "study-context:bi:raman",
  "study-context:mo:table-I-column-2",
  "study-context:mo:table-I-column-3",
  "study-context:pt:xrd-correspondence",
  "study-context:pt:calorimetry-attribution",
]);

function matchesSnapshot(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 20) return false;
  if (expected === null || typeof expected !== "object") return value === expected
    && (typeof value !== "number" || Number.isFinite(value)) && (typeof value !== "string" || value.length <= 2048);
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length && value.length <= 64
    && value.every((entry, index) => matchesSnapshot(entry, expected[index], depth + 1));
  if (!isRow(value) || !isRow(expected)) return false;
  const keys = Object.keys(expected);
  return keys.length <= 64 && Object.keys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key) && matchesSnapshot(value[key], expected[key], depth + 1));
}

/** Only the finite inspected source context is accepted; matching grants no result or sample association. */
export function loadStudyContextBatch(value: unknown = snapshot): StudyContextBatch | null {
  if (!isRow(value) || !matchesSnapshot(value, snapshot)) return null;
  const data = value as StudyContextBatch;
  if (data.version !== "materials-study-context/1.0.0" || data.prepared_on !== "2026-10-04"
    || data.status !== "independent_source_context_pending" || data.source_case_count !== 3
    || data.source_scope_count !== 6 || data.field_projection_count !== 19
    || data.counts_are_independent_experiments !== false || data.sources.length !== 3
    || data.entries.length !== 6 || data.authority.selected_result_association !== "unestablished"
    || Object.entries(data.authority).some(([key, flag]) => key !== "selected_result_association" && flag !== false && flag !== 0)
    || data.sources.some(source => !studyContextSourceHref(source.source_url)
      || source.current_publication_status !== "not_checked" || source.publisher_revision_equivalence_verified !== false)
    || new Set(data.entries.map(entry => entry.id)).size !== 6) return null;
  const fields = data.entries.flatMap<StudyContextField>(entry => entry.fields);
  if (fields.length !== 19 || new Set(fields.map(field => field.field)).size !== 19
    || data.entries.some(entry => !contextIds.has(entry.id) || entry.status !== "pending_source_context"
      || entry.selected_result_association !== "unestablished")
    || fields.some(field => {
      const locator = field.locator;
      return field.normalized_value !== null || !hash(locator.literal_sha256)
        || !Object.hasOwn(data.source_windows, locator.source_window_id) || locator.end_exclusive !== true
        || !unsignedInteger(locator.char_start) || !unsignedInteger(locator.char_end)
        || locator.char_end <= locator.char_start || Array.from(field.raw_value).length !== locator.char_end - locator.char_start;
    })) return null;
  return JSON.parse(JSON.stringify(data)) as StudyContextBatch;
}

/** No arbitrary hosts, queries, credentials or caller-provided source URLs. */
export function studyContextSourceHref(value: unknown): string | null {
  if (typeof value !== "string" || !sourceUrls.has(value)) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}
