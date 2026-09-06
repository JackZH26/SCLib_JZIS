import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScientificMatches } from "@/components/ScientificMatches";
import { pressureLabel } from "@/lib/pressure-semantics";

const version = { classifier_version: "pressure-policy/1.0.0" };

describe("explicit pressure display", () => {
  it("never translates absent, legacy zero, or negative pressure into ambient", () => {
    expect(pressureLabel(undefined, null)).toBe("Pressure not reported");
    expect(pressureLabel(undefined, 0)).toBe("0 GPa (unverified)");
    expect(pressureLabel(undefined, -1)).toBe("-1 GPa (unverified)");
    expect(pressureLabel({ ...version, pressure_state: "ambiguous" }, 0)).toBe("Pressure unresolved");
    expect(pressureLabel({ ...version, pressure_state: "explicit_ambient" })).toBe("Explicit ambient");
  });
  it("preserves interval, bound and uncertainty notation", () => {
    expect(pressureLabel({ ...version, pressure_state: "reported", relation: "interval", value_lower_gpa: 1, value_upper_gpa: 3 })).toBe("1–3 GPa");
    expect(pressureLabel({ ...version, pressure_state: "reported", relation: "le", value_upper_gpa: 2 })).toBe("≤ 2 GPa");
    expect(pressureLabel({ ...version, pressure_state: "reported", pressure_gpa: 2, uncertainty_gpa: 0.5 })).toBe("2 ± 0.5 GPa");
  });
  it("surfaces the matched occurrence instead of a catalogue maximum", () => {
    render(<ScientificMatches results={[{ result_id: "legacy-result:fixture", record_index: 1,
      formula: "Synthetic-X", family: null, tc_lower_bound_k: 5, pressure_semantics: { ...version, pressure_state: "not_reported" },
      result_classification: { knowledge_origin: "Computed" }, filter_policy_version: "same-result/1.0.0" }]} />);
    expect(screen.getByText("Matching result evidence (1)")).toBeInTheDocument();
    expect(screen.getByText(/Tc lower bound 5 K/)).toHaveTextContent("Pressure not reported · Computed");
  });
});
