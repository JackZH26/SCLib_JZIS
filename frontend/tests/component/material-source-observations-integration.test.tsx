import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialEnrichment } from "@/components/MaterialEnrichment";
import { ExternalStructureReferences } from "@/components/ExternalStructureReferences";
import { getMaterialEnrichment, getMaterialStructureReferences, type MaterialEnrichmentReport, type MaterialStructureReferences } from "@/lib/api";

vi.mock("@/lib/api", () => ({ getMaterialEnrichment: vi.fn(), getMaterialStructureReferences: vi.fn() }));
const pt = "mat:bafe1.906pt0.094as2";
const seed = JSON.parse(readFileSync(resolve(process.cwd(), "../api/services/resources/material_enrichment_seed.json"), "utf8"));
function recovery(materialId: string): MaterialEnrichmentReport {
  return { version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false,
    candidates: seed.reports.flatMap((report: { candidates: Array<Record<string, unknown>> }) => report.candidates).filter((candidate: Record<string, unknown>) => candidate.material_id === materialId),
    primary_source_seed: { status: "available", seed_sha256: seed.seed_sha256 }, counts: {},
    coverage: [{ material_id: materialId, formula: materialId, fields: [] }],
  } as MaterialEnrichmentReport;
}
function crystal(sourceRevision: string): MaterialStructureReferences {
  return { version: "material-crystal-references/1.0.0", provider: "COD", status: "available", scientific_acceptance: false, database_changed: false,
    sample_identity_established: false, phase_identity_established: false, retrieved_at: null, inspected_entries: 1, truncated: false,
    references: [{ id: "1510641", source_revision: sourceRevision, declared_formula: "B2 Cr", cell_content_formula: "B2 Cr", composition_relation: "same_composition",
      knowledge_origin: "Observed", sample_identity_established: false, phase_identity_established: false, coordinate_model_validated: false,
      cif_validation_status: "external_file_not_validated", lattice: {}, measurement_conditions: {}, bibliography: { year: 1954 }, method: "X-ray diffraction" }],
  } as unknown as MaterialStructureReferences;
}
describe("Source observations within current material requests", () => {
  beforeEach(() => vi.resetAllMocks());
  it("shows the source additions after a matching actual seed and removes them immediately on material change", async () => {
    vi.mocked(getMaterialEnrichment).mockImplementation(async materialId => recovery(materialId));
    const view = render(<MaterialEnrichment materialId={pt} />);
    const summary = await screen.findByText("Additional source observations (5)");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("-2.8 T/K")).toBeInTheDocument();
    expect(screen.getByText("≈ 45 T")).toBeInTheDocument();
    expect(screen.getByText("≈ 65 T")).toBeInTheDocument();
    view.rerender(<MaterialEnrichment materialId="mat:nb" />);
    expect(screen.queryByText("Additional source observations (5)")).not.toBeInTheDocument();
    await waitFor(() => expect(getMaterialEnrichment).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("≈ 45 T")).not.toBeInTheDocument();
  });
  it("loads CIF additions only inside an opened lookup that returns the captured revision", async () => {
    vi.mocked(getMaterialStructureReferences).mockResolvedValueOnce(crystal("svn:176435")).mockResolvedValueOnce(crystal("svn:176436"));
    const view = render(<ExternalStructureReferences materialId="mat:crb2" />);
    expect(getMaterialStructureReferences).not.toHaveBeenCalled();
    const first = document.querySelector("details")!;
    first.open = true; fireEvent(first, new Event("toggle"));
    const summary = await screen.findByText("Additional source observations (4)");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("2 listed asymmetric-unit sites")).toBeInTheDocument();
    view.rerender(<ExternalStructureReferences materialId="mat:another" />);
    expect(screen.queryByText("Additional source observations (4)")).not.toBeInTheDocument();
    expect(getMaterialStructureReferences).toHaveBeenCalledTimes(1);
    const second = document.querySelector("details")!;
    second.open = true; fireEvent(second, new Event("toggle"));
    await screen.findByText("Source year: 1954");
    expect(screen.queryByText("Additional source observations (4)")).not.toBeInTheDocument();
  });
});
