import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExternalStructureReferences } from "@/components/ExternalStructureReferences";
import { getMaterialStructureReferences } from "@/lib/api";
import type { ExternalStructureReference, MaterialStructureReferences } from "@/lib/api";

vi.mock("@/lib/api", () => ({ getMaterialStructureReferences: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
function row(extra: Partial<ExternalStructureReference> = {}): ExternalStructureReference {
  return { id: "4002152", url: "javascript:alert(1)", cif_url: "javascript:alert(1)", knowledge_origin: "Observed", declared_formula: "FeSe", cell_content_formula: "Fe0.996Se", composition_relation: "different_composition", match_level: "declared_composition_only_refined_differs", space_group: "P 4/n m m", hall_symbol: null, space_group_number: 129, lattice: { a: { value: 3.7696, unit: "Å", uncertainty: 0.00005, raw_value: "3.7696", raw_uncertainty: "0.00005", uncertainty_type: "standard_uncertainty", source_field: "a", uncertainty_source_field: "siga" } }, volume: null, measurement_conditions: { cell_temperature: null, diffraction_temperature: null, cell_pressure: null, diffraction_pressure: null }, method: "powder diffraction", method_status: "reported", source_revision: "svn:176432", revision_status: "reported", source_updated: null, source_snapshot_sha256: "a".repeat(64), source_status: null, provider_flags: "has coordinates", bibliography: { doi: null, doi_url: "javascript:alert(1)", title: null, journal: null, year: 2010 }, provider_has_coordinates: true, coordinate_model_validated: false, cif_validation_status: "external_file_not_validated", sample_identity_established: false, phase_identity_established: false, ...extra };
}
function report(status: MaterialStructureReferences["status"] = "available", references = [row()]): MaterialStructureReferences {
  return { version: "material-crystal-references/1.0.0", provider: "COD", formula: "FeSe", query_formula: "Fe Se", status, reason: null, references, retrieved_at: "2026-10-02T00:00:00Z", matches_total: references.length, inspected_entries: references.length, truncated: false, source_response_sha256: "b".repeat(64), scientific_acceptance: false, sample_identity_established: false, phase_identity_established: false, database_changed: false, scope: "external", reference_conditions: "unresolved", methodology_url: "https://wiki.crystallography.net/cod_mysql_schema/" };
}
function open() {
  const details = document.querySelector("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
}

describe("COD structure references", () => {
  it("loads only when expanded and preserves source differences, uncertainty and unvalidated files", async () => {
    vi.mocked(getMaterialStructureReferences).mockResolvedValue(report());
    render(<ExternalStructureReferences materialId="FeSe" />);
    expect(getMaterialStructureReferences).not.toHaveBeenCalled();
    open();
    expect(await screen.findByText("Declared and cell-content compositions differ")).toBeInTheDocument();
    expect(screen.getByText("a = 3.7696 ± 0.00005 Å")).toBeInTheDocument();
    expect(screen.getByText("Cell pressure: Not supplied")).toBeInTheDocument();
    expect(screen.getByText(/Missing pressure is not assumed to be ambient/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "External CIF file ↗" })).toHaveAttribute("href", "https://www.crystallography.net/cod/4002152.cif@176432");
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(document.body.textContent).not.toContain("0 GPa");
  });
  it("keeps missing measurement origin unresolved", async () => {
    vi.mocked(getMaterialStructureReferences).mockResolvedValue(report("available", [row({ knowledge_origin: "Unresolved", method: null, method_status: "unreported" })]));
    render(<ExternalStructureReferences materialId="FeSe" />); open();
    expect(await screen.findByText("Measurement origin unresolved")).toBeInTheDocument();
    expect(screen.queryByText("Experimental method reported")).not.toBeInTheDocument();
  });
  it("does not assert a composition difference when the declaration is unresolved", async () => {
    vi.mocked(getMaterialStructureReferences).mockResolvedValue(report("available", [row({ declared_formula: null, cell_content_formula: "FeSe", composition_relation: "unresolved", match_level: "cell_content_composition_only_declared_unresolved" })]));
    render(<ExternalStructureReferences materialId="FeSe" />); open();
    expect(await screen.findByText("Declared composition unresolved")).toBeInTheDocument();
    expect(screen.queryByText("Declared and cell-content compositions differ")).not.toBeInTheDocument();
    expect(screen.queryByText("Cell-content composition unresolved")).not.toBeInTheDocument();
  });
  it("distinguishes unavailable, no-match and unresolved composition", async () => {
    vi.mocked(getMaterialStructureReferences).mockResolvedValueOnce(report("unavailable", [])).mockResolvedValueOnce(report("no_match", [])).mockResolvedValueOnce(report("not_applicable", []));
    const view = render(<ExternalStructureReferences materialId="A" />); open();
    expect(await screen.findByText(/COD reference service unavailable/)).toBeInTheDocument();
    view.rerender(<ExternalStructureReferences materialId="B" />);
    expect(getMaterialStructureReferences).toHaveBeenCalledTimes(1);
    expect(document.querySelector("details")).not.toHaveAttribute("open");
    open();
    expect(await screen.findByText(/No exact-composition reference was returned/)).toBeInTheDocument();
    view.rerender(<ExternalStructureReferences materialId="C" />);
    open();
    expect(await screen.findByText(/Resolve the source composition/)).toBeInTheDocument();
  });
  it("ignores late material A results while showing material B", async () => {
    let resolveA!: (value: MaterialStructureReferences) => void;
    vi.mocked(getMaterialStructureReferences).mockImplementationOnce(() => new Promise(resolve => { resolveA = resolve; })).mockResolvedValueOnce(report("no_match", []));
    const view = render(<ExternalStructureReferences materialId="A" />); open();
    await waitFor(() => expect(getMaterialStructureReferences).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(getMaterialStructureReferences).mock.calls[0][1];
    view.rerender(<ExternalStructureReferences materialId="B" />);
    expect(signal?.aborted).toBe(true);
    expect(getMaterialStructureReferences).toHaveBeenCalledTimes(1);
    open();
    expect(await screen.findByText(/No exact-composition reference was returned/)).toBeInTheDocument();
    await act(async () => resolveA(report()));
    expect(screen.queryByRole("link", { name: "COD 4002152 ↗" })).not.toBeInTheDocument();
  });
  it("rejects a payload that presents external coordinates as validated", async () => {
    const unsafe = report();
    unsafe.references[0].coordinate_model_validated = true as unknown as false;
    vi.mocked(getMaterialStructureReferences).mockResolvedValue(unsafe);
    render(<ExternalStructureReferences materialId="A" />); open();
    expect(await screen.findByText(/COD reference service unavailable/)).toBeInTheDocument();
  });
});
