import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialEnrichment } from "@/components/MaterialEnrichment";
import { getMaterialEnrichment, type MaterialEnrichmentReport } from "@/lib/api";

vi.mock("@/lib/api", () => ({ getMaterialEnrichment: vi.fn() }));
function candidate(field: string, rawValue: unknown, quantity: Record<string, unknown> | null = null, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { candidate_id: `candidate:${field}`, field, raw_value: rawValue, value: quantity?.value ?? rawValue, quantity,
    source: { paper_id: "paper:synthetic", kind: "original_passage", source_revision: "test-capture", content_sha256: "1".repeat(64), source_url: "https://arxiv.org/html/0912.2752v2", locator: { table: "1", row: 2 }, span: { char_start: 0, char_end: 10, text_sha256: "2".repeat(64) } }, reason_codes: ["material_state_association_requires_review"], ...overrides };
}
function report(candidates: Record<string, unknown>[]): MaterialEnrichmentReport {
  return { version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false, counts: {}, candidates,
    coverage: [{ material_id: "synthetic", formula: "Synthetic fixture", fields: candidates.map(item => ({ field: String(item.field), status: "pending_review", retained_present: false, candidate_count: 1, reason_codes: [], routes: ["source_table_and_supplement"] })) }] };
}
function quantity(value: number | null, unit: string, overrides: Record<string, unknown> = {}) {
  return { status: "parsed", relation: "exact", value, lower: null, upper: null, uncertainty: null, approximate: false, errors: [], unit, raw_unit: unit, ...overrides };
}
async function renderCandidates(candidates: Record<string, unknown>[]) {
  vi.mocked(getMaterialEnrichment).mockResolvedValue(report(candidates));
  const view = render(<MaterialEnrichment materialId="synthetic" />);
  await waitFor(() => expect(screen.getByText(`Source recovery candidates (${candidates.length})`)).toBeInTheDocument());
  return view;
}
function candidateRow(label: string): HTMLLIElement {
  const title = screen.getByText((text, element) => element?.tagName === "P" && element.className.includes("font-medium") && text.startsWith(label));
  return title.closest("li")!;
}

describe("Recovery candidate quantity and source presentation", () => {
  beforeEach(() => vi.resetAllMocks());

  it("formats parsed values once when original tokens already include their unit", async () => {
    const view = await renderCandidates([candidate("tc_kelvin", "116 K", quantity(116, "K")), candidate("measurement_temperature_k", "250 K", quantity(250, "K")), candidate("pressure_gpa", "140 GPa", quantity(140, "GPa"))]);
    expect(candidateRow("Tc:").querySelector("p")).toHaveTextContent("Tc: 116 K");
    expect(candidateRow("Measurement temperature:").querySelector("p")).toHaveTextContent("Measurement temperature: 250 K");
    expect(candidateRow("Pressure:").querySelector("p")).toHaveTextContent("Pressure: 140 GPa");
    expect(view.container.textContent).not.toMatch(/116 K K|250 K K|140 GPa GPa/);
    expect(within(candidateRow("Tc:")).getByText("Raw source value:").parentElement).toHaveTextContent("116 K");
  });

  it("keeps crystallographic uncertainty and the original parenthetical notation accessible", async () => {
    await renderCandidates([candidate("lattice_a", "3.9772(9)", quantity(3.9772, "angstrom", { uncertainty: 0.0009, raw_unit: "Å" }))]);
    const row = candidateRow("Lattice a:");
    expect(row.querySelector("p")).toHaveTextContent("3.9772 ± 0.0009 Å");
    expect(within(row).getByText("3.9772(9)")).toBeInTheDocument();
    expect(row).toHaveTextContent("exact / parsed");
  });

  it("retains intervals and source frequency units without manufacturing a point or converting to Kelvin", async () => {
    await renderCandidates([candidate("tc_kelvin", "120-130 K", quantity(null, "K", { relation: "interval", lower: 120, upper: 130 })), candidate("omega_log_source_value", "1090 cm^-1", quantity(1090, "cm^-1"))]);
    expect(candidateRow("Tc:").querySelector("p")).toHaveTextContent("120–130 K");
    expect(candidateRow("Tc:")).toHaveTextContent("interval / parsed");
    expect(candidateRow("Logarithmic phonon frequency:").querySelector("p")).toHaveTextContent("1090 cm^-1");
    expect(candidateRow("Logarithmic phonon frequency:").querySelector("p")).not.toHaveTextContent("1090 K");
  });

  it("preserves an invalid source token without appending a guessed unit", async () => {
    await renderCandidates([candidate("tc_kelvin", "unclear temperature token", quantity(237, "K", { status: "invalid", errors: ["unparsed"] }))]);
    const row = candidateRow("Tc:"); expect(row.querySelector("p")).toHaveTextContent("Tc: unclear temperature token");
    expect(row.querySelector("p")).not.toHaveTextContent("237"); expect(row.querySelector("p")).not.toHaveTextContent("token K");
    expect(row).toHaveTextContent("exact / invalid"); expect(row).toHaveTextContent("Review needed");
  });

  it("shows pending composition, site and occupancy dictionaries as labeled scientific context", async () => {
    await renderCandidates([
      candidate("composition_identity", { catalogue_formula: "BaFe1.906Pt0.094As2", source_formula: "BaFe1.90Pt0.10As2", nominal_formula_raw: "BaFe1.90Pt0.10As2", refined_formula_raw: "BaFe1.906(8)Pt0.094(8)As2", relation: "nominal_refined_same_sample_proposal", association_reviewed: false, reviewer_email: "PRIVATE@example.invalid" }),
      candidate("atomic_sites", { site: "As", fractional_coordinate_raw: "z=0.35422(9)", full_coordinates_and_symmetry_reviewed: false }),
      candidate("site_occupancies", { site_elements: ["Fe", "Pt"], fractions_raw: { Fe: "0.953(4)", Pt: "0.047(4)", private_notes: "SECRET" }, interpretation: "source_reported_refined_same_site_ratio", occupancy_and_structure_binding_reviewed: false }),
    ]);
    const composition = candidateRow("Composition identity:");
    expect(composition).toHaveTextContent("Catalogue formula"); expect(composition).toHaveTextContent("BaFe1.906Pt0.094As2"); expect(composition).toHaveTextContent("Refined formula (source)"); expect(composition).toHaveTextContent("BaFe1.906(8)Pt0.094(8)As2"); expect(composition).toHaveTextContent("not automatically equivalent");
    expect(candidateRow("Atomic sites:")).toHaveTextContent("z=0.35422(9)");
    const occupancy = candidateRow("Site occupancies:"); expect(occupancy).toHaveTextContent("Fe occupancy (source)"); expect(occupancy).toHaveTextContent("0.953(4)"); expect(occupancy).toHaveTextContent("Pt occupancy (source)"); expect(occupancy).toHaveTextContent("0.047(4)"); expect(occupancy).toHaveTextContent("do not supply validated coordinates");
    expect(document.body.textContent).not.toMatch(/\[object Object\]|See quantity|PRIVATE@example.invalid|SECRET/);
  });

  it("links the primary source and falls back safely when a supplied URL is not an HTTP source", async () => {
    await renderCandidates([candidate("space_group", "Cmmm"), candidate("crystal_structure", "Tetragonal", null, { source: { paper_id: "paper:synthetic", source_url: "javascript:alert(1)", locator: { section: "Results", private_notes: "PRIVATE" } } })]);
    expect(within(candidateRow("Space group:")).getByRole("link", { name: "Open primary source" })).toHaveAttribute("href", "https://arxiv.org/html/0912.2752v2");
    expect(within(candidateRow("Space group:")).getByRole("link", { name: "Open primary source" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(candidateRow("Structure label:")).getByRole("link", { name: "Open linked paper" })).toHaveAttribute("href", "/paper/paper%3Asynthetic");
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull(); expect(document.body.textContent).not.toContain("PRIVATE");
  });

  it("states the record and paper sampling scope rather than implying complete coverage", async () => {
    const body = report([]);
    body.inspection_scope = { records_total: 500, records_inspected: 32, records_truncated: true, papers_total: 12, papers_inspected: 8, papers_truncated: true };
    vi.mocked(getMaterialEnrichment).mockResolvedValue(body);
    render(<MaterialEnrichment materialId="synthetic" />);
    expect(await screen.findByText(/Inspected 32 of 500 eligible retained records across 8 of 12 linked papers/)).toHaveTextContent("remaining records and sources have not been inspected");
  });
});
