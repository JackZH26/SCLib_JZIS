import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MaterialsPage from "@/app/materials/page";
import { MaterialTable } from "@/components/MaterialTable";
import { StructureEvidencePanel, StructureEvidenceValue, STRUCTURE_EVIDENCE_VERSION } from "@/components/StructureEvidence";
import { listMaterials, type MaterialStructureEvidence, type MaterialSummary } from "@/lib/api";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, listMaterials: vi.fn() };
});

function proposal(): Record<string, unknown> {
  return {
    proposal_id: "synthetic-proposal", field: "structure_phase", value: "Synthetic phase",
    status: "pending", association: "unassigned", scientific_acceptance: false,
    representation: "text_claim", coordinate_artifact_id: null,
    subject: { formula: "SYNTHETIC", sample_id: "S1", pressure: { value: 2, unit: "GPa" } },
    source: { paper_id: "synthetic:source", content_sha256: "a".repeat(64), publication_revision: null },
    evidence: { text: "PRIVATE SOURCE EXCERPT", text_sha256: "b".repeat(64), locator: { kind: "assembled_text_char_span", start: 1, end: 24 } },
    reason_codes: ["source_not_rechecked"],
  };
}

function envelope(): MaterialStructureEvidence {
  return {
    version: STRUCTURE_EVIDENCE_VERSION, scientific_acceptance: false, coordinate_status: "not_validated",
    properties: {
      structure_phase: { status: "pending", value: null, proposal_count: 1 },
      crystal_structure: { status: "unknown", value: null, proposal_count: 0 },
      space_group: { status: "unknown", value: null, proposal_count: 0 },
    },
    proposals: [proposal()], unassigned_mentions: [],
    coverage: { proposal_count: 1, unassigned_mention_count: 0, assessment_complete: true, display_truncated: false },
    warnings: ["text_label_is_not_a_coordinate_structure"],
  };
}

describe("pending-only structure evidence", () => {
  beforeEach(() => { vi.resetAllMocks(); });
  afterEach(() => { vi.unstubAllEnvs(); });

  it("renders source identity and state without approving relations or disclosing unlicensed excerpts", () => {
    const { container } = render(<StructureEvidencePanel evidence={envelope()} />);
    expect(screen.getByText("Pending source review")).toBeInTheDocument();
    expect(screen.getByText("structure_phase: Synthetic phase")).toBeInTheDocument();
    expect(screen.getByText(/"sample_id": "S1"/)).toHaveTextContent('"value": 2');
    expect(screen.getByRole("link", { name: "synthetic:source" })).toHaveAttribute("href", "/paper/synthetic%3Asource");
    expect(screen.getByText(/Source bytes and source revision are not independently rechecked/)).toBeInTheDocument();
    expect(screen.getByText(/Source excerpt withheld/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("PRIVATE SOURCE EXCERPT");
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it.each([undefined, null, {}, { version: "structure-evidence/2.0.0" }, { ...envelope(), scientific_acceptance: true }, { ...envelope(), coordinate_status: "validated" }])("fails closed for missing/incompatible envelope %j", value => {
    render(<StructureEvidencePanel evidence={value} />);
    expect(screen.getByText(/Compatible structure-evidence metadata is unavailable/)).toBeInTheDocument();
    expect(screen.getAllByText("Unknown")).toHaveLength(3);
    expect(screen.queryByText("Pending source review")).not.toBeInTheDocument();
    expect(screen.queryByText("structure_phase: Synthetic phase")).not.toBeInTheDocument();
  });

  it.each([
    { status: "accepted", value: "FAKE", proposal_count: 1 },
    { status: "pending", value: "FAKE", proposal_count: 1 },
    { status: "pending", value: null, proposal_count: -1 },
    { status: "pending", value: null, proposal_count: NaN },
  ])("does not promote malformed property metadata %j", property => {
    render(<StructureEvidenceValue evidence={{ ...envelope(), properties: { structure_phase: property } }} />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.queryByText("FAKE")).not.toBeInTheDocument();
  });

  it("retains unassigned mentions separately and states incomplete/bounded coverage", () => {
    const value = envelope();
    value.unassigned_mentions = [{ ...proposal(), field: "structure_phase", value: "Synthetic unassigned mention" }];
    value.coverage = { proposal_count: 1, unassigned_mention_count: 1, assessment_complete: false, display_truncated: true };
    render(<StructureEvidencePanel evidence={value} />);
    expect(screen.getByText("These mentions are not assigned to this material or state.")).toBeInTheDocument();
    expect(screen.getByText(/assessment is incomplete/)).toBeInTheDocument();
    expect(screen.getByText(/Display is bounded/)).toBeInTheDocument();
    expect(screen.getByText(/Counts are not independent structures or accepted results/)).toBeInTheDocument();
  });

  it("never renders approved or coordinate proposals even under a compatible parent", () => {
    const value = envelope();
    value.proposals = [{ ...proposal(), status: "accepted", value: "FAKE ACCEPTED" }, { ...proposal(), representation: "CIF", value: "FAKE CIF" }];
    value.unassigned_mentions = [{ ...proposal(), scientific_acceptance: true, value: "FAKE MENTION" }];
    const { container } = render(<StructureEvidencePanel evidence={value} />);
    expect(container.textContent).not.toMatch(/FAKE ACCEPTED|FAKE CIF|FAKE MENTION/);
  });

  it("bounds proposal expansion to twenty entries", () => {
    const value = envelope();
    value.proposals = Array.from({ length: 35 }, (_, index) => ({ ...proposal(), proposal_id: `synthetic-${index}` }));
    render(<StructureEvidencePanel evidence={value} />);
    expect(screen.getAllByText("structure_phase: Synthetic phase")).toHaveLength(20);
    expect(screen.getByText(/Display is bounded/)).toBeInTheDocument();
  });

  it("escapes source fields, encodes paper routes and allowlists subject metadata", () => {
    const attack = '<img src=x onerror="window.pwned=true">';
    const value = envelope();
    value.proposals = [{ ...proposal(), value: attack, source: { paper_id: "../../bad?x=<script>" }, subject: { formula: attack, reviewer_email: "secret@example.invalid", pressure: { value: 2, private_notes: "SECRET" } } }];
    const { container } = render(<StructureEvidencePanel evidence={value} />);
    expect(container.querySelector("img, script")).toBeNull();
    expect(container.textContent).toContain(attack);
    expect(container.textContent).not.toMatch(/secret@example.invalid|SECRET|PRIVATE SOURCE EXCERPT/);
    expect(screen.getByRole("link", { name: "../../bad?x=<script>" })).toHaveAttribute("href", "/paper/..%2F..%2Fbad%3Fx%3D%3Cscript%3E");
  });

  it("table never counts a stale phase as linked coverage", () => {
    const row = { id: "synthetic", formula: "SYNTHETIC", total_papers: 1, variant_count: 0, structure_phase: "STALE PHASE", structure_evidence: envelope(), property_evidence: propertyEnvelope(atomicItem("structure_phase", "STALE PHASE")) } as MaterialSummary;
    const { container } = render(<MaterialTable rows={[row]} />);
    expect(screen.getByText("Pending source review")).toBeInTheDocument();
    expect(screen.getByText("0/6")).toBeInTheDocument();
    expect(container.textContent).not.toContain("STALE PHASE");
  });

  it("saved phase filters are explicit unavailable states with a lossless removal link", async () => {
    render(await MaterialsPage({ searchParams: Promise.resolve({ structure_phase: "old-phase", family: "hydride", tc_min: "20", page: "3" }) }));
    expect(vi.mocked(listMaterials)).not.toHaveBeenCalled();
    expect(screen.getByText(/Your saved phase filter was not silently ignored/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("old-phase")).toBeDisabled();
    const link = screen.getByRole("link", { name: /Remove the phase filter/ });
    expect(link).toHaveAttribute("href", "/materials?family=hydride&tc_min=20");
  });

  it("ordinary material browsing still requests the scoped result filters", async () => {
    vi.mocked(listMaterials).mockResolvedValue({ total: 0, results: [], limit: 50, offset: 0 });
    render(await MaterialsPage({ searchParams: Promise.resolve({ family: "hydride", tc_min: "20", pressure_max: "2", experimental_only: "true" }) }));
    expect(vi.mocked(listMaterials)).toHaveBeenCalledWith(expect.objectContaining({ family: "hydride", tc_min: 20, pressure_max: 2, experimental_only: true, structure_phase: undefined }));
    expect(screen.getByPlaceholderText("Pending source review")).toBeDisabled();
    expect(screen.queryByText(/phase filter still uses a catalogue column/)).not.toBeInTheDocument();
  });

  it("full-document recovery includes the configured deployment prefix", async () => {
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib");
    render(await MaterialsPage({ searchParams: Promise.resolve({ structure_phase: "old-phase", family: "hydride", tc_min: "20", page: "3" }) }));
    expect(screen.getByRole("link", { name: /Remove the phase filter/ })).toHaveAttribute("href", "/sclib/materials?family=hydride&tc_min=20");
    expect(vi.mocked(listMaterials)).not.toHaveBeenCalled();
  });
});
