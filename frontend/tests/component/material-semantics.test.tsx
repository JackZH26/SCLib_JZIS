import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MaterialSemanticValue, MaterialSemanticsPanel } from "@/components/MaterialSemantics";
import { MaterialTable } from "@/components/MaterialTable";
import type { MaterialSemanticEvidence, MaterialSemanticStatus, MaterialSummary } from "@/lib/api";
import { materialSemanticValue, materialSourceCountLabel, negativeEvidenceQualified } from "@/lib/material-semantics";
import { materialSemantics, semanticProperty, semanticReport } from "../fixtures/material-semantics";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";

describe("material classification semantics", () => {
  it("does not turn stale legacy flags or old atomic classifications into reported cells", () => {
    const row = { id: "synthetic", formula: "SYNTHETIC", family: "cuprate", pairing_symmetry: "stale-d-wave", is_unconventional: true, has_competing_order: false, total_papers: 7, variant_count: 0, property_evidence: propertyEnvelope(atomicItem("pairing_symmetry", "old-d-wave"), atomicItem("is_unconventional", true), atomicItem("has_competing_order", false)) } as MaterialSummary;
    const { container } = render(<MaterialTable rows={[row]} />);
    expect(screen.getAllByText("Unknown")).toHaveLength(3);
    expect(screen.getByText("0/6")).toBeInTheDocument();
    expect(screen.getByText("7 legacy links")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/stale-d-wave|old-d-wave|Reported false|Reported true/);
  });

  it.each([
    ["unknown", "Unknown"], ["not_reported", "Not reported"], ["not_extracted", "Not extracted"],
    ["not_computed", "Not computed"], ["failed", "Assessment failed"], ["conflicted", "Conflicting reports"],
  ] as [MaterialSemanticStatus, string][])("keeps %s distinct from false", (status, label) => {
    const value = materialSemantics({ is_unconventional: { ...semanticProperty(null), status, evidence: [] } });
    render(<MaterialSemanticValue semantics={value} field="is_unconventional" />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("Not a negative finding")).toBeInTheDocument();
    expect(screen.queryByText("Reported false (scoped)")).not.toBeInTheDocument();
  });

  it("shows reason-qualified not applicable, not a false scientific finding", () => {
    const value = materialSemantics({ pairing_symmetry: { ...semanticProperty(null, semanticReport(null, { status: "not_applicable", status_reason: "Synthetic source-specific applicability statement" })), status: "not_applicable" } });
    expect(materialSemanticValue(value, "pairing_symmetry")).toBe("Not applicable");
    value.properties.pairing_symmetry!.evidence[0].status_reason = null;
    expect(materialSemanticValue(value, "pairing_symmetry")).toBe("Unknown");
  });

  it("retains an unqualified negative report but never promotes it to false", () => {
    const value = materialSemantics({ has_competing_order: { ...semanticProperty(null, semanticReport(false, { eligible_for_summary: false })), status: "unknown" } });
    render(<MaterialSemanticsPanel semantics={value} />);
    expect(screen.getByText("Retained report: false")).toBeInTheDocument();
    expect(screen.getByText("Unqualified negative report: does not establish absence.")).toBeInTheDocument();
    expect(screen.queryByText("Reported false (scoped)")).not.toBeInTheDocument();
  });

  it("shows a qualified negative with inspectable source, method, conditions and occurrence count", () => {
    const report = semanticReport(false, { negative_qualified: true, detection_conditions: { temperature_min_k: 0.03, temperature_max_k: 20, magnetic_field_t: 0 }, occurrence_count: 3 });
    const value = materialSemantics({ has_competing_order: semanticProperty(false, report) });
    render(<MaterialSemanticsPanel semantics={value} />);
    expect(screen.getByText("Reported false (scoped)")).toBeInTheDocument();
    expect(screen.getByText(/absence is scoped, not universal/)).toBeInTheDocument();
    expect(screen.getByText(/Retained occurrences: 3/)).toBeInTheDocument();
    expect(screen.getByText(/Synthetic scattering method/)).toBeInTheDocument();
    expect(screen.getByText(/"temperature_min_k": 0.03/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "arxiv:synthetic" })).toHaveAttribute("href", "/paper/arxiv%3Asynthetic");
  });

  it.each([
    ["missing method", { method: null }], ["empty conditions", { detection_conditions: {} }],
    ["placeholder method", { method: "unknown" }], ["overlong method", { method: "x".repeat(161) }],
    ["unknown-only conditions", { detection_conditions: { unknown: true } }], ["nonfinite condition", { detection_conditions: { pressure_gpa: NaN } }],
    ["numeric text condition", { detection_conditions: { pressure_gpa: "unknown" } }], ["negative temperature", { detection_conditions: { temperature_min_k: -1 } }],
    ["reversed range", { detection_conditions: { temperature_min_k: 20, temperature_max_k: 1 } }], ["missing-text condition", { detection_conditions: { description: "not reported" } }],
    ["missing source", { paper_id: null, bibliographic_identifiers: [] }], ["forged qualification", { negative_qualified: false }],
    ["ineligible source", { eligible_for_summary: false }], ["held source", { source_status: "retracted" }], ["prior basis", { basis: "family_prior" }],
    ["conflicted classification", { classification_status: "conflicted" }], ["conflicted source role", { source_role: "conflicted" }],
    ["legacy family default", { basis: "family_default" }], ["mixed-case held source", { source_status: " Retracted " }],
    ["overlong result ID", { result_id: "x".repeat(201) }], ["overlong source ID", { paper_id: "x".repeat(201), bibliographic_identifiers: [] }],
  ] as [string, Partial<MaterialSemanticEvidence>][])("fails closed for false with %s", (_label, overrides) => {
    const report = semanticReport(false, { negative_qualified: true, detection_conditions: { pressure_gpa: 0 }, ...overrides });
    const value = materialSemantics({ is_unconventional: semanticProperty(false, report) });
    expect(negativeEvidenceQualified(report)).toBe(false);
    expect(materialSemanticValue(value, "is_unconventional")).toBe("Unknown");
  });

  it.each(["pending", "disputed", "corrected", "retracted", "withdrawn", "quarantined"])("does not promote a %s source even with forged eligibility", source_status => {
    expect(materialSemanticValue(materialSemantics({ is_unconventional: semanticProperty(true, semanticReport(true, { source_status })) }), "is_unconventional")).toBe("Unknown");
  });

  it.each([undefined, null, {}, { version: "material-semantics/2.0.0" }, { version: "material-semantics/1.0.0", scientific_acceptance: true, properties: { is_unconventional: semanticProperty(true) } }])("handles missing, legacy or incompatible metadata safely: %j", value => {
    render(<MaterialSemanticsPanel semantics={value} />);
    expect(screen.getByText(/Compatible material-semantics metadata is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("Reported true")).not.toBeInTheDocument();
  });

  it("rejects malformed basis, scalar types, missing witnesses and incomplete assessment", () => {
    for (const change of [
      (value: ReturnType<typeof materialSemantics>) => { value.properties.is_unconventional!.basis = {} as string; },
      (value: ReturnType<typeof materialSemantics>) => { value.properties.is_unconventional!.value = "true"; },
      (value: ReturnType<typeof materialSemantics>) => { value.properties.is_unconventional!.evidence = []; },
      (value: ReturnType<typeof materialSemantics>) => { value.properties.is_unconventional!.evidence[0].value = false; },
      (value: ReturnType<typeof materialSemantics>) => { value.support.assessment_complete = false; },
      (value: ReturnType<typeof materialSemantics>) => { delete value.support.assessment_complete; },
    ]) {
      const value = materialSemantics({ is_unconventional: semanticProperty(true) });
      change(value);
      expect(materialSemanticValue(value, "is_unconventional")).toBe("Unknown");
    }
    const value = materialSemantics({ is_unconventional: semanticProperty(true) });
    value.support.assessment_complete = false;
    render(<MaterialSemanticsPanel semantics={value} />);
    expect(screen.getByText(/semantics assessment is incomplete/)).toBeInTheDocument();
  });

  it("keeps inferred family priors separate from reported cells and coverage", () => {
    const value = materialSemantics();
    value.priors.push({ property: "pairing_symmetry", value: "synthetic-d-wave", knowledge_origin: "Inferred", basis: "legacy_family_heuristic", policy_version: value.version, provenance: { kind: "legacy_sclib_application_rule", scientific_citation: null }, applicability: { family: "cuprate", sample_state: "not_assessed", universally_applicable: false } });
    render(<><MaterialTable rows={[{ id: "synthetic", formula: "SYNTHETIC", total_papers: 7, variant_count: 0, material_semantics: value } as MaterialSummary]} /><MaterialSemanticsPanel semantics={value} /></>);
    expect(screen.getByText("0/6")).toBeInTheDocument();
    expect(screen.getByText("2 IDs")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Family and domain priors · Inferred, not measured" })).toBeInTheDocument();
    expect(screen.getByText(/synthetic-d-wave · Inferred prior/)).toBeInTheDocument();
    expect(screen.getByText(/not observed labels for ML/)).toBeInTheDocument();
    expect(materialSemanticValue(value, "pairing_symmetry")).toBe("Unknown");
  });

  it("counts reported false as a source-linked field, not an assumed missing value", () => {
    const value = materialSemantics({ has_competing_order: semanticProperty(false, semanticReport(false, { negative_qualified: true, detection_conditions: { pressure_gpa: 0 } })), pairing_symmetry: semanticProperty("synthetic s-wave") });
    render(<MaterialTable rows={[{ id: "synthetic", formula: "SYNTHETIC", total_papers: 7, variant_count: 0, material_semantics: value } as MaterialSummary]} />);
    expect(screen.getByText("2/6")).toBeInTheDocument();
    expect(screen.getByText("Reported false (scoped)")).toBeInTheDocument();
    expect(screen.getByText("synthetic s-wave")).toBeInTheDocument();
  });

  it("separates Tc/state variation, extraction inconsistency and unadjudicated disputes", () => {
    const value = materialSemantics();
    value.conflicts.state_variability = { detected: true, count: 1, properties: ["tc_kelvin"], evidence: [{ property: "tc_kelvin", result_ids: ["synthetic-A", "synthetic-B"], occurrence_ids: ["occ-A", "occ-B"], reason_codes: ["different_known_conditions"] }] };
    value.conflicts.extraction_conflict = { detected: true, count: 1, properties: ["pairing_symmetry"], evidence: [] };
    value.conflicts.scientific_dispute = { status: "reported_unadjudicated", count: 1, evidence: [{ paper_id: "doi:synthetic", result_id: "synthetic-C" }], evidence_truncated: true };
    render(<MaterialSemanticsPanel semantics={value} />);
    expect(screen.getByText(/Variation across Tc values or state metadata is not itself a scientific dispute/)).toBeInTheDocument();
    expect(screen.getByText(/An extraction inconsistency needs source inspection/)).toBeInTheDocument();
    expect(screen.getByText("Reported — unadjudicated")).toBeInTheDocument();
    expect(screen.getByText("Result IDs: synthetic-A; synthetic-B")).toBeInTheDocument();
    expect(screen.getByText("Occurrence IDs: occ-A; occ-B")).toBeInTheDocument();
    expect(screen.getByText(/not a complete dispute or conflict history/)).toBeInTheDocument();
  });

  it("retains explicit order labels without claiming causal competition", () => {
    render(<MaterialSemanticsPanel semantics={materialSemantics({ has_competing_order: semanticProperty(true, semanticReport(true, { source_value: "CDW", basis: "reported_competing_order_label" })) })} />);
    expect(screen.getByText("Reported true")).toBeInTheDocument();
    expect(screen.getByText(/Reported order label: CDW. An order label does not establish causal competition/)).toBeInTheDocument();
  });

  it("labels identifier and legacy parent-rollup counts and never infers independent confirmations", () => {
    const value = materialSemantics();
    value.support.independent_work_count = 12345;
    value.support.independent_replication_count = 67890;
    const { container } = render(<MaterialSemanticsPanel semantics={value} />);
    expect(screen.getByText("Bibliographic identifiers").nextElementSibling).toHaveTextContent("2");
    expect(screen.getByText("Legacy catalogue paper links").nextElementSibling).toHaveTextContent("7");
    expect(screen.getAllByText("Unknown — not established")).toHaveLength(2);
    expect(screen.getByText(/Legacy paper links may include parent rollups/)).toBeInTheDocument();
    expect(screen.getByText(/Count basis:/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/12345|67890/);
    expect(materialSourceCountLabel(undefined, 7)).toBe("7 legacy links");
    expect(materialSourceCountLabel(materialSemantics(), 7)).toBe("2 IDs");
    value.support.bibliographic_identifier_count = -1;
    expect(materialSourceCountLabel(value)).toBe("Unknown");
  });

  it("renders source strings literally, encodes paper paths, and excludes private context", () => {
    const attack = '<img src=x onerror="window.pwned=true">';
    const report = semanticReport(true, { paper_id: "../../bad?x=<script>", method: attack, state: { sample_id: attack, pressure: { state: "reported", value: 2, reviewer_email: "private@example.invalid" }, doping_level: { value: 0.2, unit: "fraction" }, reviewer_email: "private@example.invalid" }, source_locator: { table: attack, private_notes: "SECRET" } });
    const { container } = render(<MaterialSemanticsPanel semantics={materialSemantics({ is_unconventional: semanticProperty(true, report) })} />);
    expect(container.querySelector("img, script")).toBeNull();
    expect(container.textContent).toContain(attack);
    expect(container.textContent).not.toMatch(/private@example.invalid|SECRET/);
    expect(screen.getByRole("link", { name: "../../bad?x=<script>" })).toHaveAttribute("href", "/paper/..%2F..%2Fbad%3Fx%3D%3Cscript%3E");
    expect(screen.getByText(/"doping_level"/)).toHaveTextContent('"value": 0.2');
  });

  it("does not collapse known false into absent evidence in its table row", () => {
    const value = materialSemantics({ is_unconventional: semanticProperty(false, semanticReport(false, { negative_qualified: true, detection_conditions: { description: "Synthetic fixed protocol" } })) });
    render(<MaterialSemanticsPanel semantics={value} />);
    const row = screen.getByRole("rowheader", { name: "Unconventional classification" }).closest("tr")!;
    expect(within(row).getByText("Reported false (scoped)")).toBeInTheDocument();
    expect(within(row).getByText("Inspect 1 retained report")).toBeInTheDocument();
  });
});
