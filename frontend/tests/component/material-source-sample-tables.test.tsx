import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Page from "@/app/materials/source-observations/fe-te-se-samples/page";
import { MaterialSourceSampleTables } from "@/components/MaterialSourceSampleTables";
import { loadSourceSampleTables, sourceSampleTableHref, sourceSampleTablesDownloadPath, sourceSampleTablesSha256 } from "@/lib/material-source-sample-tables";
import { materialStudyReading } from "@/lib/material-study-reading";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("Source sample tables retain cell, sample and fit roles", () => {
  it("pins the download and preserves printed coefficients without canonical values or private source text", () => {
    const name = "materials-source-sample-tables-2026-10-04.json";
    const raw = readFileSync(`public/research-pilots/${name}`);
    expect(createHash("sha256").update(raw).digest("hex")).toBe(sourceSampleTablesSha256);
    expect(readFileSync(`public/research-pilots/${name}.sha256`, "utf8")).toBe(`${sourceSampleTablesSha256}  ${name}\n`);
    const data = loadSourceSampleTables()!;
    expect(data.authority.canonical_updates).toBe(0);
    expect(data.authority.material_sample_state_and_selected_result_association).toBe("unestablished");
    expect(data.counts.original_table_cells).toBe(54);
    expect(data.counts.displayed_table_cells).toBe(60);
    expect(data.counts.independent_experiment_count_established).toBe(false);
    for (const table of [data.composition_table, data.fit_parameter_table]) {
      expect(table.rows).toHaveLength(6);
      for (const row of table.rows) for (const cell of Object.values(row.cells)) expect(cell.normalized_value).toBeNull();
    }
    expect(raw.toString()).not.toMatch(/\/private\/tmp|\/Users\/|"full_text"|"selected_Tc_K"|"material_id"/);
  });

  it("keeps nominal preparation labels and excess Fe separate from measured Se coefficients", () => {
    render(<Page />);
    const table = within(screen.getByRole("table", { name: /Table I composition rows/ }));
    expect(table.getAllByRole("row")).toHaveLength(7);
    const row = within(table.getByRole("row", { name: "0.30 1.07 0.80 0.20" }));
    expect(row.getByRole("rowheader")).toHaveTextContent("0.30");
    expect(row.getAllByRole("cell").map(cell => cell.textContent)).toEqual(["1.07", "0.80", "0.20"]);
    expect(table.getByRole("row", { name: "0.10 1.00 0.95 0.05" })).toBeInTheDocument();
    expect(table.getByRole("row", { name: "0.40(I) 1.12 0.72 0.28" })).toBeInTheDocument();
    expect(table.queryByRole("row", { name: /^0.48 / })).not.toBeInTheDocument();
  });

  it("distinguishes the printed blank from an adjacent dash and keeps negative fit values and units", () => {
    render(<Page />);
    const table = within(screen.getByRole("table", { name: /Susceptibility-fit parameters/ }));
    const blank = within(table.getByRole("row", { name: /0.40\(I\).*Blank in source/ }));
    expect(blank.getAllByRole("cell").map(cell => cell.textContent)).toEqual(["-", "-", "Blank in source", "0.12", "-24"]);
    const dash = within(table.getByRole("row", { name: /0.40\(II\)/ }));
    expect(dash.getAllByRole("cell").map(cell => cell.textContent)).toEqual(["-", "-", "-", "0.05", "-23"]);
    expect(table.getByRole("row", { name: "0 2.24 -319 4.2 - -" })).toBeInTheDocument();
    expect(table.getByRole("columnheader", { name: "C (emu K/mol)" })).toBeInTheDocument();
    expect(table.getByRole("columnheader", { name: "μeff (μB)" })).toBeInTheDocument();
    expect(screen.getByText(/100–300 K:/)).toHaveTextContent("measured x = 0 and 0.05");
    expect(screen.getByText(/20–50 K:/)).toHaveTextContent("tentatively attribute this term to Fe(II)");
    expect(screen.getByText(/θ is a Weiss fit temperature/)).toHaveTextContent("do not establish ordering temperatures or ordered moments");
  });

  it("provides named focusable tables and closed metadata with real, versioned source and download links", () => {
    render(<Page />);
    for (const name of ["FeTeSe nominal and EDX composition", "FeTeSe Curie–Weiss fit parameters"]) {
      const region = screen.getByRole("region", { name: name + ", horizontally scrollable" });
      region.focus(); expect(region).toHaveFocus();
    }
    const fold = screen.getByText("Source, scope and downloads").closest("details")!;
    expect(fold).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Source, scope and downloads"));
    expect(screen.getByRole("link", { name: "Download sample tables (JSON)" })).toHaveAttribute("href", sourceSampleTablesDownloadPath);
    expect(JSON.parse(screen.getByLabelText("Source sample table metadata JSON").textContent!)).toEqual(loadSourceSampleTables());
    const metadata = screen.getByRole("region", { name: "Source sample table metadata JSON" });
    metadata.focus(); expect(metadata).toHaveFocus();
    expect(screen.getByRole("link", { name: /Read Table I in arXiv/ })).toHaveAttribute("href", "https://arxiv.org/pdf/0911.4758v1#page=4");
    expect(screen.getAllByRole("link", { name: "Read this passage on PDF page 4 ↗" })).toHaveLength(3);
    for (const link of screen.getAllByRole("link", { name: "Read this passage on PDF page 4 ↗" })) expect(link).toHaveAttribute("href", "https://arxiv.org/pdf/0911.4758v1#page=4");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
    expect(sourceSampleTableHref(0)).toBeNull(); expect(sourceSampleTableHref(6)).toBeNull();
  });

  it("rejects changed blank semantics, source attribution, values, units, normalized quantities and approval flags", () => {
    const edits = [
      (data: any) => { data.fit_parameter_table.rows[4].cells.mu_eff.raw_value = "-"; },
      (data: any) => { data.composition_table.rows[3].cells.EDX_Fe.raw_value = "1.00"; },
      (data: any) => { data.composition_table.rows[0].cells.EDX_Fe.normalized_value = 1.12; },
      (data: any) => { data.fit_parameter_table.source_printed_units.C = "SI"; },
      (data: any) => { data.source.edition = "0911.4758v2"; },
      (data: any) => { data.locators[0].char_end += 1; },
      (data: any) => { data.authority.scientific_acceptance = true; },
      (data: any) => { data.authority.material_sample_state_and_selected_result_association = "reviewed"; },
      (data: any) => { data.full_text = "unreviewed text"; },
    ];
    for (const edit of edits) { const data = loadSourceSampleTables()!; edit(data); expect(loadSourceSampleTables(data)).toBeNull(); }
    render(<MaterialSourceSampleTables data={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("captured sample tables are unavailable");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("adds a companion for the existing exact Fe reading and guarded table links for four frozen same-paper records", () => {
    const source = { paper_id: "arxiv:0911.4758" };
    const tuples = [
      ["mat:fe1te0.55se0.45", "legacy-result:8f2a87e3d987f3548691ab68cda67db0ac43801e9b981b2c48c52dc3cf85816a"],
      ["mat:fe1te0.80se0.20", "legacy-result:6ad4ff3c6914d1dc724b1905868d086442177d551813b8d2232e3c6a9bcf3e61"],
      ["mat:fe1te0.88se0.12", "legacy-result:2392dd3b85dc1ce9823448a57614d10e8c894d2e884314e480fc1f9b194e9287"],
      ["mat:fe1te0.95se0.05", "legacy-result:20c35e5c252ac226b147a85e6b385f338658e77748e454680376a2cddcb81a93"],
    ];
    for (const [material, result_id] of tuples) {
      const selected = { result_id, source };
      expect(materialStudyReading(material, selected)?.href).toBe("/materials/source-observations/fe-te-se-samples");
      expect(materialStudyReading(material, { ...selected, result_id: "legacy-result:other" })).toBeNull();
      expect(materialStudyReading(material, { ...selected, source: { paper_id: "arxiv:0911.4758v2" } })).toBeNull();
      expect(materialStudyReading("mat:other", selected)).toBeNull();
    }
    const selected = { result_id: "legacy-result:17c34bd20d1efd2f3d2cae898af035089b6e0e53a04489f96bfd6c10c000478a", source };
    const reading = materialStudyReading("mat:fe1te0.52se0.48", selected)!;
    expect(reading.href).toContain("#paper-context-fete");
    expect(reading.companion?.href).toBe("/materials/source-observations/fe-te-se-samples");
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib-preview");
    expect(materialStudyReading("mat:fe1te0.52se0.48", selected)?.companion?.href).toBe("/sclib-preview/materials/source-observations/fe-te-se-samples");
  });
});
