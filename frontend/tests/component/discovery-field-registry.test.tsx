import { describe, expect, it } from "vitest";
import { DISCOVERY_DEMO_ROWS } from "@/lib/discovery-layout-demo";
import { FIELD_BY_KEY, FIELD_GROUPS, SCIENTIFIC_FIELDS, checkedScientificValue, formatScientificValue, missingScientificValue, type ScientificValue } from "@/lib/discovery-field-registry";

describe("Cross-family scientific display contract", () => {
  it("defines unique fields with group, unit, context, comparison and ML roles", () => {
    expect(SCIENTIFIC_FIELDS.length).toBeGreaterThan(100);
    expect(new Set(SCIENTIFIC_FIELDS.map(f => f.key)).size).toBe(SCIENTIFIC_FIELDS.length);
    for (const f of SCIENTIFIC_FIELDS) {
      expect(FIELD_GROUPS.some(g => g.id === f.group)).toBe(true);
      expect(f.definition.length).toBeGreaterThan(10);
      expect(f.requiredContext.length).toBeGreaterThan(10);
      expect(f.comparisonScope).toBeTruthy();
      expect(f.monotonicity).toBe("not_assumed");
      expect(f.sortable).toBe(false);
      if (f.kind === "number") expect(f.unit).toBeTruthy();
    }
  });

  it("retains scientific distinctions and posterior safeguards", () => {
    expect(FIELD_BY_KEY.carrier_density_2d.unit).toBe("cm⁻²");
    expect(FIELD_BY_KEY.carrier_density_3d.unit).toBe("cm⁻³");
    expect(FIELD_BY_KEY.electron_phonon_lambda.unit).toBe("1");
    expect(FIELD_BY_KEY.penetration_depth.unit).toBe("nm");
    expect(FIELD_BY_KEY.omega_log.unit).toBe("K");
    expect(FIELD_BY_KEY.dos_ef.definition).toContain("normalization");
    for (const key of ["tc_onset", "tc_zero", "tc_over_tf", "gap_ratio", "penetration_depth", "coherence_length", "superfluid_weight"]) expect(FIELD_BY_KEY[key].featureRole).toBe("post_outcome");
    expect(FIELD_BY_KEY.predicted_tc.featureRole).toBe("audit_only");
    for (const key of ["quantum_metric", "alpha2f", "lambda_band_matrix", "interface_stack"]) expect(FIELD_BY_KEY[key].kind).toBe("artifact");
  });

  it("keeps every fixture explicitly synthetic and every populated value on its own state", () => {
    expect(new Set(DISCOVERY_DEMO_ROWS.map(row => row.formula)).size).toBe(DISCOVERY_DEMO_ROWS.length);
    for (const row of DISCOVERY_DEMO_ROWS) for (const [key, value] of Object.entries(row.fields)) {
      expect(FIELD_BY_KEY[key]).toBeDefined();
      if (value.availability === "known") {
        expect(value.kind).toBe(FIELD_BY_KEY[key].kind);
        expect(value.provenance.stateId).toBe(row.stateId);
        expect(value.provenance.synthetic).toBe(true);
        expect(value.provenance.origin).toBe("AI-Proposed");
        expect(value.provenance.review).toBe("pending");
        if (value.kind === "number") {
          expect(Number.isFinite(value.value)).toBe(true);
          expect(value.unit).toBe(FIELD_BY_KEY[key].unit);
        }
      } else {
        expect(value.value).toBeNull();
        expect(value.reason.length).toBeGreaterThan(10);
      }
    }
  });

  it("preserves true zero, signed quantities, unknown and N/A separately", () => {
    const mg = DISCOVERY_DEMO_ROWS.find(row => row.id === "DEMO-01")!;
    expect(formatScientificValue(mg.fields.pressure_gpa)).toBe("0");
    expect(formatScientificValue(mg.fields.substrate)).toBe("Not applicable");
    expect(formatScientificValue(missingScientificValue())).toBe("Unknown");
    expect(formatScientificValue(DISCOVERY_DEMO_ROWS.find(row => row.id === "DEMO-14")!.fields.moire_filling)).toBe("-2.2");
    const cuprate = DISCOVERY_DEMO_ROWS.find(row => row.family === "Cuprate")!;
    expect(cuprate.fields.electron_phonon_lambda.applicability).toBe("undetermined");
    expect(cuprate.fields.oxygen_defect_status.availability).toBe("not_extracted");
    expect(DISCOVERY_DEMO_ROWS.find(row => row.id === "DEMO-11")!.fields.energy_above_hull.availability).toBe("failed");
  });

  it("rejects unit mismatch, non-finite values, absent normalization and wrong-state joins", () => {
    const row = DISCOVERY_DEMO_ROWS.find(row => row.id === "DEMO-01")!;
    const hull = row.fields.energy_above_hull;
    if (hull.availability !== "known" || hull.kind !== "number") throw new Error("fixture requires hull");
    expect(checkedScientificValue("energy_above_hull", { ...hull, value: 20, qualifier: "exact", unit: "meV/atom" }, row.stateId).availability).toBe("unavailable");
    expect(checkedScientificValue("energy_above_hull", { ...hull, value: Infinity, qualifier: "exact" }, row.stateId).availability).toBe("unavailable");
    expect(checkedScientificValue("energy_above_hull", hull, "wrong-state").availability).toBe("unavailable");
    const dos = row.fields.dos_ef;
    if (dos.availability !== "known") throw new Error("fixture requires DOS");
    expect(checkedScientificValue("dos_ef", { ...dos, provenance: { ...dos.provenance, normalization: undefined } }, row.stateId).availability).toBe("unavailable");
    for (const key of ["pairing_assertions", "pairing_solver", "structure_evidence_status"]) expect(FIELD_BY_KEY[key].featureRole).toBe("audit_only");
  });

  it("preserves ranges and one-sided limits instead of manufacturing midpoints", () => {
    const row = DISCOVERY_DEMO_ROWS.find(row => row.id === "DEMO-01")!;
    const pressure = row.fields.pressure_gpa;
    if (pressure.availability !== "known" || pressure.kind !== "number") throw new Error("fixture requires pressure");
    const interval: ScientificValue = { ...pressure, qualifier: "interval", value: null, lower: 150, upper: 170 };
    expect(formatScientificValue(checkedScientificValue("pressure_gpa", interval, row.stateId))).toBe("150–170");
    expect(checkedScientificValue("pressure_gpa", { ...interval, lower: 180 }, row.stateId).availability).toBe("unavailable");
    expect(formatScientificValue({ ...pressure, qualifier: "lt", value: 1 })).toBe("<1");
  });
});
