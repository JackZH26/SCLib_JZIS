import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { getResearchProposalCatalog, parseResearchProposalCatalog, RESEARCH_PROPOSAL_MAX_BYTES } from "@/lib/discovery-proposals";

const hash = (text: string) => createHash("sha256").update(text).digest("hex");
const changed = (edit: (catalog: any) => void) => {
  const catalog = getResearchProposalCatalog();
  edit(catalog);
  return catalog;
};

describe("source-pinned public research proposal catalog", () => {
  it("retains three real coordinate proposals, keeps the host separate, and never assigns a score or approval", () => {
    const catalog = getResearchProposalCatalog();
    expect(catalog.proposals.map(row => row.formula)).toEqual(["Mg7AlB16", "Mg7CaB16", "Mg7B16"]);
    expect(catalog.proposals.map(row => row.structure.atom_count)).toEqual([24, 24, 23]);
    expect(catalog.reference).toEqual({ formula: "MgB2", role: "reference", counts_as_proposal: false });
    expect(catalog).toMatchObject({ formal_scientific_release: false, rps_release: false, human_scientific_review: null });
    expect(catalog.source).toMatchObject({ provider: "COD", record_id: "1526507", revision: 176429,
      cif_sha256: "0eb4eaf6098974db2698bf97a0cd443ffff9a2fc3f6ba8ca31afbebd06c5363d" });
    for (const row of catalog.proposals) {
      expect(row).toMatchObject({ score: null, rank: null, formal_approval: null, status: "unrelaxed" });
      expect(Object.values(row.conditions)).toEqual([null, null, null, null]);
      expect(Object.values(row.physical_axes)).toEqual(Array(6).fill({ status: "unknown", value: null }));
      expect(hash(row.structure.cif_text)).toBe(row.structure.cif_sha256);
      expect(row.structure.cif_text.split("\n").filter(line => /^S\d+ /.test(line))).toHaveLength(row.structure.atom_count);
      expect(row.operation.mg_site_fraction).toBe(1 / 8);
      expect(row.next_action.kind).toBe("state_method_input_review");
    }
    expect(parseResearchProposalCatalog(catalog)).toEqual(catalog);
  });

  it("keeps private paths, identities, costs, inherited runs and Chinese UI prose out of public data", () => {
    const text = JSON.stringify(getResearchProposalCatalog());
    expect(Buffer.byteLength(text)).toBeLessThan(RESEARCH_PROPOSAL_MAX_BYTES);
    expect(text).not.toMatch(/\/Users\/|\/private\/|\/var\/folders\/|jack@|jzis\.org|budget|reviewer_id|user_id|sql_|retained_run|AlB2|\p{Script=Han}/u);
    expect(text).not.toMatch(/"(?:tc|energy|stability)_calculated"\s*:\s*true/);
  });

  it.each([
    ["invented score", (c: any) => { c.proposals[0].score = 5000; }],
    ["invented rank", (c: any) => { c.proposals[0].rank = 1; }],
    ["formal release flag", (c: any) => { c.formal_scientific_release = true; }],
    ["RPS release flag", (c: any) => { c.rps_release = true; }],
    ["human review", (c: any) => { c.human_scientific_review = "approved"; }],
    ["approval", (c: any) => { c.proposals[0].formal_approval = "approved"; }],
    ["assumed ambient pressure", (c: any) => { c.proposals[0].conditions.pressure_gpa = 0; }],
    ["assumed temperature", (c: any) => { c.proposals[0].conditions.temperature_k = 300; }],
    ["physical value", (c: any) => { c.proposals[0].physical_axes.stability.value = 100; }],
    ["missing axis", (c: any) => { delete c.proposals[0].physical_axes.geometry; }],
    ["inherited result", (c: any) => { c.proposals[0].tc = 39; }],
    ["private account", (c: any) => { c.source.account = "private@example.test"; }],
    ["private nested field", (c: any) => { c.proposals[0].structure.path = "/private/source.cif"; }],
    ["unreviewed source revision", (c: any) => { c.source.revision++; }],
    ["source checksum", (c: any) => { c.source.cif_sha256 = "0".repeat(64); }],
    ["mutable source URL", (c: any) => { c.source.cif_url = "https://www.crystallography.net/cod/1526507.cif"; }],
    ["invented source license", (c: any) => { c.source.license = "CC-BY-4.0"; }],
    ["formula substitution", (c: any) => { c.proposals[0].formula = "MgB2"; }],
    ["false composition", (c: any) => { c.proposals[0].structure.composition.Al = 2; }],
    ["wrong atom count", (c: any) => { c.proposals[2].structure.atom_count = 24; }],
    ["wrong site", (c: any) => { c.proposals[0].operation.target.id = "image-0-cell-0-0-1"; }],
    ["wrong fraction", (c: any) => { c.proposals[0].operation.mg_site_fraction = 1 / 24; }],
    ["different CIF", (c: any) => { c.proposals[0].structure.cif_text = c.proposals[1].structure.cif_text; }],
    ["CIF bytes and hash both changed", (c: any) => {
      const structure = c.proposals[0].structure;
      structure.cif_text = structure.cif_text.replace("S1 Al 0 0 0 1", "S1 Al 0.1 0 0 1");
      structure.cif_sha256 = hash(structure.cif_text);
    }],
    ["CIF checksum only", (c: any) => { c.proposals[0].structure.cif_sha256 = "0".repeat(64); }],
    ["duplicate identity", (c: any) => { c.proposals[1] = c.proposals[0]; }],
    ["unknown catalog version", (c: any) => { c.version += "-changed"; }],
    ["changed action claim", (c: any) => { c.proposals[0].next_action.summary = "Predict room-temperature Tc"; }],
  ])("rejects %s", (_name, edit) => {
    expect(() => parseResearchProposalCatalog(changed(edit))).toThrow("Research proposal catalog is invalid.");
  });

  it("bounds malformed data, nonfinite numbers, prototype objects, depth and record count", () => {
    for (const value of [null, [], "catalog", new Date(), { nested: Infinity }]) {
      expect(() => parseResearchProposalCatalog(value)).toThrow();
    }
    expect(() => parseResearchProposalCatalog(changed(c => { c.proposals = Array(101).fill(c.proposals[0]); }))).toThrow();
    expect(() => parseResearchProposalCatalog(changed(c => { c.proposals[0].structure.cif_text = "x".repeat(RESEARCH_PROPOSAL_MAX_BYTES + 1); }))).toThrow();
    const circular: any = {}; circular.self = circular;
    expect(() => parseResearchProposalCatalog(circular)).toThrow();
  });

  it("returns independent copies and permits no caller mutation of the retained catalog", () => {
    const first = getResearchProposalCatalog();
    first.proposals[0].structure.cif_text = "changed";
    first.proposals.pop();
    const second = getResearchProposalCatalog();
    expect(second.proposals).toHaveLength(3);
    expect(hash(second.proposals[0].structure.cif_text)).toBe(second.proposals[0].structure.cif_sha256);
  });
});
