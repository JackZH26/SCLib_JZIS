import snapshot from "@/public/research-pilots/materials-source-sample-tables-2026-10-04.json";

export type SourceSampleTables = typeof snapshot;
export type SourceSampleTable = SourceSampleTables["composition_table"] | SourceSampleTables["fit_parameter_table"];
export type SourceSampleCell = { raw_value: string | null; display_state: string; normalized_value: null };
export const sourceSampleTablesSha256 = "a20ebb3d98b1e460a942944fe24004d860ccb969b5c25d10c4b007f407f5d372";
export const sourceSampleTablesDownloadPath = (process.env.NEXT_PUBLIC_BASE_PATH || "") + "/research-pilots/materials-source-sample-tables-2026-10-04.json";

const isRow = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
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

/** A finite source table reference, with no selected-result or material-property overlay. */
export function loadSourceSampleTables(value: unknown = snapshot): SourceSampleTables | null {
  if (!isRow(value) || !matchesSnapshot(value, snapshot)) return null;
  const data = value as SourceSampleTables;
  if (data.version !== "materials-source-sample-tables/1.0.0" || data.status !== "source_qualified_reference"
    || data.authority.canonical_updates !== 0 || data.authority.scientific_acceptance !== false
    || data.authority.formal_human_review !== false || data.authority.ML_approval !== false
    || data.authority.material_sample_state_and_selected_result_association !== "unestablished"
    || !hash(data.source.pdf_sha256) || !hash(data.source.derived_text_sha256)
    || data.locators.some(locator => !hash(locator.window_sha256) || locator.page !== 4
      || !Number.isSafeInteger(locator.char_start) || !Number.isSafeInteger(locator.char_end)
      || locator.char_start < 0 || locator.char_end <= locator.char_start || locator.end_exclusive !== true)
    || [data.composition_table, data.fit_parameter_table].some(table => !data.locators.some(locator => locator.id === table.source_locator_id)
      || table.rows.some(row => Object.values(row.cells).some(cell => cell.normalized_value !== null
        || (cell.display_state === "source_blank" ? cell.raw_value !== null
          : cell.display_state === "source_dash" ? cell.raw_value !== "-" : typeof cell.raw_value !== "string"))))) return null;
  return JSON.parse(JSON.stringify(data)) as SourceSampleTables;
}

export function sourceSampleTableCell(row: SourceSampleTable["rows"][number], column: string): SourceSampleCell {
  return (row.cells as Record<string, SourceSampleCell>)[column];
}

/** Only the captured Table I page becomes a paper link. */
export function sourceSampleTableHref(page = 4): string | null {
  return page === 4 ? snapshot.source.source_url + "#page=4" : null;
}
