import snapshot from "@/public/research-pilots/discovery-ab2h24-source-table-2026-10-04.json";

export type DiscoverySourceTable = typeof snapshot;
export type DiscoverySourceRow = DiscoverySourceTable["rows"][number];
export type DiscoverySourceLocator = DiscoverySourceTable["locators"][number];

export const DISCOVERY_SOURCE_TABLE_VERSION = "discovery-ab2h24-source-table/1.0.0";
export const discoverySourceTableSha256 = "e63ab6df2fd73daf92cb75f0c7efda804cfda595a302f63e8b99fb55eaa9f362";
export const discoverySourceTableFilename = "discovery-ab2h24-source-table-2026-10-04.json";

export function discoverySourceTableDownloadPath() {
  return `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/${discoverySourceTableFilename}`;
}

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);

function matchesSnapshot(value: unknown, expected: unknown, depth = 0): boolean {
  if (depth > 20) return false;
  if (expected === null || typeof expected !== "object") return value === expected
    && (typeof value !== "number" || Number.isFinite(value)) && (typeof value !== "string" || value.length <= 4096);
  if (Array.isArray(expected)) return Array.isArray(value) && value.length === expected.length && value.length <= 64
    && value.every((entry, index) => matchesSnapshot(entry, expected[index], depth + 1));
  if (!object(value) || !object(expected)) return false;
  const keys = Object.keys(expected);
  return keys.length <= 64 && Object.keys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key) && matchesSnapshot(value[key], expected[key], depth + 1));
}

function validLocator(locator: DiscoverySourceLocator) {
  return Number.isSafeInteger(locator.pdf_page_one_based) && locator.pdf_page_one_based >= 1 && locator.pdf_page_one_based <= 7
    && Number.isSafeInteger(locator.char_start) && Number.isSafeInteger(locator.char_end)
    && locator.char_start >= 0 && locator.char_end > locator.char_start && locator.end_exclusive === true && hash(locator.window_sha256);
}

/** Finite published table metadata, independent of catalogue and private design rows. */
export function loadDiscoverySourceTable(value: unknown = snapshot): DiscoverySourceTable | null {
  if (!matchesSnapshot(value, snapshot)) return null;
  const table = value as DiscoverySourceTable;
  if (table.version !== DISCOVERY_SOURCE_TABLE_VERSION || table.status !== "source_qualified_comparison"
    || table.source_row_count !== 21 || table.rows.length !== 21 || table.counts_are_independent_experiments !== false
    || table.authority.canonical_field_updates !== 0 || Object.entries(table.authority).some(([key, flag]) => key !== "canonical_field_updates" && flag !== false)
    || !hash(table.source.pdf_sha256) || !hash(table.source.derived_text_sha256)
    || table.common_context.pressure.value !== 300 || table.common_context.pressure.unit !== "GPa"
    || table.common_context.mu_star.value !== 0.1 || table.common_context.mu_star.role !== "assumed_model_parameter"
    || table.scope.pressure_response_series_established !== false || table.scope.omega_log_unit_established !== false
    || table.scope.source_row_catalogue_association !== "unestablished" || table.scope.raw_fulltext_or_PDF_included !== false
    || new Set(table.rows.map(row => row.id)).size !== 21 || new Set(table.rows.map(row => row.formula)).size !== 21
    || table.locators.some(locator => !validLocator(locator))) return null;
  const wholeTable = table.locators.find(locator => locator.id === "table-I");
  if (!wholeTable || table.rows.some((row, index) => row.source_data_row !== index + 1
    || row.formula !== `${row.a_element}${row.b_element}2H24`
    || !validLocator(row.row_locator) || row.row_locator.pdf_page_one_based !== 3
    || row.row_locator.char_start < wholeTable.char_start || row.row_locator.char_end > wholeTable.char_end
    || !Number.isFinite(row.electron_phonon_lambda.value) || row.electron_phonon_lambda.value < 0
    || row.electron_phonon_lambda.value !== Number(row.electron_phonon_lambda.raw_value) || row.electron_phonon_lambda.unit !== "1"
    || !Number.isFinite(row.computed_tc.value) || row.computed_tc.value < 0 || row.computed_tc.value !== Number(row.computed_tc.raw_value)
    || row.computed_tc.unit !== "K" || row.computed_tc.uncertainty !== null
    || row.omega_log.value !== null || row.omega_log.unit !== null || row.omega_log.unit_status !== "not_printed_in_table"
    || Object.values(row.field_locators).some(field => !Number.isSafeInteger(field.char_start) || !Number.isSafeInteger(field.char_end)
      || field.char_start < row.row_locator.char_start || field.char_end > row.row_locator.char_end
      || field.char_end <= field.char_start || !hash(field.token_sha256)))) return null;
  return JSON.parse(JSON.stringify(table)) as DiscoverySourceTable;
}

/** The finite publisher URL is a reading locator, not a promise of immutable/current bytes. */
export function discoverySourcePaperHref(page?: number): string | null {
  const url = new URL(snapshot.source.source_url);
  if (url.href !== "https://journals.aps.org/prresearch/pdf/10.1103/7lg7-l3x8") return null;
  if (page !== undefined) {
    if (!Number.isSafeInteger(page) || page < 1 || page > snapshot.source.pdf_pages) return null;
    url.hash = `page=${page}`;
  }
  return url.href;
}

/** Filtering never changes source order or turns a source row into a material association. */
export function filterDiscoverySourceRows(table: DiscoverySourceTable, aElement = "", bElement = "") {
  return table.rows.filter(row => (!aElement || row.a_element === aElement) && (!bElement || row.b_element === bElement));
}

/** Source CSV carries the shared assumptions and unresolved unit on every row. */
export function discoverySourceTableCsv(value: unknown = snapshot): string {
  const table = loadDiscoverySourceTable(value);
  if (!table) throw new Error("The captured source table is unavailable.");
  const headers = ["source_table_version", "source_data_row", "source_row_id", "compound", "a_element", "b_element", "lambda_raw", "lambda_unit",
    "omega_log_raw", "omega_log_unit", "omega_log_unit_status", "computed_tc_raw", "computed_tc_unit", "pressure_raw", "pressure_unit",
    "tc_solver", "mu_star_raw", "mu_star_role", "knowledge_origin", "catalogue_association", "scientific_acceptance", "ml_training_approved",
    "new_calculation_executed", "doi", "source_pdf_sha256", "source_text_sha256", "pdf_page", "row_char_start", "row_char_end", "row_window_sha256"];
  const rows = table.rows.map(row => [table.version, row.source_data_row, row.id, row.formula, row.a_element, row.b_element,
    row.electron_phonon_lambda.raw_value, row.electron_phonon_lambda.unit, row.omega_log.raw_value, "", row.omega_log.unit_status,
    row.computed_tc.raw_value, row.computed_tc.unit, table.common_context.pressure.raw_value, table.common_context.pressure.unit,
    table.common_context.tc_solver.table_label, table.common_context.mu_star.raw_value, table.common_context.mu_star.role,
    table.common_context.knowledge_origin, table.scope.source_row_catalogue_association, table.authority.scientific_acceptance,
    table.authority.ml_training_approved, table.authority.new_calculation_executed, table.source.doi, table.source.pdf_sha256,
    table.source.derived_text_sha256, row.row_locator.pdf_page_one_based, row.row_locator.char_start, row.row_locator.char_end, row.row_locator.window_sha256]);
  const cell = (item: string | number | boolean) => `"${String(item).replaceAll('"', '""')}"`;
  return [headers, ...rows].map(row => row.map(cell).join(",")).join("\r\n") + "\r\n";
}
