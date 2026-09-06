import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MaterialTable } from "@/components/MaterialTable";
import type { MaterialSummary } from "@/lib/api";
import { recordClassification, resultOrigin, scientificNumber } from "@/lib/result-semantics";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";

describe("result classification display", () => {
  it("does not infer Observed from a legacy false theory flag or T1", () => {
    expect(recordClassification({ is_theoretical: false, credibility_tier: "T1" }).origin).toBe("Unknown");
    expect(resultOrigin("experimental")).toBe("Unknown");
    expect(resultOrigin("<script>")).toBe("Unknown");
  });

  it("keeps conflicts, cited roles and version context visible", () => {
    expect(recordClassification({ result_classification: {
      knowledge_origin: "Unknown", classification_status: "conflicted",
      source_role: "cited", classifier_version: "sclib-result-origin/v1",
    } })).toEqual({
      origin: "Unknown", status: "conflicted", role: "cited", version: "sclib-result-origin/v1",
    });
  });

  it("renders millikelvin data without rounding it into a measured zero", () => {
    expect(scientificNumber(0.001)).toBe("0.001");
    expect(scientificNumber(0.00001)).toBe("0.00001");
    expect(scientificNumber(Infinity)).toBe("—");
  });

  it("labels a computed headline beside its value and calls T1 a source tier", () => {
    const row = {
      id: "synthetic", formula: "MgB2", family: null, tc_max: 0.001,
      tc_max_origin: "Computed", tc_ambient: null, total_papers: 1,
      pairing_symmetry: null, structure_phase: null, ambient_sc: null,
      is_unconventional: null, has_competing_order: null, arxiv_year: null,
      best_credibility_tier: "T1", variant_count: 0,
      property_evidence: propertyEnvelope(atomicItem("tc_max", 0.001)),
    } as MaterialSummary;
    render(<MaterialTable rows={[row]} />);
    expect(screen.getAllByText("Computed").length).toBeGreaterThan(0);
    expect(screen.getByText("0.001")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Source tier" })).toHaveAttribute(
      "title", "Source tier is not experimental confirmation",
    );
    expect(screen.queryByText("Observed")).not.toBeInTheDocument();
  });
});
