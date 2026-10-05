import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Page from "@/app/materials/source-observations/nb-cvs-pressure/page";
import ObservationsPage from "@/app/materials/source-observations/page";
import { MaterialNbCvsPressure } from "@/components/MaterialNbCvsPressure";
import { MaterialSourceObservations } from "@/components/MaterialSourceObservations";
import { loadNbCvsPressure, nbCvsPressureDownloadPath, nbCvsPressureSnapshotSha256, type NbCvsPressure } from "@/lib/material-nb-cvs-pressure";
import { loadSourceObservationBatch, sourceObservationWindow } from "@/lib/material-source-observations";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("Actual Nb0.07-CVS pressure table", () => {
  it("pins all 32 cells and distinguishes extra property parameters from fit statistics and source dashes", () => {
    const name = "materials-nb-cvs-pressure-2026-10-05.json";
    const bytes = readFileSync(`public/research-pilots/${name}`);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(nbCvsPressureSnapshotSha256);
    expect(readFileSync(`public/research-pilots/${name}.sha256`, "utf8")).toBe(`${nbCvsPressureSnapshotSha256}  ${name}\n`);
    const data = loadNbCvsPressure()!;
    expect(data.pressure_columns.map(column => column.raw_value)).toEqual(["0", "0.4", "0.8", "1.2"]);
    expect(data.fields.map(field => field.cells.map(cell => cell.raw_value))).toEqual([
      ["6.9(3)", "5.7(3)", "10.0(4)", "12.5(1)"], ["381", "419", "315", "283"],
      ["1", "1", "0.73(4)", "1"], ["3.000(6)", "3.25(1)", "6.67(7)", "6.94(2)"],
      ["0.54(9)", "0.47(7)", "0.65(5)", "1.56(4)"], ["-", "-", "3.5(9)", "-"],
      ["4.5", "2.6", "15.4", "34.8"], ["0.346", "0.153", "1.1", "1.74"],
    ]);
    expect(data.counts).toMatchObject({ numeric_cells: 29, source_dashes: 3, additional_property_parameters: 18,
      fit_statistic_numeric_cells: 8, previously_displayed_numeric_cells: 3, additional_numeric_cells: 26,
      independent_experiments: null, formal_property_promotions: 0 });
    expect(data.fields.flatMap(field => field.cells).every(cell => cell.normalized_value === null)).toBe(true);
    expect(data.fields[0].cells[2].raw_uncertainty).toBe("(4)");
    expect(data.fields[2].display_unit).toBeNull();
    expect(data.method.origin).toBe("fit_of_experimental_data");
    expect(Object.values(data.authority).every(flag => flag === false)).toBe(true);
  });

  it("shows conditions and original temperature labels without combining distinct fits", () => {
    render(<Page />);
    const table = within(screen.getByRole("table", { name: "Nb0.07-CVS gap-structure fit parameters" }));
    expect(table.getAllByRole("cell")).toHaveLength(24);
    expect(table.getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["Parameter", "0 GPa", "0.4 GPa", "0.8 GPa", "1.2 GPa"]);
    expect(table.getByRole("rowheader", { name: /λ⁻²\(T = 0\) \(μm⁻²\)/ })).toBeInTheDocument();
    expect(table.getByRole("rowheader", { name: /λ\(T > 0\) \(nm\)/ })).toBeInTheDocument();
    expect(table.getByText("3.000(6)")).toBeInTheDocument();
    expect(table.getByText("3.5(9)")).toBeInTheDocument();
    expect(table.getAllByLabelText("Not listed, source dash")).toHaveLength(3);
    expect(screen.getByText(/Transverse-field μSR · 10 mT/)).toBeInTheDocument();
    expect(screen.getByText(/separate AC susceptibility measurements used zero-field/)).toBeInTheDocument();
    expect(screen.getByText(/Tc = 4.70\(3\) K, λ = 316\(5\) nm and Δ = 0.590\(5\) meV/)).toBeInTheDocument();
    expect(screen.getAllByText("Single nodeless s-wave")).toHaveLength(3);
    expect(screen.getAllByText("Double nodeless s-wave")).toHaveLength(1);
    expect(screen.getByText("Inspect 8 fit statistics").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByRole("region", { name: "Nb0.07-CVS gap-structure fit parameters, horizontally scrollable" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("link", { name: "Open PDF page 8 ↗" })).toHaveAttribute("href", "https://arxiv.org/pdf/2411.18744v1#page=8");
    expect(screen.getByRole("link", { name: "Download pressure-series metadata (JSON)" })).toHaveAttribute("download");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|—/);
  });

  it("is discoverable from the source hub and the relevant zero-pressure window only", () => {
    render(<ObservationsPage />);
    expect(screen.getByRole("link", { name: "Nb0.07-CVS pressure-series fits" })).toHaveAttribute("href", "/materials/source-observations/nb-cvs-pressure");
    expect(screen.getAllByRole("link", { name: "Compare all four pressure columns and fit statistics" })).toHaveLength(1);
    cleanup();
    const all = loadSourceObservationBatch()!;
    const pt = all.entries.filter(entry => (entry.source_window as { id?: string }).id !== "pressure_series_table_zero_column");
    const window = sourceObservationWindow(pt, null, "independent_captured_sources");
    render(<MaterialSourceObservations window={window} defaultExpanded />);
    expect(screen.queryByRole("link", { name: "Compare all four pressure columns and fit statistics" })).not.toBeInTheDocument();
  });

  it("rejects changed raw values, units, pressure binding, conditions, authority and executable links", () => {
    const changes: Array<(data: NbCvsPressure) => void> = [
      data => { data.fields[3].cells[0].raw_value = "4.70(3)"; },
      data => { data.fields[5].cells[0].raw_value = "0"; },
      data => { data.fields[0].display_unit = "nm⁻²"; },
      data => { data.fields[1].symbol = "EPC λ"; },
      data => { data.fields[5].cells[2].pressure_column_index_0_based = 0; },
      data => { data.method.applied_field.raw_value = "0"; },
      data => { data.authority.scientific_acceptance = true; },
      data => { data.source.html_url = "javascript:alert(1)"; },
    ];
    for (const change of changes) {
      const data = loadNbCvsPressure()!; change(data);
      expect(loadNbCvsPressure(data)).toBeNull();
      render(<MaterialNbCvsPressure snapshot={data} />);
      expect(screen.getByRole("status")).toHaveTextContent("readings are unavailable");
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      cleanup();
    }
    expect(loadNbCvsPressure(null)).toBeNull();
    const getter = loadNbCvsPressure()!;
    Object.defineProperty(getter, "fields", { enumerable: true, get() { throw Error("must not run"); } });
    expect(loadNbCvsPressure(getter)).toBeNull();
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/preview");
    expect(nbCvsPressureDownloadPath()).toBe("/preview/research-pilots/materials-nb-cvs-pressure-2026-10-05.json");
  });
});
