import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { discoveryPressurePaperHref, discoveryPressurePoints, discoveryPressureQuantityOptions, discoveryPressureSeriesCsv,
  discoveryPressureSeriesDownloadPath, discoveryPressureSeriesFilename, discoveryPressureSeriesSha256, loadDiscoveryPressureSeries,
  type DiscoveryPressureQuantity } from "@/lib/discovery-pressure-series";

afterEach(() => vi.unstubAllEnvs());

const fieldOrder = ["formula", "pressure", "electron_phonon_lambda", "omega_log", "tc_mcmillan", "tc_allen_dynes", "tc_anisotropic_me", "tc_isotropic_sc_dft"];
const numericKeys: (DiscoveryPressureQuantity | "pressure")[] = ["pressure", "electron_phonon_lambda", "omega_log", "tc_mcmillan",
  "tc_allen_dynes", "tc_anisotropic_me", "tc_isotropic_sc_dft"];
const sourceRows = [
  ["LaH10", "129", "3.62", "76.4", "171.8", "252.6", "255.3", "230"],
  ["LaH10", "163", "2.67", "96.4", "197.1", "247.0", "242.8", "225"],
  ["LaH10", "214", "2.06", "115.5", "196.3", "235.9", "237.9", "210"],
  ["LaH10", "264", "1.73", "126.6", "189.5", "219.2", "216.9", "201"],
  ["LaD10", "159", "3.14", "63.5", "135.0", "184.2", "180.4", "171"],
  ["LaD10", "210", "2.21", "81.7", "145.5", "176.5", "172.9", "158"],
  ["LaD10", "260", "1.80", "92.2", "142.2", "164.6", "157.9", "151"],
];

describe("LaH10 author-source computational pressure series", () => {
  it("preserves the complete seven-row source table, printed precision, field order and byte pins", () => {
    const bytes = readFileSync(`public/research-pilots/${discoveryPressureSeriesFilename}`);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(discoveryPressureSeriesSha256);
    expect(readFileSync(`public/research-pilots/${discoveryPressureSeriesFilename}.sha256`, "utf8"))
      .toBe(`${discoveryPressureSeriesSha256}  ${discoveryPressureSeriesFilename}\n`);
    const table = loadDiscoveryPressureSeries()!;
    expect(table.source_row_count).toBe(7);
    expect(table.source_field_order).toEqual(fieldOrder);
    expect(table.rows.map(row => [row.formula, ...numericKeys.map(key => row[key].raw_value)])).toEqual(sourceRows);
    expect(table.rows.map(row => row.source_data_row)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(table.source).toMatchObject({ source_edition: "arxiv_author_preprint_v1", arxiv_version: "v1", submission_date: "2019-07-27",
      pdf_printed_date: "2019-07-30", pdf_pages: 20, table_pdf_page_one_based: 11,
      pdf_sha256: "5ec05581e7ea71074a80afee8b4c4dafdc524938e830b849143ec35e7726c07f",
      derived_text_sha256: "383697d172df6415084fe68491307c93308519d1b4047357e359e1e9e89007ef" });
    expect(table.source.related_version_of_record.table_equivalence).toBe("not_verified");
    expect(table.locators).toHaveLength(10);
    expect(table.locators.find(locator => locator.id === "extended-data-table-I")).toMatchObject({ pdf_page_one_based: 11,
      char_start: 64900, char_end: 66714, end_exclusive: true,
      window_sha256: "cb9d8e141eb008e11c67dcac3c0e33617df1b9a60575550756734a5df51d0469" });
    expect(bytes.length).toBeLessThan(50_000);
    expect(bytes.toString()).not.toMatch(/\/Users\/|\/private\/|base64|"material_id"|"selected_result_id"|"full_text"|"raw_pdf"/);
  });

  it("retains all 49 numeric cells and 56 field-token pins without inventing uncertainties or missing values", () => {
    const table = loadDiscoveryPressureSeries()!;
    let cellCount = 0;
    for (const row of table.rows) {
      expect(row.formula_locator.token_sha256).toBe(createHash("sha256").update(row.formula).digest("hex"));
      for (const [index, key] of numericKeys.entries()) {
        const cell = row[key];
        expect(cell.value).toBe(Number(sourceRows[row.source_data_row - 1][index + 1]));
        expect(cell.raw_value).not.toBeNull();
        expect(cell.uncertainty).toBeNull();
        expect(cell.missing_reason).toBeNull();
        expect(cell.locator!.token_sha256).toBe(createHash("sha256").update(cell.raw_value!).digest("hex"));
        expect(cell.locator!.char_start).toBeGreaterThanOrEqual(row.row_locator.char_start);
        expect(cell.locator!.char_end).toBeLessThanOrEqual(row.row_locator.char_end);
        cellCount += 1;
      }
      expect(row.pressure.unit).toBe("GPa");
      expect(row.electron_phonon_lambda).toMatchObject({ unit: "1", unit_status: "dimensionless_quantity_definition" });
      expect(row.omega_log).toMatchObject({ unit: "meV", unit_status: "printed_in_table_header" });
      expect(row.tc_anisotropic_me.unit).toBe("K");
    }
    expect(cellCount).toBe(49);
  });

  it("keeps quantum pressure, anharmonic approximation and distinct Coulomb treatments explicit", () => {
    const table = loadDiscoveryPressureSeries()!;
    expect(table.common_context.pressure_definition).toMatchObject({ unit: "GPa", axis_role: "quantum_energy_pressure",
      label: "Pressure calculated from quantum E(R)" });
    expect(table.common_context.structure).toMatchObject({ phase_family: "Fm-3m", coordinate_identity: "unestablished", retained_run_identity: "unestablished" });
    expect(table.common_context.structural_calculation_temperature).toMatchObject({ value: null, unit: null, status: "not_established_for_table_rows" });
    expect(table.common_context.anharmonic_method.fourth_order_term).toBe("Φ(4) = 0 in the reported superconductivity calculations");
    const solvers = Object.fromEntries(table.solvers.map(solver => [solver.id, solver]));
    for (const id of ["mcmillan", "allen_dynes"]) expect(solvers[id].mu_star)
      .toEqual({ raw_value: "0.1", value: 0.1, role: "assumed_scalar_coulomb_pseudopotential" });
    expect(solvers.anisotropic_me.mu_star).toEqual({ raw_value: null, value: null, role: "scalar_mu_star_not_specified_for_reported_rpa_treatment" });
    expect(solvers.anisotropic_me.coulomb_treatment).toContain("k-averaged static");
    expect(solvers.isotropic_sc_dft.mu_star).toEqual({ raw_value: null, value: null, role: "no_empirical_scalar_mu_star_parameter" });
    expect(solvers.isotropic_sc_dft.coulomb_treatment).toContain("iso-energy surfaces");
    expect(table.scope).toMatchObject({ source_row_catalogue_association: "unestablished", cross_solver_connection_allowed: false,
      cross_isotope_connection_allowed: false, isotope_coefficient_derived: false, stable_host_at_300K_and_1atm_established: false,
      new_fit_or_derivative_or_unit_conversion: false, raw_fulltext_or_PDF_included: false });
    expect(table.counts_are_independent_experiments).toBe(false);
    expect(table.authority.canonical_field_updates).toBe(0);
    expect(Object.entries(table.authority).filter(([key]) => key !== "canonical_field_updates").every(([, value]) => value === false)).toBe(true);
  });

  it("rejects edited units, pressure meanings, methods, editions, order, missing-cell rewrites, associations and extra keys", () => {
    const edits: ((table: any) => void)[] = [
      table => { table.rows[0].pressure.value = 0; },
      table => { table.rows[0].pressure.raw_value = "129.0"; },
      table => { table.rows[0].omega_log.unit = "K"; },
      table => { table.rows[0].tc_anisotropic_me.value = null; table.rows[0].tc_anisotropic_me.raw_value = null; },
      table => { table.rows[0].tc_anisotropic_me.uncertainty = 0; },
      table => { table.rows[0].tc_anisotropic_me.locator.char_start += 1; },
      table => { table.rows[0].formula = "LaD10"; },
      table => { table.rows.reverse(); },
      table => { table.rows.push(table.rows[0]); },
      table => { table.source_field_order.reverse(); },
      table => { table.quantities.reverse(); },
      table => { table.default_quantity = "tc_mcmillan"; },
      table => { table.solvers[2].mu_star.value = 0.1; },
      table => { table.solvers[3].mu_star.role = "assumed_scalar_coulomb_pseudopotential"; },
      table => { table.common_context.pressure_definition.axis_role = "external_stress_target"; },
      table => { table.common_context.anharmonic_method.fourth_order_term = "full fourth-order Hessian"; },
      table => { table.common_context.structural_calculation_temperature.value = 300; },
      table => { table.common_context.structure.coordinate_identity = "verified"; },
      table => { table.source.arxiv_version = "v2"; },
      table => { table.source.source_edition = "publisher_version_of_record"; },
      table => { table.source.source_url = "https://arxiv.org/pdf/1907.11916"; },
      table => { table.source.related_version_of_record.table_equivalence = "verified"; },
      table => { table.scope.source_row_catalogue_association = "matched"; },
      table => { table.scope.cross_solver_connection_allowed = true; },
      table => { table.scope.cross_isotope_connection_allowed = true; },
      table => { table.authority.stable_host_validated = true; },
      table => { table.authority.scientific_acceptance = true; },
      table => { table.authority.ml_training_approved = true; },
      table => { table.authority.new_calculation_executed = true; },
      table => { table.raw_full_text = "unreviewed prose"; },
    ];
    for (const edit of edits) {
      const changed = loadDiscoveryPressureSeries()!;
      edit(changed);
      expect(loadDiscoveryPressureSeries(changed)).toBeNull();
      expect(discoveryPressurePoints(changed)).toEqual([]);
      expect(discoveryPressureQuantityOptions(changed)).toEqual([]);
      expect(() => discoveryPressureSeriesCsv(changed)).toThrow("The captured pressure source table is unavailable.");
    }
    expect(loadDiscoveryPressureSeries(null)).toBeNull();
    expect(loadDiscoveryPressureSeries({})).toBeNull();
  });

  it("defaults to the actual anisotropic ME channel and isolates each compound and quantity without interpolation", () => {
    const table = loadDiscoveryPressureSeries()!;
    expect(table.default_quantity).toBe("tc_anisotropic_me");
    expect(discoveryPressureQuantityOptions(table).map(option => option.id)).toEqual(["tc_anisotropic_me", "tc_isotropic_sc_dft",
      "electron_phonon_lambda", "omega_log", "tc_mcmillan", "tc_allen_dynes"]);
    expect(discoveryPressurePoints(table).map(point => [point.formula, point.pressure, point.value]))
      .toEqual([["LaH10", 129, 255.3], ["LaH10", 163, 242.8], ["LaH10", 214, 237.9], ["LaH10", 264, 216.9]]);
    expect(discoveryPressurePoints(table, "tc_isotropic_sc_dft", "LaH10").map(point => [point.pressure, point.value]))
      .toEqual([[129, 230], [163, 225], [214, 210], [264, 201]]);
    expect(discoveryPressurePoints(table, "tc_anisotropic_me", "LaD10").map(point => [point.source_data_row, point.pressure, point.value]))
      .toEqual([[5, 159, 180.4], [6, 210, 172.9], [7, 260, 157.9]]);
    for (const quantity of numericKeys.filter((key): key is DiscoveryPressureQuantity => key !== "pressure")) {
      const points = discoveryPressurePoints(table, quantity, "LaH10");
      expect(points).toHaveLength(4);
      expect(points.every(point => point.quantity === quantity && point.pressure_unit === "GPa")).toBe(true);
      expect(points.map(point => point.value_raw)).toEqual(table.rows.slice(0, 4).map(row => row[quantity].raw_value));
    }
    expect(discoveryPressurePoints(table, "omega_log").every(point => point.unit === "meV")).toBe(true);
    expect(discoveryPressurePoints(table, "unknown" as DiscoveryPressureQuantity)).toEqual([]);
    expect(discoveryPressurePoints(table, "tc_anisotropic_me", "H3S" as any)).toEqual([]);
    expect(discoveryPressurePoints(table).some(point => point.pressure === 0)).toBe(false);
  });

  it("returns independent copies rather than letting selection or metadata edits mutate the frozen source", () => {
    const first = loadDiscoveryPressureSeries()!;
    first.rows[0].pressure.value = 0;
    expect(loadDiscoveryPressureSeries()!.rows[0].pressure.value).toBe(129);
    const options = discoveryPressureQuantityOptions(loadDiscoveryPressureSeries()!);
    options[0].label = "Changed";
    expect(discoveryPressureQuantityOptions(loadDiscoveryPressureSeries()!)[0].label).toBe("Anisotropic Migdal–Éliashberg Tc");
  });

  it("exports all seven rows, every solver and source conditions including null temperature and distinct μ* roles", () => {
    const csv = discoveryPressureSeriesCsv();
    const records = csv.trimEnd().split("\r\n").map(line => Array.from(line.matchAll(/"((?:""|[^"])*)"/g), match => match[1].replaceAll('""', '"')));
    const [header, ...rows] = records;
    expect(rows).toHaveLength(7);
    expect(rows.every(row => row.length === header.length)).toBe(true);
    const cells = rows.map(row => Object.fromEntries(header.map((key, index) => [key, row[index]])));
    for (const [index, row] of cells.entries()) {
      expect(row.compound).toBe(sourceRows[index][0]);
      expect(row.pressure_raw).toBe(sourceRows[index][1]);
      for (const [column, key] of numericKeys.slice(1).entries()) expect(row[`${key}_raw`]).toBe(sourceRows[index][column + 2]);
      expect(row.omega_log_unit).toBe("meV");
      expect(row.pressure_axis_role).toBe("quantum_energy_pressure");
      expect(row.structural_calculation_temperature).toBe("");
      expect(row.structural_temperature_status).toBe("not_established_for_table_rows");
      expect(row.mcmillan_mu_star_raw).toBe("0.1");
      expect(row.allen_dynes_mu_star_raw).toBe("0.1");
      expect(row.anisotropic_me_mu_star_raw).toBe("");
      expect(row.anisotropic_me_mu_star_role).toBe("scalar_mu_star_not_specified_for_reported_rpa_treatment");
      expect(row.isotropic_sc_dft_mu_star_raw).toBe("");
      expect(row.isotropic_sc_dft_mu_star_role).toBe("no_empirical_scalar_mu_star_parameter");
      expect(row.catalogue_association).toBe("unestablished");
      expect(row.scientific_acceptance).toBe("false");
      expect(row.ml_training_approved).toBe("false");
      expect(row.new_calculation_executed).toBe("false");
      expect(row.stable_host_validated).toBe("false");
      expect(row.source_edition).toBe("arxiv_author_preprint_v1");
      expect(row.vor_table_equivalence).toBe("not_verified");
      expect(row.dataset_sha256).toBe(discoveryPressureSeriesSha256);
      expect(row.row_window_sha256).toMatch(/^[a-f0-9]{64}$/);
    }
    expect(cells[6].electron_phonon_lambda_raw).toBe("1.80");
    expect(cells[0].tc_anisotropic_me_raw).toBe("255.3");
    expect(csv.endsWith("\r\n")).toBe(true);
  });

  it("keeps reading links version-specific and supports the deployed base path", () => {
    expect(discoveryPressurePaperHref()).toBe("https://arxiv.org/pdf/1907.11916v1");
    expect(discoveryPressurePaperHref(11)).toBe("https://arxiv.org/pdf/1907.11916v1#page=11");
    expect(discoveryPressurePaperHref(20)).toBe("https://arxiv.org/pdf/1907.11916v1#page=20");
    for (const invalid of [0, 21, -1, 1.5, Number.NaN]) expect(discoveryPressurePaperHref(invalid)).toBeNull();
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib");
    expect(discoveryPressureSeriesDownloadPath()).toBe(`/sclib/research-pilots/${discoveryPressureSeriesFilename}`);
  });
});
