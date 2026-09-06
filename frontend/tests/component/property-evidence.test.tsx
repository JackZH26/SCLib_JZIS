import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AtomicEvidenceDetails, JointEpcNotice, PropertyEvidenceValue } from "@/components/PropertyEvidence";
import { MaterialTable } from "@/components/MaterialTable";
import type { MaterialSummary } from "@/lib/api";
import { propertyJsonLd, propertyValue, selectedProperty, sourceHref, supportedPropertyDescription } from "@/lib/property-evidence";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";

describe("atomic property evidence", () => {
  it("does not display a stale catalogue scalar or turn T1/family into support", () => {
    const material = { id: "test", formula: "TEST", family: "hydride", tc_max: 9999, tc_ambient: 8888, pairing_symmetry: "fictional-pairing", structure_phase: "fictional-phase", best_credibility_tier: "T1", total_papers: 1, variant_count: 0 } as MaterialSummary;
    render(<MaterialTable rows={[material]} />);
    expect(screen.queryByText("9999")).not.toBeInTheDocument();
    expect(screen.queryByText("8888")).not.toBeInTheDocument();
    expect(screen.queryByText("fictional-pairing")).not.toBeInTheDocument();
    expect(screen.getAllByText("Source unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText(/Sorting uses legacy catalogue columns/)).toBeInTheDocument();
    expect(screen.getByText("0/6")).toBeInTheDocument();
  });

  it("takes maximum Hc2 conditions and provenance from B, never A", () => {
    const b = atomicItem("hc2_tesla", 100, { result_id: "result:B", conditions: { hc2_conditions: "Along ab at 0 K", hc2_direction: "ab", hc2_temperature_k: atomicItem("temperature_k", 0).quantity }, source: { paper_id: "paper:B", source_locator: { figure: "4" } } });
    render(<AtomicEvidenceDetails item={b} />);
    expect(screen.getByText("Along ab at 0 K")).toBeInTheDocument();
    expect(screen.getByText("ab")).toBeInTheDocument();
    expect(screen.getByText("0 K")).toBeInTheDocument();
    expect(screen.getByText("result:B")).toBeInTheDocument();
    expect(screen.getByText("figure: 4")).toBeInTheDocument();
    expect(screen.queryByText("Along c at 5 K")).not.toBeInTheDocument();
  });

  it("preserves small numbers, approximation, uncertainty and censored quantities", () => {
    const item = atomicItem("tc_max", 0.001);
    item.quantity = { ...item.quantity, approximate: true, uncertainty: 0.0001 };
    expect(propertyValue(item)).toBe("≈ 0.001 ± 0.0001 K");
    item.quantity = { ...item.quantity, relation: "ge", value: null, lower: 0.001, uncertainty: null };
    expect(propertyValue(item)).toBe("≈ ≥ 0.001 K");
    item.quantity = { ...item.quantity, relation: "interval", lower: 0.001, upper: 0.003 };
    expect(propertyValue(item)).toBe("≈ 0.001–0.003 K");
  });

  it.each(["no_quantity", "invalid_quantity", "nonfinite", "different_value", "numeric_source", "numeric_result", "missing_source"])("fails closed for malformed supported data: %s", mutation => {
    const item = atomicItem("tc_max", 20);
    if (mutation === "no_quantity") item.quantity = null;
    if (mutation === "invalid_quantity") item.quantity = { ...item.quantity, errors: ["unit_mismatch"] };
    if (mutation === "nonfinite") item.quantity = { ...item.quantity, value: Infinity };
    if (mutation === "different_value") item.quantity = { ...item.quantity, value: 40 };
    if (mutation === "numeric_source") item.source = { paper_id: 42 };
    if (mutation === "numeric_result") item.result_id = 42 as unknown as string;
    if (mutation === "missing_source") item.source = { paper_id: null, year: 2026 };
    expect(selectedProperty(propertyEnvelope(item), "tc_max")).toBeNull();
  });

  it("keeps source-unavailable result metadata inspectable without a headline value", () => {
    const item = atomicItem("tc_max", 20, { source: { paper_id: null, source_locator: {} } });
    render(<PropertyEvidenceValue evidence={propertyEnvelope(item)} field="tc_max" />);
    expect(screen.getByText("Source unavailable")).toBeInTheDocument();
    expect(screen.getByText(item.result_id)).toBeInTheDocument();
    expect(screen.queryByText("20 K")).not.toBeInTheDocument();
  });

  it("shows only the selected lattice subset, with full same-result structure as context", () => {
    const a = { ...atomicItem("lattice_a", 3).quantity, unit: "Å" };
    const c = { ...atomicItem("lattice_c", 12).quantity, unit: "Å" };
    const item = atomicItem("lattice_params", { a: 3 }, {
      quantity: { status: "parsed", relation: "group", components: { a, c } },
      structure: { space_group: "P4/mmm", lattice_params: { a: 3, c: 12 }, lattice_quantities: { a, c } },
    });
    expect(propertyValue(item)).toBe("a=3 Å");
    render(<PropertyEvidenceValue evidence={propertyEnvelope(item)} field="lattice_params" />);
    expect(screen.getByText("a=3 Å · c=12 Å")).toBeInTheDocument();
    expect(screen.getByText("P4/mmm")).toBeInTheDocument();
    expect(screen.getByText(/One source record; not a reconstruction/)).toBeInTheDocument();
  });

  it("only exposes source-supported selections in metadata and JSON-LD", () => {
    expect(propertyJsonLd(undefined, "tc_max")).toBeNull();
    expect(supportedPropertyDescription(undefined, "tc_max")).toBeNull();
    const item = atomicItem("tc_max", 0.001);
    item.quantity = { ...item.quantity, approximate: true, uncertainty: 0.0001 };
    expect(propertyJsonLd(propertyEnvelope(item), "tc_max")).toMatchObject({ value: "≈ 0.001 ± 0.0001", unitText: "K" });
    expect(supportedPropertyDescription(propertyEnvelope(item), "tc_max")).toContain("≈ 0.001 ± 0.0001 K (record origin: Computed; catalogue selection)");
  });

  it("qualifies record origin instead of declaring every property independently observed", () => {
    const item = atomicItem("lambda_eph", 2, { origin: { knowledge_origin: "Observed", classification_status: "resolved", source_role: "primary" } });
    const envelope = propertyEnvelope(item);
    render(<PropertyEvidenceValue evidence={envelope} field="lambda_eph" />);
    expect(screen.getByText("Record: Observed")).toBeInTheDocument();
    expect(screen.getByText("Record origin")).toBeInTheDocument();
    expect(screen.getByText("Record source role")).toBeInTheDocument();
    expect(screen.getByText(/Record-level classification does not independently establish/)).toBeInTheDocument();
    expect(propertyJsonLd(envelope, "lambda_eph")?.name).toContain("record origin: Observed");
    expect(propertyJsonLd(envelope, "lambda_eph")?.description).toContain("not an independent classification of each property");
  });

  it("never treats independent λ and ω_log selections as a linked pair", () => {
    const envelope = propertyEnvelope(atomicItem("lambda_eph", 3), atomicItem("omega_log_k", 1000));
    envelope.joint_epc = { status: "pending", pairs: [], selected: null, warnings: ["missing_or_conflicting_state_structure_run_protocol"] };
    render(<JointEpcNotice evidence={envelope} />);
    expect(screen.getByText(/Separately selected λ and ω_log must not be combined/)).toBeInTheDocument();
    expect(screen.queryByText("Inspect the linked EPC pair")).not.toBeInTheDocument();
  });

  it("distinguishes an unevaluated compact response from a negative pairing finding", () => {
    render(<JointEpcNotice evidence={propertyEnvelope()} />);
    expect(screen.getByText(/EPC association was not evaluated/)).toHaveTextContent("not evidence that no compatible pair exists");
  });

  it("identifies the actual linked pair, not two independent displayed maxima", () => {
    const envelope = propertyEnvelope(atomicItem("lambda_eph", 3), atomicItem("omega_log_k", 1000));
    const lambda = atomicItem("lambda_eph", 2, { result_id: "actual-linked-lambda" });
    const omega = atomicItem("omega_log_k", 800, { result_id: "actual-linked-omega" });
    envelope.joint_epc = { status: "eligible", selected: { pair_id: "pair:test", lambda, omega_log: omega, association_basis: "explicit_state_structure_run_protocol", eligible_meaning: "association_complete_only", allen_dynes_applicability: "not_assessed" }, pairs: [], warnings: [] };
    render(<JointEpcNotice evidence={envelope} />);
    expect(screen.getByText("Linked λ_eph: 2")).toBeInTheDocument();
    expect(screen.getByText("Linked ω_log: 800 K")).toBeInTheDocument();
    expect(screen.getByText("actual-linked-lambda")).toBeInTheDocument();
    expect(screen.getByText("actual-linked-omega")).toBeInTheDocument();
    expect(screen.getByText(/not scientific validation or permission/)).toBeInTheDocument();
  });

  it("keeps bounded alternatives separate and discloses the response scope", () => {
    const envelope = propertyEnvelope(atomicItem("tc_max", 20));
    envelope.evidence_scope = "bounded_alternatives";
    envelope.properties.tc_max.evidence = [atomicItem("tc_max", 10, { result_id: "other-state", state: { state_id: "state:other" } })];
    envelope.properties.tc_max.truncated = true;
    envelope.properties.tc_max.total_evidence_count = 30;
    render(<PropertyEvidenceValue evidence={envelope} field="tc_max" />);
    expect(screen.getByText("Other source results (1)")).toBeInTheDocument();
    expect(screen.getByText(/bounded set of alternatives/)).toBeInTheDocument();
    expect(screen.getByText("state:other")).toBeInTheDocument();
  });

  it("does not manufacture external source links from arbitrary protocols", () => {
    expect(sourceHref({ doi: "javascript:alert(1)" })).toBeNull();
    expect(sourceHref({ arxiv_id: "//evil.example" })).toBeNull();
    expect(sourceHref({ paper_id: "doi:10.1000/test" })).toBe("/paper/doi%3A10.1000%2Ftest");
  });
});
