import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExternalCalculationReferences } from "@/components/ExternalCalculationReferences";
import { getMaterialCalculationReferences } from "@/lib/api";
import type { ExternalCalculationReference, MaterialCalculationReferences } from "@/lib/api";
import { NOMAD_GAP_SCHEMA } from "@/lib/nomad-electronic-references";

vi.mock("@/lib/api", () => ({ getMaterialCalculationReferences: vi.fn() }));

const row = (id: string, fields: Partial<ExternalCalculationReference> = {}): ExternalCalculationReference => ({
  id, url: `https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/${id}`, archive_url: `https://nomad-lab.eu/prod/v1/api/v1/entries/${id}/archive`,
  formula: "B2Mg", material_id: `structure_${id}`, upload_id: "upload_1", method: "DFT", program: "VASP", parser: "parsers/vasp", structural_type: "bulk",
  space_group: "P6/mmm", space_group_number: 191, crystal_system: "hexagonal", source_references: [{ provider: "Materials Project", url: "https://next-gen.materialsproject.org/materials/mp-1580" }],
  source_snapshot_sha256: "a".repeat(64), knowledge_origin: "Computed", method_status: "reported", conditions_status: "not_inspected", match_level: "fixed_composition_only", sample_identity_established: false, phase_identity_established: false,
  xc_functional_names: null, xc_functional_type: null, spin_polarized: null, dft_metadata_status: "not_supplied", dft_metadata_scope: "reported_underlying_dft_metadata_not_complete_method",
  ...fields,
});
const report = (fields: Partial<MaterialCalculationReferences> = {}): MaterialCalculationReferences => ({
  version: "material-calculation-references/1.0.0", provider: "NOMAD", formula: "MgB2", query_formula: "B2Mg", status: "available", reason: null,
  references: [row("task_a"), row("task_b", { method: null, program: "LOBSTER", method_status: "unresolved", knowledge_origin: "Unresolved", space_group: "Fm-3m" })],
  retrieved_at: "2026-10-02T00:00:00Z", matches_total: 89, inspected_entries: 21, truncated: true,
  scientific_acceptance: false, sample_identity_established: false, phase_identity_established: false,
  scope: "computed_task_composition_references_not_selected_material_properties", reference_conditions: "Not inspected", methodology_url: "https://docs.nomad-lab.eu/1.4.3/howto/manage/program/api.html", ...fields,
});
const expand = () => fireEvent.click(screen.getByText("NOMAD calculation references"));

describe("NOMAD calculation references", () => {
  beforeEach(() => vi.resetAllMocks());
  it("shows computed electronic gaps in eV with source joules and separate DOS spin channels", async () => {
    vi.mocked(getMaterialCalculationReferences).mockResolvedValue(report({ references: [row("dos_task", { electronic: {
      version: "nomad-electronic-references/1.0.0", scope: "task_electronic_band_gaps_not_superconducting_gaps", unit_schema_url: NOMAD_GAP_SCHEMA,
      status: "reported", band_gaps: [
        { source_kind: "dos_electronic", group_index: 0, spin_channel_index: 0, spin_polarized: true, gap_type: null, value_j: 0, value_ev: 0 },
        { source_kind: "dos_electronic", group_index: 0, spin_channel_index: 1, spin_polarized: true, gap_type: null, value_j: 3.204353268e-19, value_ev: 2 },
      ],
    } })] }));
    render(<ExternalCalculationReferences materialId="mat:mgb2" />);
    expand();
    await waitFor(() => expect(screen.getByText("Electronic band gap")).toBeInTheDocument());
    fireEvent.click(screen.getByText("DOS · 2 readings"));
    expect(screen.getByText("DOS · group 0 · channel 0")).toBeVisible();
    expect(screen.getByText("DOS · group 0 · channel 1")).toBeVisible();
    expect(screen.getByText("2 eV")).toBeVisible();
    expect(screen.getByText("Source: 0 J")).toBeVisible();
    expect(screen.getByText("Source: 3.204353268e-19 J")).toBeVisible();
    expect(screen.getByRole("link", { name: "Source unit definition" })).toHaveAttribute("href", NOMAD_GAP_SCHEMA);
    expect(screen.getByText(/not superconducting gaps or measured metallicity/)).toBeInTheDocument();
    expect(screen.queryByText(/^Metal|Tc =|Nodeless$/)).not.toBeInTheDocument();
  });
  it("rejects a changed eV conversion before rendering or publishing a field hit", async () => {
    vi.mocked(getMaterialCalculationReferences).mockResolvedValue(report({ references: [row("changed_gap", { electronic: {
      version: "nomad-electronic-references/1.0.0", scope: "task_electronic_band_gaps_not_superconducting_gaps", unit_schema_url: NOMAD_GAP_SCHEMA,
      status: "reported", band_gaps: [{ source_kind: "dos_electronic", group_index: 0, spin_channel_index: null, spin_polarized: null, gap_type: null, value_j: 1.602176634e-19, value_ev: 100 }],
    } })] }));
    render(<ExternalCalculationReferences materialId="mat:mgb2" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("100 eV")).not.toBeInTheDocument();
  });
  it("starts folded, preserves structures/tasks and distinguishes unresolved methods and conditions", async () => {
    vi.mocked(getMaterialCalculationReferences).mockResolvedValue(report());
    const view = render(<ExternalCalculationReferences materialId="mat:mgb2" />);
    expect(view.container.querySelector("details")).not.toHaveAttribute("open");
    expect(getMaterialCalculationReferences).not.toHaveBeenCalled();
    expect(screen.getByText("Inspect calculation tasks")).toBeInTheDocument();
    expand();
    await waitFor(() => expect(screen.getByText("2 of 89 tasks")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "task_a ↗" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "task_b ↗" })).toBeInTheDocument();
    expect(screen.getByText("Method not resolved")).toBeInTheDocument();
    expect(screen.getByText("Not inspected")).toBeInTheDocument();
    expect(screen.getByText(/Counts describe tasks, not independent experiments/)).toBeInTheDocument();
    expect(screen.getByText(/at most 20 tasks in entry ID order/)).toBeInTheDocument();
    expect(screen.queryByText(/0 K|Ambient|Scientific approval|Tc =/)).not.toBeInTheDocument();
  });
  it("shows raw DFT names separately from GW method and distinguishes missing metadata from uninspected conditions", async () => {
    vi.mocked(getMaterialCalculationReferences).mockResolvedValue(report({ references: [row("gw_task", { method: "G0W0", program: "exciting", xc_functional_names: ["GGA_X_PBE", "GGA_C_PBE"], xc_functional_type: "GGA", spin_polarized: false, dft_metadata_status: "reported" }), row("unknown_dft")] }));
    render(<ExternalCalculationReferences materialId="mat:mgb2" />);
    expand();
    await waitFor(() => expect(screen.getByText("G0W0")).toBeInTheDocument());
    expect(screen.getByText("Underlying DFT XC: GGA_X_PBE + GGA_C_PBE")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Task details")[0]);
    expect(screen.getByText("Reported non-spin-polarized")).toBeInTheDocument();
    expect(screen.getByText("GGA")).toBeInTheDocument();
    expect(screen.getByText(/including for GW tasks; it does not specify the complete method/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Task details")[1]);
    expect(screen.getAllByText("Not supplied in returned metadata")).toHaveLength(3);
    expect(screen.getByText("Not inspected")).toBeInTheDocument();
  });
  it("rejects a malformed DFT name array rather than rendering a guessed functional", async () => {
    const invalid = row("invalid_dft", { xc_functional_names: [null] as unknown as string[], dft_metadata_status: "reported" });
    vi.mocked(getMaterialCalculationReferences).mockResolvedValue(report({ references: [invalid] }));
    render(<ExternalCalculationReferences materialId="mat:mgb2" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("invalid_dft ↗")).not.toBeInTheDocument();
  });
  it("distinguishes unresolved supplied metadata from missing leaves without discarding valid false", async () => {
    vi.mocked(getMaterialCalculationReferences).mockResolvedValue(report({ references: [row("review_dft", { dft_metadata_status: "requires_review", spin_polarized: false })] }));
    render(<ExternalCalculationReferences materialId="mat:mgb2" />);
    expand();
    await waitFor(() => expect(screen.getByText("1 of 89 tasks")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Task details"));
    expect(screen.getAllByText("Unresolved from returned metadata")).toHaveLength(2);
    expect(screen.getByText("Reported non-spin-polarized")).toBeInTheDocument();
    expect(screen.queryByText("Not supplied in returned metadata")).not.toBeInTheDocument();
  });
  it("distinguishes transport failure from a successful query without matches", async () => {
    vi.mocked(getMaterialCalculationReferences).mockRejectedValueOnce(new Error("Transport"));
    const view = render(<ExternalCalculationReferences materialId="A" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.getByText(/Database coverage cannot be determined/)).toBeInTheDocument();
    vi.mocked(getMaterialCalculationReferences).mockResolvedValueOnce(report({ status: "no_match", references: [], matches_total: 0, inspected_entries: 0 }));
    view.rerender(<ExternalCalculationReferences materialId="C" />);
    expand();
    await waitFor(() => expect(screen.getByText("No match returned")).toBeInTheDocument());
    expect(screen.getByText(/No exact fixed-composition task was returned/)).toBeInTheDocument();
    expect(screen.queryByText(/Database coverage cannot be determined/)).not.toBeInTheDocument();
  });
  it("source composition unresolved status does not invite querying a parent compound", async () => {
    vi.mocked(getMaterialCalculationReferences).mockResolvedValue(report({ status: "not_applicable", references: [], query_formula: null }));
    render(<ExternalCalculationReferences materialId="mat:isotope" />);
    expand();
    await waitFor(() => expect(screen.getByText("Composition review needed")).toBeInTheDocument());
    expect(screen.getByText(/Resolve the exact source composition, isotope or interface notation/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /task_/ })).not.toBeInTheDocument();
  });
  it("immediately resets material A data for B and ignores an aborted late response", async () => {
    let resolveA: (value: MaterialCalculationReferences) => void = () => {};
    vi.mocked(getMaterialCalculationReferences).mockImplementationOnce(() => new Promise(resolve => { resolveA = resolve; })).mockRejectedValueOnce(new Error("B unavailable"));
    const view = render(<ExternalCalculationReferences materialId="A" />);
    expand();
    await waitFor(() => expect(getMaterialCalculationReferences).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(getMaterialCalculationReferences).mock.calls[0][1];
    view.rerender(<ExternalCalculationReferences materialId="B" />);
    expect(signal?.aborted).toBe(true);
    expect(getMaterialCalculationReferences).toHaveBeenCalledTimes(1);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    await act(async () => resolveA(report()));
    expect(screen.queryByText("2 of 89 tasks")).not.toBeInTheDocument();
    expect(screen.queryByText("task_a ↗")).not.toBeInTheDocument();
  });
  it("does not carry loaded A rows or an open fold into a new material", async () => {
    vi.mocked(getMaterialCalculationReferences).mockResolvedValueOnce(report()).mockImplementationOnce(() => new Promise(() => {}));
    const view = render(<ExternalCalculationReferences materialId="A" />);
    expand();
    await waitFor(() => expect(screen.getByText("2 of 89 tasks")).toBeInTheDocument());
    expect(view.container.querySelector("details")).toHaveAttribute("open");
    view.rerender(<ExternalCalculationReferences materialId="B" />);
    expect(screen.queryByText("task_a ↗")).not.toBeInTheDocument();
    expect(screen.getByText("Inspect calculation tasks")).toBeInTheDocument();
    expect(getMaterialCalculationReferences).toHaveBeenCalledTimes(1);
    expect(view.container.querySelector("details")).not.toHaveAttribute("open");
  });
  it("rejects promoted/unsafe report identities and suppresses untrusted origin links", async () => {
    vi.mocked(getMaterialCalculationReferences).mockResolvedValueOnce(report({ references: [row("task_a", { url: "https://evil.example" })] }));
    const view = render(<ExternalCalculationReferences materialId="A" />);
    expand();
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "task_a ↗" })).not.toBeInTheDocument();
    vi.mocked(getMaterialCalculationReferences).mockResolvedValueOnce(report({ references: [row("task_safe", { source_references: [{ provider: "Malicious", url: "javascript:alert(1)" }] })] }));
    view.rerender(<ExternalCalculationReferences materialId="B" />);
    expand();
    await waitFor(() => expect(screen.getByText("1 of 89 tasks")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Task details"));
    expect(screen.queryByRole("link", { name: "Malicious ↗" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Inspect NOMAD archive ↗" })).toHaveAttribute("href", "https://nomad-lab.eu/prod/v1/api/v1/entries/task_safe/archive");
  });
});
