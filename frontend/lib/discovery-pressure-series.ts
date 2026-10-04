import snapshot from "@/public/research-pilots/discovery-lah10-pressure-series-2026-10-04.json";

export type DiscoveryPressureQuantity = "electron_phonon_lambda" | "omega_log" | "tc_mcmillan" | "tc_allen_dynes"
  | "tc_anisotropic_me" | "tc_isotropic_sc_dft";
export type DiscoveryPressureCompound = "LaH10" | "LaD10";
export type DiscoveryPressureLocator = typeof snapshot.locators[number];
export type DiscoveryPressureTokenLocator = typeof snapshot.rows[number]["formula_locator"];
export type DiscoveryPressureCell = {
  raw_value: string | null;
  value: number | null;
  unit: string | null;
  unit_status: string;
  uncertainty: null;
  missing_reason: string | null;
  locator: DiscoveryPressureTokenLocator | null;
  unit_locator_id: string | null;
};
export type DiscoveryPressureRow = Omit<typeof snapshot.rows[number], DiscoveryPressureQuantity | "pressure" | "formula"> & {
  formula: DiscoveryPressureCompound;
  pressure: DiscoveryPressureCell;
} & Record<DiscoveryPressureQuantity, DiscoveryPressureCell>;
export type DiscoveryPressureQuantityOption = Omit<typeof snapshot.quantities[number], "id"> & { id: DiscoveryPressureQuantity };
export type DiscoveryPressureSeries = Omit<typeof snapshot, "rows" | "quantities" | "default_quantity" | "default_compound" | "compounds"> & {
  rows: DiscoveryPressureRow[];
  quantities: DiscoveryPressureQuantityOption[];
  default_quantity: DiscoveryPressureQuantity;
  default_compound: DiscoveryPressureCompound;
  compounds: DiscoveryPressureCompound[];
};
export type DiscoveryPressurePoint = {
  row_id: string;
  source_data_row: number;
  formula: DiscoveryPressureCompound;
  quantity: DiscoveryPressureQuantity;
  pressure: number;
  value: number;
  pressure_raw: string;
  value_raw: string;
  pressure_unit: string;
  unit: string;
};

export const DISCOVERY_PRESSURE_SERIES_VERSION = "discovery-lah10-pressure-series/1.0.0";
export const discoveryPressureSeriesFilename = "discovery-lah10-pressure-series-2026-10-04.json";
export const discoveryPressureSeriesSha256 = "f80b7b855c154163dc4a18d02489fc8c97882154abc735ff6582fddaf0804e9c";

const quantities: DiscoveryPressureQuantity[] = ["electron_phonon_lambda", "omega_log", "tc_mcmillan", "tc_allen_dynes",
  "tc_anisotropic_me", "tc_isotropic_sc_dft"];
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

function validWindow(locator: DiscoveryPressureLocator) {
  return Number.isSafeInteger(locator.pdf_page_one_based) && locator.pdf_page_one_based >= 1 && locator.pdf_page_one_based <= 20
    && Number.isSafeInteger(locator.char_start) && Number.isSafeInteger(locator.char_end) && locator.char_start >= 0
    && locator.char_end > locator.char_start && locator.end_exclusive === true && hash(locator.window_sha256);
}

function validCell(cell: DiscoveryPressureCell, row: DiscoveryPressureRow, unit: string, locatorIds: Set<string>) {
  if (cell.value === null || cell.raw_value === null) return cell.value === null && cell.raw_value === null
    && cell.missing_reason !== null && cell.locator === null && cell.uncertainty === null;
  const token = cell.locator;
  return typeof cell.raw_value === "string" && /^\d+(?:\.\d+)?$/.test(cell.raw_value)
    && Number.isFinite(cell.value) && cell.value >= 0 && Number(cell.raw_value) === cell.value
    && cell.unit === unit && cell.uncertainty === null && cell.missing_reason === null
    && cell.unit_status === (unit === "1" ? "dimensionless_quantity_definition" : "printed_in_table_header")
    && cell.unit_locator_id !== null && locatorIds.has(cell.unit_locator_id)
    && token !== null && Number.isSafeInteger(token.char_start) && Number.isSafeInteger(token.char_end)
    && token.char_start >= row.row_locator.char_start && token.char_end <= row.row_locator.char_end
    && token.char_end > token.char_start && token.end_exclusive === true && hash(token.token_sha256);
}

/** Exact finite author-preprint source facts; this does not load catalogue or native calculation records. */
export function loadDiscoveryPressureSeries(value: unknown = snapshot): DiscoveryPressureSeries | null {
  if (!matchesSnapshot(value, snapshot)) return null;
  const table = value as DiscoveryPressureSeries;
  const locatorIds = new Set(table.locators.map(locator => locator.id));
  const wholeTable = table.locators.find(locator => locator.id === "extended-data-table-I");
  if (table.version !== DISCOVERY_PRESSURE_SERIES_VERSION || table.status !== "source_qualified_computational_pressure_series"
    || table.source_row_count !== 7 || table.rows.length !== 7 || table.counts_are_independent_experiments !== false
    || table.authority.canonical_field_updates !== 0 || Object.entries(table.authority).some(([key, flag]) => key !== "canonical_field_updates" && flag !== false)
    || table.source.source_edition !== "arxiv_author_preprint_v1" || table.source.arxiv_version !== "v1"
    || table.source.related_version_of_record.table_equivalence !== "not_verified"
    || !hash(table.source.pdf_sha256) || !hash(table.source.derived_text_sha256)
    || table.common_context.pressure_definition.axis_role !== "quantum_energy_pressure"
    || table.common_context.structure.coordinate_identity !== "unestablished"
    || table.common_context.structural_calculation_temperature.value !== null
    || table.scope.source_row_catalogue_association !== "unestablished" || table.scope.cross_solver_connection_allowed !== false
    || table.scope.cross_isotope_connection_allowed !== false || table.scope.new_fit_or_derivative_or_unit_conversion !== false
    || table.scope.raw_fulltext_or_PDF_included !== false || table.locators.some(locator => !validWindow(locator))
    || locatorIds.size !== table.locators.length || !wholeTable || wholeTable.pdf_page_one_based !== 11
    || new Set(table.rows.map(row => row.id)).size !== 7 || table.quantities.length !== 6
    || table.solvers.some(solver => solver.locator_ids.some(id => !locatorIds.has(id)))) return null;
  if (table.rows.some((row, index) => row.source_data_row !== index + 1 || !validWindow(row.row_locator)
    || row.row_locator.pdf_page_one_based !== 11 || row.row_locator.char_start < wholeTable.char_start
    || row.row_locator.char_end > wholeTable.char_end || row.formula_locator.char_start < row.row_locator.char_start
    || row.formula_locator.char_end > row.row_locator.char_end || row.formula_locator.char_end <= row.formula_locator.char_start
    || row.formula_locator.end_exclusive !== true || !hash(row.formula_locator.token_sha256)
    || row.formula !== (index < 4 ? "LaH10" : "LaD10")
    || !validCell(row.pressure, row, "GPa", locatorIds)
    || quantities.some(quantity => !validCell(row[quantity], row, table.quantities.find(option => option.id === quantity)!.unit, locatorIds)))) return null;
  return JSON.parse(JSON.stringify(table)) as DiscoveryPressureSeries;
}

export function discoveryPressureSeriesDownloadPath() {
  return `${process.env.NEXT_PUBLIC_BASE_PATH || ""}/research-pilots/${discoveryPressureSeriesFilename}`;
}

/** The reading URL explicitly addresses v1; no assertion of publisher-table equivalence or current bytes follows. */
export function discoveryPressurePaperHref(page?: number): string | null {
  const url = new URL(snapshot.source.source_url);
  if (url.href !== "https://arxiv.org/pdf/1907.11916v1") return null;
  if (page !== undefined) {
    if (!Number.isSafeInteger(page) || page < 1 || page > snapshot.source.pdf_pages) return null;
    url.hash = `page=${page}`;
  }
  return url.href;
}

/** Source order is retained. The selector cannot connect solvers, merge isotopes, synthesize a missing value or convert units. */
export function discoveryPressurePoints(value: unknown, quantity: DiscoveryPressureQuantity = "tc_anisotropic_me",
  compound: DiscoveryPressureCompound = "LaH10"): DiscoveryPressurePoint[] {
  const table = loadDiscoveryPressureSeries(value);
  if (!table || !quantities.includes(quantity) || !table.compounds.includes(compound)) return [];
  return table.rows.flatMap(row => {
    const cell = row[quantity];
    if (row.formula !== compound || row.pressure.value === null || row.pressure.raw_value === null || row.pressure.unit === null
      || cell.value === null || cell.raw_value === null || cell.unit === null) return [];
    return [{ row_id: row.id, source_data_row: row.source_data_row, formula: row.formula, quantity, pressure: row.pressure.value,
      value: cell.value, pressure_raw: row.pressure.raw_value, value_raw: cell.raw_value, pressure_unit: row.pressure.unit, unit: cell.unit }];
  });
}

export function discoveryPressureQuantityOptions(value: unknown): DiscoveryPressureQuantityOption[] {
  return loadDiscoveryPressureSeries(value)?.quantities ?? [];
}

/** All seven original rows and all four Tc channels are exported, regardless of the display selection. */
export function discoveryPressureSeriesCsv(value: unknown = snapshot): string {
  const table = loadDiscoveryPressureSeries(value);
  if (!table) throw new Error("The captured pressure source table is unavailable.");
  const headers = ["source_table_version", "source_data_row", "source_row_id", "compound", "isotope_label", "pressure_raw", "pressure_unit",
    "pressure_definition", "pressure_axis_role", "phase_family", "coordinate_identity", "retained_run_identity", "structural_calculation_temperature",
    "structural_temperature_status", "electronic_functional", "phonon_method", "anharmonic_hessian_approximation"];
  for (const quantity of quantities) headers.push(`${quantity}_raw`, `${quantity}_unit`, `${quantity}_unit_status`, `${quantity}_missing_reason`);
  for (const solver of table.solvers) headers.push(`${solver.id}_solver`, `${solver.id}_mu_star_raw`, `${solver.id}_mu_star_role`, `${solver.id}_coulomb_treatment`);
  headers.push("knowledge_origin", "catalogue_association", "scientific_acceptance", "ml_training_approved", "new_calculation_executed", "stable_host_validated",
    "source_edition", "arxiv_version", "source_submission_date", "pdf_printed_date", "related_vor_doi", "vor_table_equivalence", "source_pdf_sha256",
    "source_text_sha256", "dataset_sha256", "pdf_page", "row_char_start", "row_char_end", "row_window_sha256");
  const rows = table.rows.map(row => {
    const cells: (string | number | boolean | null)[] = [table.version, row.source_data_row, row.id, row.formula, row.isotope_label, row.pressure.raw_value,
      row.pressure.unit, table.common_context.pressure_definition.label, table.common_context.pressure_definition.axis_role, table.common_context.structure.phase_family,
      table.common_context.structure.coordinate_identity, table.common_context.structure.retained_run_identity, table.common_context.structural_calculation_temperature.value,
      table.common_context.structural_calculation_temperature.status, table.common_context.electronic_method.functional, table.common_context.anharmonic_method.name,
      table.common_context.anharmonic_method.fourth_order_term];
    for (const quantity of quantities) cells.push(row[quantity].raw_value, row[quantity].unit, row[quantity].unit_status, row[quantity].missing_reason);
    for (const solver of table.solvers) cells.push(solver.display_label, solver.mu_star.raw_value, solver.mu_star.role, solver.coulomb_treatment);
    cells.push(table.common_context.knowledge_origin, table.scope.source_row_catalogue_association, table.authority.scientific_acceptance,
      table.authority.ml_training_approved, table.authority.new_calculation_executed, table.authority.stable_host_validated, table.source.source_edition,
      table.source.arxiv_version, table.source.submission_date, table.source.pdf_printed_date, table.source.related_version_of_record.doi,
      table.source.related_version_of_record.table_equivalence, table.source.pdf_sha256, table.source.derived_text_sha256, discoveryPressureSeriesSha256,
      row.row_locator.pdf_page_one_based, row.row_locator.char_start, row.row_locator.char_end, row.row_locator.window_sha256);
    return cells;
  });
  const cell = (item: string | number | boolean | null) => `"${String(item ?? "").replaceAll('"', '""')}"`;
  return [headers, ...rows].map(row => row.map(cell).join(",")).join("\r\n") + "\r\n";
}
