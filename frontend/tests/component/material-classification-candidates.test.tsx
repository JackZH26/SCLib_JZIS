import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MaterialClassificationCandidates } from "@/components/MaterialClassificationCandidates";
import { objectValue } from "@/lib/property-evidence";

const source = { paper_id: "paper:synthetic", source_url: "https://arxiv.org/html/2411.18744v1", source_revision: "synthetic-source-v1", publication_revision_verified: false, content_sha256: "1".repeat(64), locator: { section: "Results", figure: "6", private_notes: "PRIVATE LOCATOR" }, span: { text_sha256: "2".repeat(64) }, evidence_text: "PRIVATE SOURCE" };
function candidate(field = "reported_order", stance = "reported", overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { candidate_id: `classification:synthetic-${field}-${stance}`, version: "material-classification-candidates/1.0.0", material_id: "synthetic", field,
    disposition: "pending", source_content_checked: false, material_state_reviewed: false, scientific_acceptance: false, ml_training_approved: false, public_release: false, database_changed: false,
    claim: { stance, normalized_value: "CDW", value_raw: "charge order", source_role: "author_report", scope: "source_statement_only", relation_to_superconductivity: null },
    subject: { formula: "Synthetic", formula_raw: "Source alias", identity_basis: "local_fixed_composition", conditions: { mentions: [], pressure_status: "not_supplied_in_local_statement" }, methods: [{ name: "susceptibility", value_raw: "magnetic susceptibility" }], private_notes: "PRIVATE SUBJECT" },
    source, evidence_text: "PRIVATE EVIDENCE", private_notes: "PRIVATE CANDIDATE", retained_reference_count: 3, ...overrides };
}
function row(label: string): HTMLElement {
  return screen.getByText((text, element) => element?.tagName === "P" && element.className.includes("font-medium") && text.startsWith(label)).closest("li")!;
}
describe("Pending classification statements", () => {
  it("keeps report, fit, proposal and scoped non-detection separate", () => {
    render(<MaterialClassificationCandidates materialId="synthetic" candidates={[
      candidate(), candidate("pairing_symmetry", "fitted", { claim: { stance: "fitted", normalized_value: "s-wave", value_raw: "s-wave pairing", source_role: "author_report", scope: "source_statement_only" } }),
      candidate("is_unconventional", "proposed", { claim: { stance: "proposed", normalized_value: "unconventional", value_raw: "unconventional superconductivity", source_role: "author_report", scope: "source_statement_only" } }),
      candidate("competing_order", "not_detected", { claim: { stance: "not_detected", normalized_value: "AFM", value_raw: "AFM", source_role: "author_report", scope: "source_statement_only" } }),
    ]} />);
    expect(row("Reported order:")).toHaveTextContent("Author report");
    expect(row("Pairing symmetry:")).toHaveTextContent("Fitted model");
    expect(row("Superconductivity classification:")).toHaveTextContent("Proposed interpretation");
    const negative = row("Competing order:");
    expect(negative).toHaveTextContent("Not detected in reported scope");
    expect(negative).toHaveTextContent("does not establish absence in this material under every condition");
    expect(document.body.textContent).not.toMatch(/Competing order: (No|False)|Scientific approval|PRIVATE|\[object Object\]/);
  });

  it("shows whole condition intervals and units, with unresolved association", () => {
    const item = candidate();
    item.subject = { ...objectValue(item.subject), conditions: { pressure_status: "mentions_require_review", mentions: [{ kind: "pressure", raw_value: "1 to 2", raw_unit: "GPa", quantity: { status: "parsed", relation: "interval", lower: 1, upper: 2, value: null, unit: "GPa", errors: [] } }, { kind: "temperature", raw_value: "10", raw_unit: "K", quantity: { status: "parsed", relation: "exact", value: 10, unit: "K", errors: [] } }] } };
    render(<MaterialClassificationCandidates materialId="synthetic" candidates={[item]} />);
    expect(row("Reported order:")).toHaveTextContent("pressure: 1–2 GPa");
    expect(row("Reported order:")).toHaveTextContent("temperature: 10 K");
    expect(row("Reported order:")).toHaveTextContent("Association and tested window need review");
    expect(row("Reported order:")).toHaveTextContent("Local methods: Susceptibility");
    expect(row("Reported order:")).not.toHaveTextContent("0 GPa");
  });

  it("keeps alias definition provenance distinct from the claim source, without private context", () => {
    const item = candidate();
    item.subject = { ...objectValue(item.subject), identity_basis: "explicit_source_alias_definition_proposal", binding_proposal: { alias_raw: "Sample-A", doping_assignment_raw: "x=0.07", evidence_text: "PRIVATE BINDING", source: { ...source, source_url: "https://arxiv.org/html/2411.18744v1", locator: { section: "Methods", private_notes: "PRIVATE NESTED" } } } };
    render(<MaterialClassificationCandidates materialId="synthetic" candidates={[item]} />);
    const itemRow = row("Reported order:");
    expect(itemRow).toHaveTextContent("Source-defined alias proposal");
    expect(itemRow).toHaveTextContent("Subject definition source:");
    expect(itemRow).toHaveTextContent("Sample-A · x=0.07");
    expect(itemRow).toHaveTextContent("section: Methods");
    expect(within(itemRow).getAllByRole("link", { name: "Open primary source" })).toHaveLength(2);
    expect(itemRow).toHaveTextContent("publication version not verified");
    expect(itemRow).toHaveTextContent("3; these are references to this statement, not independent experiments");
    expect(document.body.textContent).not.toMatch(/PRIVATE|\[object Object\]/);
  });

  it("does not render authority escalation, booleans as labels, other-material or malformed rows", () => {
    render(<MaterialClassificationCandidates materialId="synthetic" candidates={[
      candidate("reported_order", "reported", { scientific_acceptance: true }),
      candidate("reported_order", "reported", { material_id: "other" }),
      candidate("reported_order", "reported", { claim: { stance: "reported", normalized_value: false, value_raw: false, source_role: "author_report", scope: "source_statement_only" } }),
      null as unknown as Record<string, unknown>,
    ]} />);
    expect(screen.queryByText(/Pairing, gap and order source statements/)).not.toBeInTheDocument();
  });

  it("shows rejected spans as review reasons without turning them into negative attributes", () => {
    render(<MaterialClassificationCandidates materialId="synthetic" findings={[{ material_id: "synthetic", fields: ["pairing_symmetry"], reason_codes: ["multiple_property_alternatives_require_review"], source: { ...source, source_url: "javascript:alert(1)" }, evidence_text: "PRIVATE FINDING" }]} />);
    expect(screen.getByText("Source statements requiring closer inspection (1)")).toBeInTheDocument();
    expect(screen.getByText("multiple property alternatives require review")).toBeInTheDocument();
    expect(screen.getByText(/not evidence that the property is absent/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open linked paper" })).toHaveAttribute("href", "/paper/paper%3Asynthetic");
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(document.body.textContent).not.toContain("PRIVATE");
  });

  it("reveals every returned statement and resets expansion on material change", () => {
    const items = Array.from({ length: 41 }, (_, index) => candidate("reported_order", "reported", { candidate_id: `classification:${index}`, claim: { stance: "reported", normalized_value: "CDW", value_raw: `Synthetic order ${index + 1}`, source_role: "author_report", scope: "source_statement_only" } }));
    const view = render(<MaterialClassificationCandidates materialId="synthetic" candidates={items} truncated />);
    expect(screen.queryByText(/Reported order: Synthetic order 41/)).not.toBeInTheDocument();
    const show = screen.getByRole("button", { name: "Show remaining source statements (1)" });
    expect(show).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(show);
    expect(row("Reported order: Synthetic order 41")).toBeInTheDocument();
    expect(screen.getByText(/Only a bounded set/)).toBeInTheDocument();
    view.rerender(<MaterialClassificationCandidates materialId="other" candidates={items.map(item => ({ ...item, material_id: "other" }))} />);
    expect(screen.queryByText(/Reported order: Synthetic order 41/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show remaining source statements (1)" })).toHaveAttribute("aria-expanded", "false");
  });
});
