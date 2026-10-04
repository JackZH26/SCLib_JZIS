import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { Blob as NodeBlob } from "node:buffer";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DiscoverySourceComparison } from "@/components/DiscoverySourceComparison";
import { discoverySourcePaperHref, discoverySourceTableCsv, discoverySourceTableDownloadPath, discoverySourceTableFilename,
  discoverySourceTableSha256, filterDiscoverySourceRows, loadDiscoverySourceTable } from "@/lib/discovery-source-comparison";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.useRealTimers(); });

const sourceRows = [
  ["ThY2H24", "1161", "2.39", "300"], ["LaSc2H24", "839", "2.57", "286"], ["AcSc2H24", "983", "2.64", "276"],
  ["ZrMg2H24", "783", "2.68", "267"], ["CaZr2H24", "586", "3.02", "262"], ["ThCa2H24", "530", "2.96", "250"],
  ["KTi2H24", "595", "2.68", "215"], ["CeCa2H24", "951", "1.97", "206"], ["CeMg2H24", "901", "1.66", "203"],
  ["AcHf2H24", "1326", "1.46", "198"], ["AcZr2H24", "1333", "1.46", "197"], ["LaZr2H24", "1375", "1.41", "195"],
  ["ThSc2H24", "1584", "1.29", "194"], ["LaHf2H24", "1374", "1.34", "187"], ["CeSc2H24", "1572", "1.14", "164"],
  ["ThHf2H24", "1462", "1.06", "148"], ["LaTh2H24", "953", "1.12", "113"], ["CeHf2H24", "1428", "0.88", "108"],
  ["CeZr2H24", "1500", "0.85", "107"], ["CeTh2H24", "1132", "0.39", "4"], ["ThCe2H24", "1164", "0.35", "2"],
];

describe("AB2H24 published source comparison", () => {
  it("retains all 21 original rows, exact printed values and byte-pinned factual metadata", () => {
    const bytes = readFileSync(`public/research-pilots/${discoverySourceTableFilename}`);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(discoverySourceTableSha256);
    expect(readFileSync(`public/research-pilots/${discoverySourceTableFilename}.sha256`, "utf8")).toBe(`${discoverySourceTableSha256}  ${discoverySourceTableFilename}\n`);
    const table = loadDiscoverySourceTable()!;
    expect(table.rows.map(row => [row.formula, row.omega_log.raw_value, row.electron_phonon_lambda.raw_value, row.computed_tc.raw_value])).toEqual(sourceRows);
    expect(table.locators.find(locator => locator.id === "table-I")).toMatchObject({ pdf_page_one_based: 3, char_start: 9717, char_end: 10368,
      window_sha256: "23aa969de4a64f7ea3238167cf2a39c44ae0c9c47f2682be5ee1e925eccf0711" });
    expect(table.source.pdf_sha256).toBe("d601beae68163ed8e423fca34cbf6513330a9a8b12cdff75b1d5f30d623d5a81");
    expect(table.source.derived_text_sha256).toBe("a31918c668f46c46f37683c1828bc3b64fce84b1de7d526918e38ca45cab63df");
    expect(table.authority.canonical_field_updates).toBe(0);
    expect(table.authority.scientific_acceptance).toBe(false);
    expect(table.authority.ml_training_approved).toBe(false);
    expect(table.authority.new_calculation_executed).toBe(false);
    expect(table.counts_are_independent_experiments).toBe(false);
    expect(table.scope.source_row_catalogue_association).toBe("unestablished");
    expect(bytes.toString()).not.toMatch(/\/Users\/|\/private\/|base64|"material_id"|"selected_result_id"|"full_text"|"raw_pdf"/);
    for (const row of table.rows) {
      expect(row.omega_log).toMatchObject({ value: null, unit: null, unit_status: "not_printed_in_table" });
      expect(row.electron_phonon_lambda.uncertainty).toBeNull();
      expect(row.computed_tc.uncertainty).toBeNull();
      expect(row.field_locators.formula.token_sha256).toBe(createHash("sha256").update(row.formula).digest("hex"));
      expect(row.field_locators.electron_phonon_lambda.token_sha256).toBe(createHash("sha256").update(row.electron_phonon_lambda.raw_value).digest("hex"));
      expect(row.field_locators.computed_tc.token_sha256).toBe(createHash("sha256").update(row.computed_tc.raw_value).digest("hex"));
      expect(row.field_locators.omega_log.token_sha256).toBe(createHash("sha256").update(row.omega_log.raw_value).digest("hex"));
    }
  });

  it("rejects changed pressures, model assumptions, source identities, unit guesses, order and scientific authority", () => {
    const edits: ((table: any) => void)[] = [
      table => { table.common_context.pressure.value = 140; },
      table => { table.common_context.mu_star.value = 0.13; },
      table => { table.common_context.tc_solver.table_label = "Allen-Dynes equation"; },
      table => { table.common_context.prototype.scope = "identical validated coordinates"; },
      table => { table.rows[5].omega_log.value = 530; table.rows[5].omega_log.unit = "K"; },
      table => { table.rows[5].electron_phonon_lambda.raw_value = "2.960"; },
      table => { table.rows[5].computed_tc.value = 300; },
      table => { table.rows[5].computed_tc.uncertainty = 0; },
      table => { table.rows[5].field_locators.computed_tc.char_start += 1; },
      table => { table.rows.reverse(); },
      table => { table.rows.push(table.rows[0]); },
      table => { table.source.source_url = "https://example.org/another-source.pdf"; },
      table => { table.scope.pressure_response_series_established = true; },
      table => { table.source_notes[1].summary = "ThCa2H24 is unstable at 250 GPa"; },
      table => { table.authority.stable_host_validated = true; },
      table => { table.authority.scientific_acceptance = true; },
      table => { table.authority.ml_training_approved = true; },
      table => { table.authority.new_calculation_executed = true; },
      table => { table.scope.source_row_catalogue_association = "matched"; },
      table => { table.raw_full_text = "unreviewed source prose"; },
    ];
    for (const edit of edits) {
      const changed = loadDiscoverySourceTable()!;
      edit(changed);
      expect(loadDiscoverySourceTable(changed)).toBeNull();
      expect(() => discoverySourceTableCsv(changed)).toThrow("The captured source table is unavailable.");
    }
    expect(loadDiscoverySourceTable(null)).toBeNull();
    expect(loadDiscoverySourceTable({})).toBeNull();
  });

  it("shows the common source model and two actual physical axes, without treating omega_log as a normalized quantity", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<DiscoverySourceComparison />);
    expect(screen.getByRole("heading", { name: "Source study comparison" })).toBeInTheDocument();
    expect(document.getElementById("discovery-source-comparisons")).toHaveClass("scroll-mt-24", "min-w-0");
    expect(screen.getByText("300 GPa · isotropic Eliashberg equation · assumed μ* = 0.1")).toBeInTheDocument();
    const plot = screen.getByRole("img", { name: /Published EPC lambda and computed Tc at 300 GPa/ });
    expect(plot.querySelectorAll("circle[data-source-row-id]")).toHaveLength(21);
    const point = plot.querySelector('circle[data-source-row-id="ab2h24-table-I-row-06"]')!;
    expect(Number(point.getAttribute("cx"))).toBeCloseTo(62 + 2.96 / 3.2 * 454);
    expect(Number(point.getAttribute("cy"))).toBeCloseTo(274 - 250 / 320 * 246);
    expect(point).toHaveAttribute("data-selected", "false");
    expect(point.querySelector("title")).toHaveTextContent("ThCa2H24: λ 2.96; computed Tc 250 K; source row 6");
    expect(plot.querySelector("path, polyline")).toBeNull();
    expect(screen.getByText(/ωlog has no printed table unit/)).toHaveTextContent("excluded from the plot");
    expect(screen.getByText(/Different compounds at one pressure/)).toHaveTextContent("does not establish a pressure response curve or survival at 300 K and 1 atm");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps all 21 table rows in source order and provides native keyboard-focusable comparison controls", () => {
    render(<DiscoverySourceComparison />);
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(21);
    for (const [index, row] of rows.entries()) {
      const cells = within(row).getAllByRole("cell");
      expect(cells[1]).toHaveTextContent(String(index + 1));
      expect(within(row).getByRole("rowheader").textContent).toContain(sourceRows[index][0]);
      expect(cells[2].textContent).toBe(sourceRows[index][2]);
      expect(cells[3].textContent).toBe(sourceRows[index][1]);
      expect(cells[4].textContent).toBe(sourceRows[index][3]);
    }
    const checkbox = screen.getByRole("checkbox", { name: "Compare ThCa2H24" });
    expect(checkbox).toHaveAttribute("type", "checkbox");
    expect(checkbox).toHaveClass("h-4", "w-4");
    checkbox.focus(); expect(checkbox).toHaveFocus();
    expect(screen.getByRole("region", { name: "AB2H24 source table, horizontally scrollable" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("region", { name: "AB2H24 source table, horizontally scrollable" })).toHaveClass("max-w-full", "overflow-x-auto");
    expect(screen.getByRole("region", { name: "Published lambda and Tc plot, horizontally scrollable" })).toHaveClass("max-w-full", "overflow-x-auto");
  });

  it("compares two rows before the plot, caps selection at two and highlights the corresponding source points", () => {
    render(<DiscoverySourceComparison />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare ThCa2H24" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare ThY2H24" }));
    const comparison = screen.getByRole("region", { name: "Selected source rows" });
    expect(within(comparison).getByText("2.96")).toBeInTheDocument();
    expect(within(comparison).getByText("250")).toBeInTheDocument();
    expect(within(comparison).getByText("2.39")).toBeInTheDocument();
    expect(within(comparison).getByText("300")).toBeInTheDocument();
    expect(within(comparison).getAllByText("ωlog (unit not printed)")).toHaveLength(2);
    const table = screen.getByRole("table");
    expect(comparison.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const plot = screen.getByRole("img", { name: /Published EPC lambda/ });
    expect(plot.querySelectorAll('circle[data-selected="true"]')).toHaveLength(2);
    expect(screen.getByRole("checkbox", { name: "Compare LaSc2H24" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Jump to selected comparison" }).getAttribute("href")).toBe(`#${within(comparison).getByRole("heading", { name: "Selected source rows" }).id}`);
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare ThCa2H24" }));
    expect(screen.getByRole("checkbox", { name: "Compare LaSc2H24" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Clear comparison" }));
    expect(screen.queryByRole("region", { name: "Selected source rows" })).not.toBeInTheDocument();
    expect(plot.querySelectorAll('circle[data-selected="true"]')).toHaveLength(0);
  });

  it("filters A and B without sorting or combining source rows, and clears previous selections", () => {
    const table = loadDiscoverySourceTable()!;
    expect(filterDiscoverySourceRows(table, "Th").map(row => row.formula)).toEqual(["ThY2H24", "ThCa2H24", "ThSc2H24", "ThHf2H24", "ThCe2H24"]);
    expect(filterDiscoverySourceRows(table, "", "Sc").map(row => row.formula)).toEqual(["LaSc2H24", "AcSc2H24", "ThSc2H24", "CeSc2H24"]);
    render(<DiscoverySourceComparison />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare ThCa2H24" }));
    fireEvent.change(screen.getByRole("combobox", { name: "A element" }), { target: { value: "Th" } });
    expect(screen.getByText(/5 of 21 source rows shown/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Selected source rows" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Compare ThCa2H24" })).not.toBeChecked();
    const filteredPlot = screen.getByRole("img", { name: /Published EPC lambda/ });
    expect(filteredPlot.querySelectorAll("circle[data-source-row-id]")).toHaveLength(5);
    fireEvent.change(screen.getByRole("combobox", { name: "B element" }), { target: { value: "Sc" } });
    expect(screen.getByText(/1 of 21 source rows shown/)).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(screen.getByRole("checkbox", { name: "Compare ThSc2H24" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear element filters" }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(21);
  });

  it("uses an explicit empty filter state rather than a fallback point or fabricated zero", () => {
    render(<DiscoverySourceComparison />);
    fireEvent.change(screen.getByRole("combobox", { name: "A element" }), { target: { value: "K" } });
    fireEvent.change(screen.getByRole("combobox", { name: "B element" }), { target: { value: "Hf" } });
    expect(screen.getByText(/No Table I source rows match these elements/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/0 of 21 source rows shown/)).toBeInTheDocument();
  });

  it("separates source-selected dynamic stability, class-level most, unresolved units and fitted-CS scope from individual row facts", () => {
    render(<DiscoverySourceComparison />);
    expect(screen.getByText(/The Table I caption describes/, { selector: "p" })).toHaveTextContent("author-reported selection criterion");
    const classNote = screen.getByText(/The discussion says most of these compounds/, { selector: "p" });
    expect(classNote).toHaveTextContent("not thermodynamically stable at 300 GPa");
    expect(classNote).toHaveTextContent("dynamically unstable when pressure decreases to 250 GPa");
    expect(classNote).toHaveTextContent("not assigned to individual table rows");
    expect(screen.getByText(/The paper fits its CS descriptor against Tc/, { selector: "p" })).toHaveTextContent("not applied to predict new compounds");
    expect(screen.getByText(/The abstract gives a maximum Tc of 276 K/, { selector: "p" })).toHaveTextContent("Table I lists 300 K for ThY2H24");
    expect(screen.getByText(/The table prints no uncertainties/, { selector: "p" })).toHaveTextContent("does not establish zero uncertainty");
    expect(screen.getByRole("table").textContent).not.toMatch(/unstable|accepted|training|530 K|1161 K|RPS|CS|300 K/);
    for (const disclosure of document.querySelectorAll("details")) expect(disclosure).not.toHaveAttribute("open");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|—/);
  });

  it("exports 21 CSV rows with conditions, raw omega_log, unresolved units and source locators regardless of current filters", () => {
    const csv = discoverySourceTableCsv();
    const lines = csv.trimEnd().split("\r\n");
    expect(lines).toHaveLength(22);
    const values = (line: string) => line.slice(1, -1).split('","');
    const headers = values(lines[0]);
    const rows = lines.slice(1).map(values);
    const get = (row: string[], key: string) => row[headers.indexOf(key)];
    expect(rows.map(row => get(row, "compound"))).toEqual(sourceRows.map(row => row[0]));
    expect(get(rows[5], "lambda_raw")).toBe("2.96");
    expect(get(rows[5], "omega_log_raw")).toBe("530");
    expect(get(rows[5], "computed_tc_raw")).toBe("250");
    for (const row of rows) {
      expect(get(row, "omega_log_unit")).toBe("");
      expect(get(row, "omega_log_unit_status")).toBe("not_printed_in_table");
      expect(get(row, "pressure_raw")).toBe("300");
      expect(get(row, "pressure_unit")).toBe("GPa");
      expect(get(row, "mu_star_raw")).toBe("0.1");
      expect(get(row, "mu_star_role")).toBe("assumed_model_parameter");
      expect(get(row, "tc_solver")).toBe("isotropic Eliashberg equation");
      expect(get(row, "knowledge_origin")).toBe("Computed");
      expect(get(row, "catalogue_association")).toBe("unestablished");
      expect(get(row, "scientific_acceptance")).toBe("false");
      expect(get(row, "ml_training_approved")).toBe("false");
      expect(get(row, "new_calculation_executed")).toBe("false");
      expect(get(row, "doi")).toBe("10.1103/7lg7-l3x8");
      expect(get(row, "row_window_sha256")).toMatch(/^[a-f0-9]{64}$/);
    }
  });

  it("starts a CSV browser download containing all rows and releases its object URL", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("Blob", NodeBlob);
    const create = vi.fn((_blob: Blob) => "blob:source-csv"); const revoke = vi.fn();
    const NativeURL = URL;
    vi.stubGlobal("URL", class extends NativeURL { static createObjectURL = create; static revokeObjectURL = revoke; });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<DiscoverySourceComparison />);
    fireEvent.change(screen.getByRole("combobox", { name: "A element" }), { target: { value: "K" } });
    fireEvent.click(screen.getByRole("button", { name: "Export all 21 source rows (CSV)" }));
    expect(create).toHaveBeenCalledTimes(1);
    expect(await create.mock.calls[0][0].text()).toBe(discoverySourceTableCsv());
    expect(click).toHaveBeenCalledTimes(1);
    expect(click.mock.instances[0]).toHaveAttribute("download", `sclib-ab2h24-source-table-${discoverySourceTableSha256.slice(0, 12)}.csv`);
    expect(click.mock.instances[0]).toHaveAttribute("href", "blob:source-csv");
    expect(screen.getByText(/CSV download requested for all 21 source rows/)).toBeInTheDocument();
    vi.advanceTimersByTime(1000); expect(revoke).toHaveBeenCalledWith("blob:source-csv");
  });

  it("shows a clear CSV failure while retaining the independently accessible JSON resource", () => {
    const NativeURL = URL;
    vi.stubGlobal("URL", class extends NativeURL { static createObjectURL = () => { throw new Error("download blocked"); }; });
    render(<DiscoverySourceComparison />);
    fireEvent.click(screen.getByRole("button", { name: "Export all 21 source rows (CSV)" }));
    expect(screen.getByText(/The browser could not start the CSV download/)).toHaveTextContent("static JSON resource remains available");
    expect(screen.getByRole("link", { name: "Download all 21 source rows (JSON)" })).toHaveAttribute("href", discoverySourceTableDownloadPath());
  });

  it("provides bounded JSON, checksum and finite publisher links with configured base paths", () => {
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib-preview");
    render(<DiscoverySourceComparison />);
    const metadata = screen.getByRole("region", { name: "Source table metadata JSON" });
    expect(metadata).toHaveAttribute("tabindex", "0");
    expect(metadata).toHaveClass("max-h-80", "max-w-full", "overflow-auto", "whitespace-pre-wrap", "break-all");
    expect(JSON.parse(metadata.textContent!)).toEqual(loadDiscoverySourceTable());
    expect(screen.getByRole("link", { name: "Download all 21 source rows (JSON)" })).toHaveAttribute("href", `/sclib-preview/research-pilots/${discoverySourceTableFilename}`);
    expect(screen.getByRole("link", { name: "Download file SHA-256" })).toHaveAttribute("href", `/sclib-preview/research-pilots/${discoverySourceTableFilename}.sha256`);
    expect(screen.getByRole("link", { name: "Read Table I in the publisher PDF" })).toHaveAttribute("href", "https://journals.aps.org/prresearch/pdf/10.1103/7lg7-l3x8#page=3");
    expect(discoverySourcePaperHref(2)).toBe("https://journals.aps.org/prresearch/pdf/10.1103/7lg7-l3x8#page=2");
    expect(discoverySourcePaperHref(7)).toBe("https://journals.aps.org/prresearch/pdf/10.1103/7lg7-l3x8#page=7");
    for (const page of [0, -1, 1.5, 8, Infinity, NaN]) expect(discoverySourcePaperHref(page)).toBeNull();
  });

  it("does not replace an unavailable or altered source snapshot with default scientific values", () => {
    render(<DiscoverySourceComparison table={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("The captured source comparison is unavailable.");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    cleanup();
    const changed = loadDiscoverySourceTable()!;
    changed.authority.ml_training_approved = true;
    render(<DiscoverySourceComparison table={changed} />);
    expect(screen.getByRole("status")).toHaveTextContent("unavailable");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
