import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import type { MaterialEnrichmentReport, MaterialStructureReferences } from "@/lib/api";
import publicBatch from "@/public/research-pilots/materials-source-observations-2026-10-02.json";
import { groupSourceObservations, loadSourceObservationBatch, observationLabel, observationValue, sourceObservationsForCod, sourceObservationsForRecovery } from "@/lib/material-source-observations";

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const literal = JSON.parse(readFileSync(resolve(process.cwd(), "../api/services/resources/material_enrichment_seed.json"), "utf8"));
const classification = JSON.parse(readFileSync(resolve(process.cwd(), "../api/services/resources/material_classification_seed.json"), "utf8"));
const pt = "mat:bafe1.906pt0.094as2", cs = "mat:cs(v0.93nb0.07)3sb5";
function recovery(id: string): MaterialEnrichmentReport {
  return {
    version: "materials-enrichment/1.0.0", scientific_acceptance: false, database_changed: false,
    candidates: clone(literal.reports.flatMap((r: { candidates: Array<Record<string, unknown>> }) => r.candidates).filter((r: Record<string, unknown>) => r.material_id === id)),
    classification_candidates: clone(classification.candidates.filter((r: Record<string, unknown>) => r.material_id === id)),
    primary_source_seed: { status: "available", seed_sha256: literal.seed_sha256 },
    classification_primary_source_seed: { status: "available", seed_sha256: classification.seed_sha256 },
    coverage: [{ material_id: id, formula: id === pt ? "BaFe1.906Pt0.094As2" : "Cs(V0.93Nb0.07)3Sb5", fields: [] }], counts: {},
  } as unknown as MaterialEnrichmentReport;
}

describe("Field-specific source observations", () => {
  it("preserves all fifteen original facts, units, windows and source anchors in the public projection", () => {
    const b = loadSourceObservationBatch();
    expect(b?.entries).toHaveLength(15);
    expect(b?.original_batch_sha256).toBe("947e13d7947f27d9d291a3783ad262308babcec14c186de0e5fbf1c70b8a884f");
    expect(b?.prior_source_expression_batch_sha256).toBe("1bdc386c9f67bfa4a454ee17c07910ee72ee49b0f1adfb656dba56a60735fdd2");
    expect(groupSourceObservations(b!.entries).map(g => g.entries.length)).toEqual([5, 3, 3, 4]);
    const file = readFileSync(resolve(process.cwd(), "public/research-pilots/materials-source-observations-2026-10-02.json"));
    const sidecar = readFileSync(resolve(process.cwd(), "public/research-pilots/materials-source-observations-2026-10-02.json.sha256"), "utf8");
    expect(sidecar).toBe(`${createHash("sha256").update(file).digest("hex")}  materials-source-observations-2026-10-02.json\n`);
    expect(b!.entries.every(e => e.selected_result_association === "unestablished")).toBe(true);
  });

  it("keeps the signed slope and competing source model estimates, without a direct 0 K measurement", () => {
    const entries = loadSourceObservationBatch()!.entries.filter(e => e.source_group === "pt");
    expect(entries.slice(0, 3).map(observationValue)).toEqual(["-2.8 T/K", "≈ 45 T", "≈ 65 T"]);
    expect(entries[0].source_role).toBe("source_curve_derived_slope");
    expect(entries[1].source_role).toBe("source_reported_model_estimate");
    expect(entries[1].source_window.model_temperature_k).toBe(0);
    expect(entries[0].source_window.slope_temperature_window_raw).toBe("T<20 K");
    expect(entries[1].source_window.pressure).toBeNull();
  });

  it("does not merge ambient prose and pressure-table fits or turn London lambda into EPC", () => {
    const entries = loadSourceObservationBatch()!.entries.filter(e => e.source_group === "cs_nb");
    expect(entries.map(observationValue)).toEqual(["4.70(3) K", "316(5) nm", "0.590(5) meV", "3.000(6) K", "381 nm", "0.54(9) meV"]);
    expect(groupSourceObservations(entries)).toHaveLength(2);
    expect(entries[0].source_window.pressure_gpa).toBeNull();
    expect(entries[3].source_window.pressure).toMatchObject({ raw_value: "0", value: 0, unit: "GPa" });
    expect(observationLabel(entries[4].field)).toContain("λ(T > 0)");
    expect(entries.some(e => e.field === "lambda_eph")).toBe(false);
  });

  it("only shows paper observations after the actual current seed and source identity appear in this material response", () => {
    expect(sourceObservationsForRecovery(recovery(pt), pt)?.entries).toHaveLength(5);
    expect(sourceObservationsForRecovery(recovery(cs), cs)?.entries).toHaveLength(6);
    expect(sourceObservationsForRecovery(recovery(pt), cs)).toBeNull();
    const lost = recovery(pt);
    lost.candidates = [];
    expect(sourceObservationsForRecovery(lost, pt)).toBeNull();
    const changed = recovery(pt);
    for (const candidate of changed.candidates) (candidate.source as Record<string, unknown>).capture_sha256 = "0".repeat(64);
    expect(sourceObservationsForRecovery(changed, pt)).toBeNull();
    const unknown = recovery(cs);
    unknown.classification_candidates = unknown.classification_candidates!.slice(0, 1);
    expect(sourceObservationsForRecovery(unknown, cs)).toBeNull();
    const moved = recovery(cs);
    (moved.classification_candidates![0].source as Record<string, unknown>).source_revision = "arxiv:2411.18744v2";
    expect(sourceObservationsForRecovery(moved, cs)).toBeNull();
  });

  it("keeps CIF sites and operations as an independent matching revision and refuses stale or admitted provider data", () => {
    const r = { version: "material-crystal-references/1.0.0", provider: "COD", status: "available", scientific_acceptance: false, database_changed: false, sample_identity_established: false, phase_identity_established: false,
      references: [{ id: "1510641", source_revision: "svn:176435", coordinate_model_validated: false, sample_identity_established: false, phase_identity_established: false }] } as unknown as MaterialStructureReferences;
    const w = sourceObservationsForCod(r, "mat:crb2");
    expect(w?.entries).toHaveLength(4);
    expect(w?.selected_result_association).toBe("unestablished");
    expect(w?.entries[0].value).toHaveLength(2);
    expect(w?.entries[1].value).toHaveLength(24);
    const site = (w!.entries[0].value as Array<Record<string, unknown>>)[0];
    expect((site.fractional_coordinates as Array<Record<string, unknown>>)[0]).toMatchObject({ raw_unit: null, unit: "fractional", unit_basis: "cif_fractional_coordinate_field", unit_source_field: "_atom_site_fract_x" });
    expect(site.occupancy).toMatchObject({ raw_unit: null, unit: "dimensionless", unit_source_field: "_atom_site_occupancy" });
    expect(w!.entries[3].value).toMatchObject({ raw_unit: null, unit: "dimensionless", unit_source_field: "_cell_formula_units_Z" });
    expect(sourceObservationsForCod({ ...r, references: [{ ...r.references[0], source_revision: "svn:176436" }] }, "mat:crb2")).toBeNull();
    expect(sourceObservationsForCod({ ...r, scientific_acceptance: true } as unknown as MaterialStructureReferences, "mat:crb2")).toBeNull();
    expect(sourceObservationsForCod({ ...r, status: "no_match", references: [] }, "mat:crb2")).toBeNull();
  });

  it("refuses private nested context, forged authority and changed numeric interpretations", () => {
    const privateSource = clone(publicBatch);
    (privateSource.entries[0].source as Record<string, unknown>).source_status = { private_notes: "must not leave this input" };
    expect(loadSourceObservationBatch(privateSource)).toBeNull();
    const privateWindow = clone(publicBatch);
    (privateWindow.entries[0].source_window as Record<string, unknown>).model_label = { evidence_text: "must not export" };
    expect(loadSourceObservationBatch(privateWindow)).toBeNull();
    const accepted = clone(publicBatch);
    accepted.entries[0].scientific_acceptance = true;
    expect(loadSourceObservationBatch(accepted)).toBeNull();
    const changed = clone(publicBatch);
    (changed.entries[0].value as Record<string, unknown>).value = 2.8;
    expect(loadSourceObservationBatch(changed)).toBeNull();
    const sigma = clone(publicBatch);
    (sigma.entries[5].value as Record<string, unknown>).uncertainty = 3;
    expect(loadSourceObservationBatch(sigma)).toBeNull();
  });

  it("requires real source windows and locators before applying scientific labels or exporting a window", () => {
    const mutations: Array<(entry: Record<string, unknown>, batch: typeof publicBatch) => void> = [
      entry => { entry.source_window = null; },
      entry => { entry.field_locator = null; },
      entry => { (entry.source as Record<string, unknown>).locator = null; },
      entry => { (entry.field_locator as Record<string, unknown>).char_start = 10.5; },
      entry => { (entry.field_locator as Record<string, unknown>).char_end = -1; },
      entry => { (entry.field_locator as Record<string, unknown>).token_sha256 = "invalid"; },
      (_, batch) => { (batch.entries[4].field_locator as Record<string, unknown>).spans = [null]; },
      (_, batch) => { (batch.entries[9].source_window as Record<string, unknown>).raw_row_label = "lambda(0)"; },
      (_, batch) => { (batch.entries[8].source_window as Record<string, unknown>).pressure = null; },
      (_, batch) => { (batch.entries[1].source_window as Record<string, unknown>).model_label = "direct measurement"; },
      (_, batch) => { (batch.entries[11].source as Record<string, unknown>).locator = { private_notes: "must not export" }; },
      (_, batch) => { (batch.entries[11].source as Record<string, unknown>).span = { private_notes: "must not export" }; },
      (_, batch) => { (batch.entries[4].value as Record<string, unknown>).field_direction_raw = "parallel to the a-axis"; },
      entry => { (entry.source as Record<string, unknown>).span = { char_start: 10.5, char_end: -1, text_sha256: "not-a-hash" }; },
    ];
    for (const mutate of mutations) {
      const changed = clone(publicBatch);
      mutate(changed.entries[0] as unknown as Record<string, unknown>, changed);
      expect(loadSourceObservationBatch(changed)).toBeNull();
    }
  });
});
