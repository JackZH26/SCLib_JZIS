import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, describe, expect, it, vi } from "vitest";
import { getSourceHypothesisBrowseCatalogue, getSourceHypothesisCatalogue, validateSourceHypothesisCatalogue } from "@/lib/discovery-source-hypotheses";
import { verifySourceHypothesisDetail } from "@/lib/discovery-source-hypothesis-detail";

vi.stubGlobal("crypto", webcrypto);
afterAll(() => vi.unstubAllGlobals());

const catalogue = getSourceHypothesisCatalogue();
const clone = () => JSON.parse(JSON.stringify(catalogue));
const bytes = (url: string) => readFileSync(join(process.cwd(), "public", url.slice(1)));

describe("public source-computed hypotheses", () => {
  it("retains 103 distinct compositions and 280 frozen control occurrences without an RPS or COD state", () => {
    expect(catalogue.candidates).toHaveLength(103);
    expect(new Set(catalogue.candidates.map(row => row.canonical_composition_key)).size).toBe(103);
    expect(catalogue.candidates.reduce((count, row) => count + row.countercontrols.length, 0)).toBe(280);
    expect(catalogue.counts).toEqual({ composition_groups: 103, formal_RPS_scored: 0, human_reviewed: 0, experimental_confirmed: 0, room_temperature_supported: 0 });
    expect(catalogue.candidates.every(row => row.route === "geometry_construction" && row.formal_RPS === null && row.rank === null
      && row.human_scientific_review === null && row.experimental_superconductivity === null && row.room_temperature_support === null
      && row.quantified_physical_bandwidth === null && row.quantified_mobile_carrier_density === null)).toBe(true);
    expect(catalogue.dataset_source).toMatchObject({ license: "CC BY 4.0", version: "Materials Cloud 2023.163 v1", doi: "10.24435/materialscloud:qv-bq" });
  });

  it("preserves source Tc arithmetic, negative lambda tradeoffs and an adverse hydride control", () => {
    const first = catalogue.candidates.find(row => row.formula === "Nb2HfTa")!;
    expect(first.source_tc).toEqual({ target_K: 20.749, control_K: 17.554, delta_K: 3.1950000000000003,
      unit: "K", method: "Eliashberg", mu_star: 0.1, experimental: false, sigma_binding: null });
    expect(first.seven_criteria.novelty).toContain("HfNbTa");
    expect(first.seven_criteria.novelty).not.toContain("Nb2TiMo");
    const tradeoff = catalogue.candidates.find(row => row.formula === "N2TiZr")!;
    expect(tradeoff.lambda_difference.all10!.every(value => value < 0)).toBe(true);
    expect(tradeoff.source_tc.delta_K).toBeCloseTo(0.88, 12);
    const hydride = catalogue.candidates.find(row => row.formula === "HfRu3H")!;
    expect(hydride.countercontrols[0].separate_source_Eli_mu01_target_control).toEqual([[0.1, 14.498], [0.1, 22.108]]);
    expect(hydride.countercontrols[0].target_relative_lambda_gain_percent_range).toEqual([-37.23335488041371, -12.961484120646224]);
    const mn = catalogue.candidates.find(row => row.formula === "Mn4NbRe")!;
    expect(mn.risk_summary).toContain("resolves the specific text-gap concern");
    expect(mn.next_action).toContain("NM/FM/commensurateAF");
  });

  it("uses a small initial projection and separately hash-bound details equal to their full rows", async () => {
    const browse = getSourceHypothesisBrowseCatalogue();
    expect(Buffer.byteLength(JSON.stringify(browse))).toBeLessThan(300 * 1024);
    expect(browse.candidates).toHaveLength(103);
    for (const row of browse.candidates) {
      expect(row).not.toHaveProperty("physical_summary");
      expect(row).not.toHaveProperty("prototype_evidence");
      expect(row).not.toHaveProperty("countercontrols");
      expect(row).not.toHaveProperty("evidence_pins");
      const body = bytes(row.detail.url);
      expect(body.byteLength).toBe(row.detail.bytes);
      expect(createHash("sha256").update(body).digest("hex")).toBe(row.detail.sha256);
      const detail = await verifySourceHypothesisDetail(body, row);
      expect(detail.candidate).toEqual(catalogue.candidates.find(candidate => candidate.id === row.id));
      expect(detail.dataset_source).toEqual(catalogue.dataset_source);
    }
  });

  it("rejects changed bytes and a hash-valid detail for a different material", async () => {
    const [first, second] = getSourceHypothesisBrowseCatalogue().candidates;
    const body = bytes(first.detail.url), altered = Buffer.from(body);
    altered[altered.length - 2] ^= 1;
    await expect(verifySourceHypothesisDetail(altered, first)).rejects.toThrow();
    await expect(verifySourceHypothesisDetail(bytes(second.detail.url), { ...first, detail: second.detail })).rejects.toThrow();
  });

  it("rejects accidental scoring, experimental assertions and mislabeled source units", () => {
    const scored = clone(); scored.candidates[0].formal_RPS = 0.8;
    expect(() => validateSourceHypothesisCatalogue(scored)).toThrow();
    const laboratory = clone(); laboratory.candidates[0].experimental_superconductivity = true;
    expect(() => validateSourceHypothesisCatalogue(laboratory)).toThrow();
    const unit = clone(); unit.candidates[0].source_tc.unit = "eV";
    expect(() => validateSourceHypothesisCatalogue(unit)).toThrow();
    const physicalW = clone(); physicalW.candidates[0].quantified_physical_bandwidth = 5;
    expect(() => validateSourceHypothesisCatalogue(physicalW)).toThrow();
    const Tc = clone(); Tc.candidates[0].source_tc.delta_K += 1;
    expect(() => validateSourceHypothesisCatalogue(Tc)).toThrow();
  });

  it("rejects private custody, duplicate composition and the incompatible coordinate-proposal schema", () => {
    const privateData = clone(); privateData.candidates[0].risk_summary += " /Users/private/source.json";
    expect(() => validateSourceHypothesisCatalogue(privateData)).toThrow();
    const resource = clone(); resource.candidates[0].physical_summary = { resources: { account: "operator" } };
    expect(() => validateSourceHypothesisCatalogue(resource)).toThrow();
    const duplicate = clone(); duplicate.candidates[1] = duplicate.candidates[0];
    expect(() => validateSourceHypothesisCatalogue(duplicate)).toThrow();
    const coordinates = clone(); coordinates.schema_version = "research-proposal-catalog/2.0.0";
    expect(() => validateSourceHypothesisCatalogue(coordinates)).toThrow();
  });
});
