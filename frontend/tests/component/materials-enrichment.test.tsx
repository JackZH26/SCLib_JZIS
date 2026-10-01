import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExternalMaterialReferences } from "@/components/ExternalMaterialReferences";
import { MaterialEnrichment } from "@/components/MaterialEnrichment";
import { getMaterialExternalReferences, getMaterialEnrichment } from "@/lib/api";

vi.mock("@/lib/api", () => ({ getMaterialExternalReferences: vi.fn(), getMaterialEnrichment: vi.fn() }));

describe("Materials recovery and external references", () => {
  beforeEach(() => vi.resetAllMocks());
  it("displays computed polymorphs independently and never equates metallicity with superconductivity", async () => {
    vi.mocked(getMaterialExternalReferences).mockResolvedValue({ version: "material-external-references/1.0.0", scientific_acceptance: false, sample_identity_established: false, status: "available", candidates: ["mp-aaaaaciu", "mp-2"].map(id => ({ id, url: `https://next-gen.materialsproject.org/materials/${id}`, sample_identity_established: false, phase_identity_established: false, space_group: "Fm-3m", crystal_system: "Cubic", band_gap_ev: 0, density_g_cm3: 8.3, energy_above_hull_ev_atom: 0.01, lattice: { a: 4.4 }, origins: [], source_snapshot_sha256: "1".repeat(64), functional: "Unresolved" })), reference_conditions: "0 K reference", methodology_url: "https://docs.materialsproject.org", retrieved_at: "2026-10-01T00:00:00Z", truncated: false } as Awaited<ReturnType<typeof getMaterialExternalReferences>>);
    render(<ExternalMaterialReferences materialId="mat:nbn" />);
    await waitFor(() => expect(screen.getByRole("link", { name: "mp-aaaaaciu ↗" })).toBeInTheDocument());
    expect(screen.getAllByText("Computed · composition match")).toHaveLength(2);
    expect(screen.getByText(/A zero band gap does not establish superconductivity/)).toBeInTheDocument();
    expect(screen.queryByText(/Observed/)).not.toBeInTheDocument();
  });
  it("shows an unavailable request separately from a provider no-match", async () => {
    vi.mocked(getMaterialExternalReferences).mockRejectedValue(new Error("Transport failed"));
    render(<ExternalMaterialReferences materialId="mat:nbn" />);
    await waitFor(() => expect(screen.getByText(/Reference service unavailable/)).toBeInTheDocument());
    expect(screen.queryByText(/No fixed-composition match/)).not.toBeInTheDocument();
  });
  it("never carries material A references into B during navigation or a failed request", async () => {
    const a = { version: "material-external-references/1.0.0", scientific_acceptance: false, sample_identity_established: false, status: "no_match", candidates: [] } as Awaited<ReturnType<typeof getMaterialExternalReferences>>;
    let rejectB: (reason: Error) => void = () => {};
    vi.mocked(getMaterialExternalReferences).mockResolvedValueOnce(a).mockImplementationOnce(() => new Promise((_, reject) => { rejectB = reject; }));
    const view = render(<ExternalMaterialReferences materialId="A" />);
    await waitFor(() => expect(screen.getByText(/No fixed-composition match/)).toBeInTheDocument());
    view.rerender(<ExternalMaterialReferences materialId="B" />);
    expect(screen.queryByText(/No fixed-composition match/)).not.toBeInTheDocument();
    expect(screen.getByText(/Loading calculated reference/)).toBeInTheDocument();
    await act(async () => rejectB(new Error("B unavailable")));
    expect(screen.getByText(/Reference service unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/No fixed-composition match/)).not.toBeInTheDocument();
  });
  it("ignores a late A recovery response after navigation to B", async () => {
    let resolveA: (value: Awaited<ReturnType<typeof getMaterialEnrichment>>) => void = () => {};
    vi.mocked(getMaterialEnrichment).mockImplementationOnce(() => new Promise(resolve => { resolveA = resolve; })).mockRejectedValueOnce(new Error("B unavailable"));
    const view = render(<MaterialEnrichment materialId="A" />);
    view.rerender(<MaterialEnrichment materialId="B" />);
    await waitFor(() => expect(screen.getByText(/Source recovery is unavailable/)).toBeInTheDocument());
    await act(async () => resolveA({ version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false, candidates: [], counts: {}, coverage: [{ material_id: "A", formula: "A", fields: [] }] }));
    expect(screen.getByText(/Source recovery is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/fields have retained extractions/)).not.toBeInTheDocument();
  });
  it("explains partial recovery coverage and preserves candidate status", async () => {
    vi.mocked(getMaterialEnrichment).mockResolvedValue({ version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false, counts: {}, candidates: [{ candidate_id: "candidate:1", field: "space_group", value: "Cmmm", raw_value: "Cmmm", source: { paper_id: "paper:1", kind: "legacy_unknown", content_sha256: "1".repeat(64), source_revision: "retained-capture", locator: { section: "Results" } }, reason_codes: ["publication_revision_unverified"] }], coverage: [{ material_id: "mat:ysch10", formula: "YScH10", fields: [{ field: "space_group", status: "pending_review", retained_present: false, candidate_count: 1, reason_codes: [], routes: ["source_fulltext_and_supplement"] }, { field: "pressure_gpa", status: "not_found_in_checked_sources", retained_present: false, candidate_count: 0, reason_codes: [], routes: [] }] }] });
    render(<MaterialEnrichment materialId="mat:ysch10" />);
    await waitFor(() => expect(screen.getByText(/2 need further source work/)).toBeInTheDocument());
    fireEvent.click(screen.getByText("Inspect field coverage and recovery routes"));
    expect(screen.getByText(/not every full paper or supplement/)).toBeInTheDocument();
    expect(screen.getByText("No candidate in checked chunks")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Source recovery candidates (1)"));
    expect(screen.getByText("Review needed")).toBeInTheDocument();
    expect(screen.queryByText(/Source verified|Scientific approval|Reported false/)).not.toBeInTheDocument();
  });
});
