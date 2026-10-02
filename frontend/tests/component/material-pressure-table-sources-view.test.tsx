import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Page from "@/app/materials/source-observations/pressure-and-tables/page";
import FirstPage from "@/app/materials/source-observations/page";
import FollowupPage from "@/app/materials/source-observations/followup/page";
import { MaterialPressureTableSources } from "@/components/MaterialPressureTableSources";
import { loadPressureTableBatch, loadPressureTableSubject } from "@/lib/material-pressure-table-sources";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("Pressure and table researcher view", () => {
  it("shows distinct BiTc and caption scopes with the actual unresolved pressure-label conflict", () => {
    render(<Page />);
    const bi = within(screen.getByRole("region", { name: "BiTeCl: separate pressure windows" }));
    expect(bi.getByText("7 K")).toBeInTheDocument(); expect(bi.getByText("15 GPa")).toBeInTheDocument();
    expect(bi.getByText(/Tc criterion not supplied in this source window/)).toBeInTheDocument();
    expect(bi.getByText("Caption pressure 24.1 GPa")).toBeInTheDocument();
    expect(bi.getByText("Caption pressure 50.8 GPa")).toBeInTheDocument();
    expect(bi.getAllByText("90% resistivity transition")).toHaveLength(2);
    expect(bi.getByRole("note", { name: "Unresolved Figure 2 pressure-label conflict" })).toHaveTextContent("50.1 GPa");
    expect(bi.getByText(/criterion is not assigned to the 7 K report at 15 GPa/)).toBeInTheDocument();
    expect(screen.getByText("18 field expressions from 2 papers; 3 source subjects")).toBeInTheDocument();
  });
  it("renders both original table columns and preserves uncertain values, units and missing conditions", () => {
    render(<Page />);
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Nominal Mo5P0.9B2.1")).toBeInTheDocument(); expect(table.getByText("Nominal Mo5PB2")).toBeInTheDocument();
    expect(table.getAllByText("Refined Mo5P1.07(4)B1.93(4)")).toHaveLength(2);
    ["8.7(1) K", "8.9(1) K", "8.8(2) K", "8.7(2) K", "5.9726(1) A\u030a", "5.97303(7) A\u030a", "11.074(3) A\u030a", "11.076(1) A\u030a"].forEach(value => expect(table.getByText(value)).toBeInTheDocument());
    expect(table.getAllByText("Tc pressure not supplied")).toHaveLength(2);
    expect(screen.getByText(/Room-temperature XRD conditions are not Tc conditions/)).toHaveTextContent("missing Tc pressure is not treated as ambient");
    expect(table.queryByText("9.2(1) K")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Mo Table I comparison, horizontally scrollable" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("region", { name: "Mo Table I comparison, horizontally scrollable" })).toHaveClass("overflow-x-auto", "max-w-full");
  });
  it("folds provenance, exposes all 18 exact locators, and makes version ambiguity explicit", () => {
    render(<Page />);
    expect(screen.getAllByText("Field locator")).toHaveLength(18);
    expect(document.querySelectorAll('details[open]')).toHaveLength(0);
    expect(screen.getAllByText("Source snapshot and publication version")).toHaveLength(2);
    expect(screen.getByText(/PDF internal date: July 7, 2018/)).toHaveTextContent("Official arXiv v1 submission: 2015-01-25");
    const field = document.getElementById("source-record-mo-01")!;
    expect(within(field).getByRole("link", { name: "Open field’s PDF page ↗" })).toHaveAttribute("href", "https://arxiv.org/pdf/1603.02892#page=3");
    expect(within(field).getByText(/original column 2, row 10/)).toBeInTheDocument();
    expect(within(field).getByText(/Captured characters 10951-10957/)).toBeInTheDocument();
    expect(within(field).getByText(/No bare float or interpreted uncertainty is assigned/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]|—/);
  });
  it("links the new route from both existing source pages and offers a static whole-batch export", () => {
    render(<Page />);
    expect(screen.getByRole("link", { name: "Download pressure and table metadata (JSON)" })).toHaveAttribute("href", "/research-pilots/materials-pressure-table-sources-2026-10-02.json");
    cleanup(); render(<FirstPage />);
    expect(screen.getByRole("link", { name: "Pressure and table records" })).toHaveAttribute("href", "/materials/source-observations/pressure-and-tables");
    cleanup(); render(<FollowupPage />);
    expect(screen.getByRole("link", { name: "Pressure and table records" })).toHaveAttribute("href", "/materials/source-observations/pressure-and-tables");
  });
  it("renders exact six-expression JSON inside native disclosures without downloads or blob actions", () => {
    render(<Page />);
    const links = [
      ["View BiTeCl source subject (JSON)", "/research-pilots/materials-pressure-table-bitecl-2026-10-02.json"],
      ["View original column 2 (JSON)", "/research-pilots/materials-pressure-table-mo-column-2-2026-10-02.json"],
      ["View original column 3 (JSON)", "/research-pilots/materials-pressure-table-mo-column-3-2026-10-02.json"],
    ];
    const subjects = ["bitecl", "mo_nominal_column_2", "mo_nominal_column_3"];
    for (const [index, [name, href]] of links.entries()) {
      const disclosure = screen.getByText(name).closest("details")!;
      expect(disclosure).not.toHaveAttribute("open");
      const pre = disclosure.querySelector("pre")!;
      const metadata = JSON.parse(pre.textContent!);
      expect(metadata).toEqual(loadPressureTableSubject(subjects[index]));
      expect(metadata.entries).toHaveLength(6);
      expect(metadata.scientific_acceptance).toBe(false);
      expect(metadata.canonical_promotions).toBe(0);
      expect(pre).toHaveAttribute("tabindex", "0");
      expect(pre).toHaveClass("max-w-full", "overflow-auto", "whitespace-pre-wrap", "break-all");
      const link = within(disclosure).getByRole("link", { name: "Static JSON resource" });
      expect(link).toHaveAttribute("href", href); expect(link).not.toHaveAttribute("download");
      expect(link).not.toHaveAttribute("target"); expect(link).not.toHaveAttribute("onclick");
    }
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(document.querySelectorAll("a[download]")).toHaveLength(2);
  });
  it("shows an English unavailable state for an absent metadata batch", () => {
    render(<MaterialPressureTableSources batch={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("Captured pressure and table records are unavailable.");
    expect(loadPressureTableBatch()).not.toBeNull();
  });
});
