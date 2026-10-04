import snapshot from "@/public/research-pilots/materials-native-paper-context-2026-10-04.json";

export type NativePaperContextBatch = typeof snapshot;
export type NativePaperContext = NativePaperContextBatch["contexts"][number];

export const nativePaperContextDownloadPath = (process.env.NEXT_PUBLIC_BASE_PATH || "") + "/research-pilots/materials-native-paper-context-2026-10-04.json";
export const nativePaperContextSnapshotSha256 = "6c8b6b57c8a0e66a916ba2abf8bcafe9b849f56ef9a6ff0e4b4a8f0b4c1b4404";

const isRow = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);

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

/** A finite paper reading, with no material-property, sample or result promotion. */
export function loadNativePaperContexts(value: unknown = snapshot): NativePaperContextBatch | null {
  if (!isRow(value) || !matchesSnapshot(value, snapshot)) return null;
  const batch = value as NativePaperContextBatch;
  if (batch.version !== "materials-native-paper-context/1.0.0"
    || batch.status !== "source_qualified_reading"
    || batch.counts_are_independent_experiments !== false
    || batch.canonical_field_updates !== 0
    || Object.values(batch.authority).some(flag => flag !== false && flag !== 0)
    || new Set(batch.contexts.map(context => context.id)).size !== batch.contexts.length
    || batch.sources.some(source => !hash(source.pdf_sha256) || !hash(source.derived_text_sha256))
    || batch.contexts.some(context => context.selected_result_association !== "unestablished"
      || !batch.sources.some(source => source.id === context.source_id)
      || context.additional_locator_ids.some(id => !batch.locators.some(locator => locator.id === id && locator.source_id === context.source_id))
      || context.rows.some(row => row.kind !== "source_summary" || row.normalized_value !== null
        || row.locator_ids.some(id => !batch.locators.some(locator => locator.id === id && locator.source_id === context.source_id))))
    || batch.locators.some(locator => !hash(locator.window_sha256)
      || !Number.isSafeInteger(locator.char_start) || !Number.isSafeInteger(locator.char_end)
      || locator.char_start < 0 || locator.char_end <= locator.char_start
      || locator.end_exclusive !== true || !locator.pages_one_based.length
      || locator.pages_one_based.some(page => !Number.isSafeInteger(page) || page < 1))) return null;
  return JSON.parse(JSON.stringify(batch)) as NativePaperContextBatch;
}

/** Source links are restricted to the captured finite source editions. */
export function nativePaperContextSourceHref(sourceId: string, page?: number): string | null {
  const source = snapshot.sources.find(source => source.id === sourceId);
  if (!source) return null;
  const url = new URL(source.source_url);
  if (url.protocol !== "https:" || url.hostname !== "arxiv.org" || url.username || url.password || url.port || url.search) return null;
  if (page !== undefined) {
    if (!Number.isSafeInteger(page) || page < 1 || page > source.pdf_pages) return null;
    url.hash = "page=" + page;
  }
  return url.href;
}
