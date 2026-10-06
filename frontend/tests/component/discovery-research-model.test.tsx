import { beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { getResearchCatalogue } from "@/lib/discovery-research-catalogue";
import { prepareResearchModel } from "@/lib/discovery-research-model";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });

describe("retained proposal to existing coordinate generator", () => {
  it("replays all 19 actual states and preserves original occurrence aliases and conditions", async () => {
    const catalogue = getResearchCatalogue();
    for (const state of catalogue.states) {
      const result = await prepareResearchModel(catalogue, state.id);
      expect(result.batch.candidates).toHaveLength(1);
      expect(result.candidateId).toBe(result.batch.candidates[0].id);
      expect(result.lineage.catalog_state_id).toBe(state.id);
      expect(result.lineage.original_occurrence_ids).toEqual(state.occurrence_ids);
      expect(result.lineage.coordinate_model_equivalent).toBe(true);
      expect(result.batch.candidates[0].composition).toEqual(state.composition);
      expect(result.batch.boundary.pressure_gpa).toBe(null);
      expect(result.batch.boundary.tc_calculated).toBe(false);
    }
  });
  it("retains different original and regenerated CIF hashes for the single-site export", async () => {
    const catalogue = getResearchCatalogue(), state = catalogue.states[0];
    const result = await prepareResearchModel(catalogue, state.id);
    expect(result.lineage.original_occurrence_ids).toHaveLength(2);
    expect(result.lineage.original_cif_sha256).not.toBe(result.lineage.generated_cif_sha256);
    expect(catalogue.occurrences.find(o => o.id === state.primary_occurrence_id)!.cif_sha256).toBe(result.lineage.original_cif_sha256);
  });
  it.each([
    ["source", (d: any) => { d.sources[0].cif_sha256 = "0".repeat(64); }],
    ["parent coordinate", (d: any) => { d.parents[0].atoms[0].fractional[0] = 0.1; }],
    ["state coordinate", (d: any) => { d.states[0].atoms[0].fractional[0] = 0.1; }],
    ["state species", (d: any) => { d.states[0].atoms[0].element = "Ca"; }],
    ["pressure", (d: any) => { d.states[0].conditions.pressure_gpa = 0; }],
    ["temperature", (d: any) => { d.states[0].conditions.temperature_k = 300; }],
    ["charge", (d: any) => { d.states[0].conditions.charge_state = 0; }],
    ["magnetism", (d: any) => { d.states[0].conditions.magnetic_state = "nonmagnetic"; }],
    ["strain", (d: any) => { d.states[0].strain_micro_percent = 1000000; }],
    ["CIF byte", (d: any) => { d.occurrences[0].cif_text += "# changed\n"; }],
    ["invented score", (d: any) => { d.states[0].score = 8000; }],
  ])("rejects changed %s before returning a model", async (_label, mutate) => {
    const catalogue = getResearchCatalogue(); (mutate as (d: any) => void)(catalogue);
    await expect(prepareResearchModel(catalogue, catalogue.states[0].id)).rejects.toThrow();
  });
  it("copies the input before asynchronous hashing", async () => {
    const catalogue = getResearchCatalogue(), id = catalogue.states[0].id;
    const pending = prepareResearchModel(catalogue, id);
    catalogue.states[0].atoms[0].element = "Ca";
    const result = await pending;
    expect(result.batch.candidates[0].atoms[0].element).toBe("Al");
  });
});
