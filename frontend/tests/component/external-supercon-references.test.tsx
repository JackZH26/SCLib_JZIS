import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExternalSuperconReferences } from "@/components/ExternalSuperconReferences";
import { getMaterialSuperconReferences } from "@/lib/api";
import type { ExternalSuperconReference, MaterialSuperconReferences, SuperconReferenceQuantity } from "@/lib/api";
import nbSnapshot from "../fixtures/mdr-supercon-nb-240322.json";

vi.mock("@/lib/api", () => ({ getMaterialSuperconReferences: vi.fn() }));
const dataset = "https://doi.org/10.48505/nims.4487";
const absentCode = { raw_code: null, label: null, status: "not_supplied" as const };
const quantity = (field: string, label: string, raw: string, unit: string | null = "K"): SuperconReferenceQuantity => ({
  field, label, raw_value: raw, value: Number(raw), raw_unit: unit, unit,
  status: unit === null ? "unit_not_supplied" : "reported", meaning: "Synthetic source criterion", temperature_raw: null, direction: null,
  source_method_raw: null, method_label: null, method_status: "not_supplied",
});
const row = (fields: Partial<ExternalSuperconReference> = {}): ExternalSuperconReference => ({
  id: "mdr:240322:oxide_metallic:90106", source_row_id: "90106", source_table: "oxide_metallic", source_file: "20240322_MDR_OAndM.txt",
  source_sha256: "a".repeat(64), source_row_sha256: "b".repeat(64), source_line: 3, source_line_end: 3, url: dataset, formula: "Nb", raw_common_formula: null,
  bibliography: { reference_code: "synthetic-reference", title: "Synthetic source metadata fixture", journal: "Synthetic journal", publication_year_raw: "2024" },
  structure: { space_group: null, space_group_number: null, space_group_number_raw: null, common_name: null },
  sample_form: absentCode, structure_method: absentCode, tc_method: { raw_code: "M", label: null, status: "requires_review" },
  isotope_element: null, isotope_exchange_ratio: null, sample_identifier: null,
  raw_source_method_fields: { mhc1: null, mhc2: null, mcohere: null, mpenet: null, gapmeth: null, gamcom: null, mdebye: null },
  quantities: [quantity("tc", "Database recommended Tc", "9.2"), quantity("t1", "Zero resistance", "9"), quantity("t2", "Resistance midpoint", "9.1"), quantity("t3", "R = 100%", "9.3"), quantity("tcsus", "Susceptibility criterion", "9.15", null), quantity("tcn", "Lowest tested temperature", "0")],
  ...fields,
});
const report = (fields: Partial<MaterialSuperconReferences> = {}): MaterialSuperconReferences => ({
  version: "material-supercon-references/1.0.0", provider: "MDR SuperCon", formula: "Nb", query_formula: "Nb",
  status: "available", reason: null, references: [row()], matches_total: 1, omitted_rows: 0, truncated: false,
  dataset_version: "240322", dataset_doi: dataset, license: "CC BY 4.0", attribution: "Synthetic fixture; NIMS dataset attribution applies to the versioned source.",
  scope: "oxide_metallic_curated_source_rows_composition_references_not_selected_material_properties",
  snapshot_sha256: "c".repeat(64), resource_sha256: "d".repeat(64), source_publication_status: "not_checked",
  scientific_acceptance: false, sample_identity_established: false, phase_identity_established: false, ...fields,
});
const expand = () => fireEvent.click(screen.getByText("MDR SuperCon references"));

describe("MDR SuperCon references", () => {
  beforeEach(() => vi.resetAllMocks());
  it("loads only on expansion, keeps criteria separate and exposes unresolved units/codes", async () => {
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue(report());
    const view = render(<ExternalSuperconReferences materialId="mat:nb" />);
    expect(view.container.querySelector("details")).not.toHaveAttribute("open");
    expect(getMaterialSuperconReferences).not.toHaveBeenCalled();
    expand();
    await waitFor(() => expect(screen.getByText("1 of 1 source rows")).toBeInTheDocument());
    for (const label of ["Database recommended Tc", "Zero resistance", "Resistance midpoint", "R = 100%", "Susceptibility criterion", "Lowest tested temperature"]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("9.15 (unit not supplied)")).toBeInTheDocument();
    expect(screen.getByText(/Lowest tested temperature for a non-superconducting report; this is not Tc/)).toBeInTheDocument();
    expect(screen.getByText("Unresolved code")).toBeInTheDocument();
    expect(screen.getByText("(M)")).toBeInTheDocument();
    expect(screen.getByText(/Raw row SHA-256/)).not.toBeVisible();
    expect(screen.getByRole("table").parentElement).toHaveClass("overflow-x-auto");
  });
  it("shows maximum applied pressure separately and never treats it as a Tc condition", async () => {
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue(report({ references: [row({ quantities: [quantity("tc", "Database recommended Tc", "9.2"), quantity("pmax", "Maximum applied pressure", "8", null)] })] }));
    render(<ExternalSuperconReferences materialId="mat:nb" />);
    expand();
    await waitFor(() => expect(screen.getByText("1 of 1 source rows")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Inspect source row"));
    expect(screen.getByText("8 (unit not supplied)")).toBeInTheDocument();
    expect(screen.getByText(/pressure at the selected Tc is not established/)).toBeInTheDocument();
    expect(screen.queryByText(/Tc pressure: 8|Ambient pressure/)).not.toBeInTheDocument();
  });
  it("states snapshot/table scope for successful queries without matches", async () => {
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue(report({ status: "no_match", references: [], matches_total: 0 }));
    render(<ExternalSuperconReferences materialId="mat:unmatched" />);
    expand();
    await waitFor(() => expect(screen.getByText("No match in this snapshot")).toBeInTheDocument());
    expect(screen.getByText(/oxide and metallic table of version 240322/)).toBeInTheDocument();
    expect(screen.getByText(/Organic data and other versions are outside this view/)).toBeInTheDocument();
    expect(screen.queryByText(/Source coverage cannot be determined/)).not.toBeInTheDocument();
  });
  it("keeps an unavailable snapshot distinct from no match and unresolved composition", async () => {
    vi.mocked(getMaterialSuperconReferences).mockRejectedValueOnce(new Error("Unavailable"));
    const view = render(<ExternalSuperconReferences materialId="A" />);
    expand();
    await waitFor(() => expect(screen.getByText(/Source coverage cannot be determined/)).toBeInTheDocument());
    vi.mocked(getMaterialSuperconReferences).mockResolvedValueOnce(report({ status: "not_applicable", references: [], matches_total: null, query_formula: null }));
    view.rerender(<ExternalSuperconReferences materialId="B" />);
    expand();
    await waitFor(() => expect(screen.getByText("Composition review needed")).toBeInTheDocument());
    expect(screen.getByText(/exact source composition, isotope or interface/)).toBeInTheDocument();
  });
  it.each(["scientific_acceptance", "sample_identity_established", "phase_identity_established"] as const)("rejects a promoted %s contract", async field => {
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue({ ...report(), [field]: true } as unknown as MaterialSuperconReferences);
    render(<ExternalSuperconReferences materialId="mat:nb" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("90106")).not.toBeInTheDocument();
  });
  it("rejects unsafe source identities and malformed unit types", async () => {
    vi.mocked(getMaterialSuperconReferences).mockResolvedValueOnce(report({ references: [row({ url: "javascript:alert(1)" })] }));
    const view = render(<ExternalSuperconReferences materialId="A" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    vi.mocked(getMaterialSuperconReferences).mockResolvedValueOnce(report({ references: [row({ quantities: [{ ...quantity("tc", "Tc", "9"), unit: { fake: "K" } as unknown as string }] })] }));
    view.rerender(<ExternalSuperconReferences materialId="B" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("9 K")).not.toBeInTheDocument();
  });
  it("rejects stale row IDs and reported raw-unit aliases that do not resolve", async () => {
    vi.mocked(getMaterialSuperconReferences).mockResolvedValueOnce(report({ references: [row({ id: "oxide_metallic:90106" })] }));
    const view = render(<ExternalSuperconReferences materialId="A" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    vi.mocked(getMaterialSuperconReferences).mockResolvedValueOnce(report({ references: [row({ quantities: [{ ...quantity("tc", "Tc", "9"), raw_unit: "invalid-K" }] })] }));
    view.rerender(<ExternalSuperconReferences materialId="B" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("9 K")).not.toBeInTheDocument();
  });
  it("accepts the first data line, normalizes supported unit labels and preserves derivation context", async () => {
    const derived = { ...quantity("hc2t", "Hc2 at supplied temperature", "2.1", "T"), direction: "H_parallel_ab", temperature_raw: "4.2", source_method_raw: "resistivity,WHH", method_label: "resistivity,WHH", method_status: "reported" as const };
    const lattice = { ...quantity("lata", "Lattice a", "3.08", "Å"), raw_unit: "A" };
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue(report({ references: [row({ source_line: 3, source_line_end: 4, quantities: [lattice, derived] })] }));
    render(<ExternalSuperconReferences materialId="A" />);
    expand();
    await waitFor(() => expect(screen.getByText("1 of 1 source rows")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Inspect source row"));
    expect(screen.getByText("3.08 Å")).toBeInTheDocument();
    expect(screen.getByText("Source unit (raw): A")).toBeInTheDocument();
    expect(screen.getByText("Direction: H parallel to ab")).toBeInTheDocument();
    expect(screen.getByText(/Source method: resistivity,WHH/)).toBeInTheDocument();
    expect(screen.getByText(/Temperature condition \(raw\): 4.2; unit not supplied/)).toBeInTheDocument();
    expect(screen.queryByText(/4.2 K|Observed/)).not.toBeInTheDocument();
  });
  it("aborts an in-flight old material and ignores its late response", async () => {
    let resolveA: (value: MaterialSuperconReferences) => void = () => {};
    vi.mocked(getMaterialSuperconReferences).mockImplementationOnce(() => new Promise(resolve => { resolveA = resolve; })).mockRejectedValueOnce(new Error("B unavailable"));
    const view = render(<ExternalSuperconReferences materialId="A" />);
    expand();
    await waitFor(() => expect(getMaterialSuperconReferences).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(getMaterialSuperconReferences).mock.calls[0][1];
    view.rerender(<ExternalSuperconReferences materialId="B" />);
    expect(signal?.aborted).toBe(true);
    expect(view.container.querySelector("details")).not.toHaveAttribute("open");
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    await act(async () => resolveA(report()));
    expect(screen.queryByText("90106")).not.toBeInTheDocument();
  });
  it("renders the actual licensed Nb snapshot without hiding unknown units or source context", async () => {
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue(nbSnapshot as MaterialSuperconReferences);
    render(<ExternalSuperconReferences materialId="mat:nb" />);
    expand();
    await waitFor(() => expect(screen.getByText("19 of 19 source rows")).toBeInTheDocument());
    expect(screen.getAllByText("Tc (recommended for source sample)")).toHaveLength(19);
    expect(screen.getAllByText("Tc (midpoint)")).toHaveLength(18);
    expect(screen.getByText("Tc (R = 0)")).toBeInTheDocument();
    for (const summary of screen.getAllByText("Inspect source row")) fireEvent.click(summary);
    expect(screen.getAllByText(/unit not supplied/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unit unresolved").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Source method:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Source year:/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Scientific approval|ML ready|Observed/)).not.toBeInTheDocument();
  });
  it("reports bounded omissions and keeps bibliography/hash provenance folded", async () => {
    const rows = Array.from({ length: 20 }, (_, index) => row({ id: `mdr:240322:oxide_metallic:${90106 + index}`, source_row_id: String(90106 + index) }));
    vi.mocked(getMaterialSuperconReferences).mockResolvedValue(report({ references: rows, matches_total: 24, omitted_rows: 4, truncated: true }));
    render(<ExternalSuperconReferences materialId="mat:nb" />);
    expand();
    await waitFor(() => expect(screen.getByText("20 of 24 source rows")).toBeInTheDocument());
    expect(screen.getByText(/4 additional matched rows omitted/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Dataset and attribution"));
    expect(screen.getByRole("link", { name: "CC BY 4.0 ↗" })).toHaveAttribute("href", "https://creativecommons.org/licenses/by/4.0/");
    expect(screen.getByText(/Current publication status has not been checked/)).toBeInTheDocument();
  });
});
