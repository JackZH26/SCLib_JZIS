import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Page from "@/app/materials/source-observations/pressure-and-tables/page";
import { MaterialThermalTable } from "@/components/MaterialThermalTable";
import { loadThermalTable, thermalTableDownloadPath, thermalTableSnapshotSha256 } from "@/lib/material-thermal-table";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("Actual Mo Table II thermal readings", () => {
  it("keeps download bytes and table-derived quantities pinned without converting their molar basis", () => {
    const file = "materials-thermal-table-2026-10-05.json";
    const bytes = readFileSync(`public/research-pilots/${file}`);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(thermalTableSnapshotSha256);
    expect(readFileSync(`public/research-pilots/${file}.sha256`, "utf8")).toBe(`${thermalTableSnapshotSha256}  ${file}\n`);
    const data = loadThermalTable()!;
    expect(data.readings.map(row => [row.formula_as_printed, row.raw_value, row.raw_unit])).toEqual([
      ["Mo5P1.1B1.9", "3.16", "mJ/mol-at./K2"], ["Mo5P1.1B1.9", "492", "K"],
      ["Mo5PB2", "3.07", "mJ/mol-at./K2"], ["Mo5PB2", "501", "K"],
    ]);
    expect(data.readings.every(row => row.raw_uncertainty === null && row.normalization === "none")).toBe(true);
    expect(data.source.publication_revision_verified).toBe(false);
    expect(data.scope.table_I_sample_association).toBe("unestablished");
    expect(Object.values(data.authority).every(value => !value)).toBe(true);
  });

  it("rejects changed compositions, invented uncertainty, moved columns, units, authority and external URLs", () => {
    const changes = [
      (data: NonNullable<ReturnType<typeof loadThermalTable>>) => { data.readings[0].formula_as_printed = "Mo5P0.9B2.1"; },
      (data: NonNullable<ReturnType<typeof loadThermalTable>>) => { data.readings[0].raw_value = "3.16(1)"; },
      (data: NonNullable<ReturnType<typeof loadThermalTable>>) => { data.readings[0].column_index_0_based = 2; },
      (data: NonNullable<ReturnType<typeof loadThermalTable>>) => { data.readings[0].raw_unit = "mJ/mol/K2"; },
      (data: NonNullable<ReturnType<typeof loadThermalTable>>) => { data.authority.scientific_acceptance = true; },
      (data: NonNullable<ReturnType<typeof loadThermalTable>>) => { data.source.source_url = "javascript:alert(1)"; },
    ];
    for (const change of changes) {
      const data = loadThermalTable()!; change(data);
      expect(loadThermalTable(data)).toBeNull();
      render(<MaterialThermalTable snapshot={data} />);
      expect(screen.getByRole("status")).toHaveTextContent("Captured heat-capacity table readings are unavailable.");
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      cleanup();
    }
    expect(loadThermalTable(null)).toBeNull();
    expect(loadThermalTable({ ...loadThermalTable(), private_context: "excluded" })).toBeNull();
  });

  it("shows all four values with the Table II headers and keeps Table I and its original count intact", () => {
    render(<Page />);
    const thermal = within(screen.getByRole("region", { name: "Mo borophosphide: heat-capacity analysis" }));
    const table = within(thermal.getByRole("table"));
    expect(table.getAllByRole("rowheader").map(cell => cell.textContent)).toEqual(["Mo5P1.1B1.9", "Mo5PB2"]);
    expect(table.getByRole("columnheader", { name: "Electronic specific-heat coefficient, γ, mJ/mol-at./K²" })).toBeInTheDocument();
    expect(table.getByRole("columnheader", { name: "Debye temperature, ΘD, K" })).toBeInTheDocument();
    expect(table.getAllByRole("cell").map(cell => cell.textContent)).toEqual(["3.16", "492", "3.07", "501"]);
    expect(table.getByText("mJ/mol-at./K²")).toBeInTheDocument();
    expect(table.queryByText(/1\.07/)).not.toBeInTheDocument();
    expect(screen.getByRole("table", { name: /^Table I original columns/ })).toHaveTextContent("Nominal Mo5P0.9B2.1");
    expect(screen.getByText("Pressure and Table I: 18 source expressions. Table II: 4 thermal readings.")).toBeInTheDocument();
    expect(thermal.getByText("4 source readings for 2 printed compositions, from Table II on PDF page 5.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mo Table II: thermal readings" })).toHaveAttribute("href", "#mo-thermal-table");
    expect(screen.getByRole("region", { name: "Mo Table II thermal readings, horizontally scrollable" })).toHaveAttribute("tabindex", "0");
  });

  it("folds technical locators, offers the original PDF page and portable metadata, and uses English UI", () => {
    render(<MaterialThermalTable snapshot={loadThermalTable()} />);
    expect(screen.getByText("Thermal field locators and source scope").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(/Value characters 180-184; unit characters 164-177/)).toBeInTheDocument();
    expect(screen.getByText(/Value characters 211-214; unit characters 204-205/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Table II in the paper ↗" })).toHaveAttribute("href", "https://arxiv.org/pdf/1603.02892#page=5");
    expect(screen.getByRole("link", { name: "Download thermal readings (JSON)" })).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "Download thermal SHA-256" })).toHaveAttribute("href", `${thermalTableDownloadPath()}.sha256`);
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|—/);
    expect(document.querySelectorAll("details[open]")).toHaveLength(0);
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/preview");
    expect(thermalTableDownloadPath()).toBe("/preview/research-pilots/materials-thermal-table-2026-10-05.json");
  });
});
