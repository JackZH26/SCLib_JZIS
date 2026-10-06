import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import input from "@/lib/discovery-research-catalogues/2026-10-06-retained-coordinate-proposals-v2.json";
import { getResearchCatalogue, researchCanonicalJson, validateResearchCatalogue } from "@/lib/discovery-research-catalogue";

const clone = () => JSON.parse(JSON.stringify(input));
const hash = (value: unknown) => createHash("sha256").update(researchCanonicalJson(value)).digest("hex");

describe("research catalogue v2 actual retained batches", () => {
  it("uses explicit plain decimal canonical numbers across runtimes", () => {
    expect(researchCanonicalJson({ small: 1e-7, zero: -0, large: 1e21 })).toBe('{"large":1000000000000000000000,"small":0.0000001,"zero":0}');
  });
  it("loads 20 occurrences, 19 coordinate states and eight composition groups", () => {
    const data = getResearchCatalogue();
    expect(data.counts).toEqual({ source_entries: 20, coordinate_states: 19, composition_groups: 8, duplicate_occurrences: 1 });
    expect(data.groups.map(g => [g.formula, g.state_ids.length])).toEqual([
      ["Mg7AlB16", 3], ["Mg7CaB16", 1], ["Mg7B16", 1], ["Mg7AlB15C", 3], ["Mg7AlB15", 3], ["Mg8B15C", 3], ["Mg8B16", 2], ["Mg8B15", 3],
    ]);
    expect(data.states.every(s => s.status === "unrelaxed" && s.score === null && s.rank === null)).toBe(true);
  });
  it("joins the same 0% recipe while retaining both different original CIF byte artifacts", () => {
    const data = getResearchCatalogue();
    const shared = data.states.find(s => s.formula === "Mg7AlB16" && s.strain_micro_percent === 0)!;
    const aliases = data.occurrences.filter(o => o.state_id === shared.id);
    expect(aliases).toHaveLength(2);
    expect(new Set(aliases.map(o => o.cif_sha256)).size).toBe(2);
    expect(aliases.map(o => o.legacy_candidate_id.split(":")[0])).toEqual(["site-candidate", "combined-candidate"]);
    expect(data.states.filter(s => s.formula === "Mg7AlB16").map(s => s.strain_micro_percent)).toEqual([0, -2000000, 2000000]);
  });
  it("does not count the unchanged MgB2 reference or assign pressure to geometric strain", () => {
    const data = getResearchCatalogue();
    const group = data.groups.find(g => g.formula === "Mg8B16")!;
    expect(group.reduced_formula).toBe("MgB2");
    expect(group.state_ids.map(id => data.states.find(s => s.id === id)!.strain_micro_percent)).toEqual([-2000000, 2000000]);
    expect(data.states.every(s => Object.values(s.conditions).every(v => v === null))).toBe(true);
    expect(data.states.every(s => Object.values(s.physical_axes).every(v => v.status === "unknown" && v.value === null))).toBe(true);
  });
  it.each([
    ["source identity", (d: any) => { d.sources[0].record_id = "1510641"; }],
    ["formula", (d: any) => { d.states[0].formula = "Mg8AlB16"; }],
    ["composition", (d: any) => { d.states[0].composition.Mg++; }],
    ["CIF bytes", (d: any) => { d.occurrences[0].cif_text = d.occurrences[0].cif_text.replace("S1 Al", "S1 Ca"); }],
    ["state coordinates", (d: any) => { d.states[0].atoms[1].fractional[0] += 0.01; }],
    ["condition inheritance", (d: any) => { d.states[0].conditions.pressure_gpa = 0; }],
    ["score", (d: any) => { d.states[0].score = 9000; }],
    ["review", (d: any) => { d.human_scientific_review = { approved: true }; }],
    ["formal release", (d: any) => { d.formal_scientific_release = true; }],
    ["RPS release", (d: any) => { d.rps_release = true; }],
    ["physical value", (d: any) => { d.states[0].physical_axes.electronic.value = 10; }],
    ["fake geometry result", (d: any) => { d.states[0].physical_axes.geometry.status = "known"; }],
    ["private metadata", (d: any) => { d.selection_basis = "/Users/private/capture.json"; }],
    ["unrecognized field", (d: any) => { d.states[0].ready = true; }],
    ["counts", (d: any) => { d.counts.coordinate_states = 20; }],
    ["duplicate state", (d: any) => { d.states.push(d.states[0]); }],
    ["missing source occurrence", (d: any) => { d.occurrences.pop(); }],
    ["cross-group state", (d: any) => { d.groups[0].state_ids.push(d.groups[1].state_ids[0]); }],
    ["missing baseline source", (d: any) => { d.parents[0].reference_id = "unknown"; }],
    ["numeric overflow", (d: any) => { d.states[0].cell.a = Infinity; }],
  ])("rejects %s independently of the dataset pin", (_label, mutate) => {
    const candidate = clone(); (mutate as (value: any) => void)(candidate);
    expect(() => validateResearchCatalogue(candidate)).toThrow();
  });
  it("rejects a changed CIF even when its artifact hash and occurrence identity are refreshed", () => {
    const d = clone(), o = d.occurrences[0], oldId = o.id;
    o.cif_text = o.cif_text.replace("S1 Al", "S1 Ca");
    o.cif_sha256 = createHash("sha256").update(o.cif_text).digest("hex");
    o.id = `proposal-occurrence:${hash({ source_batch_sha256: o.source_batch_sha256, source_locator: o.source_locator, legacy_candidate_id: o.legacy_candidate_id, cif_sha256: o.cif_sha256 })}`;
    d.states[0].occurrence_ids = d.states[0].occurrence_ids.map((id: string) => id === oldId ? o.id : id);
    d.states[0].primary_occurrence_id = o.id;
    expect(() => validateResearchCatalogue(d)).toThrow();
  });
  it("returns isolated snapshots and never exposes a mutable shared dataset", () => {
    const first = getResearchCatalogue(); first.states[0].atoms[0].element = "C";
    expect(getResearchCatalogue().states[0].atoms[0].element).toBe("Al");
  });
});
